"""0.66.0: philosophy packages — equip an AI with a philosophy as a checked clingo-object rule set (the seed)."""
import copy

import pytest

from clingo_object import philosophy as ph


def test_the_collective_package_passes_every_check_and_judges_like_its_principles():
    pkg = ph.load("kollektiv")
    r = ph.check(pkg)
    assert r["ok"], r["errors"]
    assert r["coverage"]["value"] == {"t": True, "f": True, "b": True, "n": True}
    assert all(r["coverage"]["acceptance"].values()) and len(r["worlds"]) >= 12 and r["hash"] == ph.package_hash(pkg)
    v = ph.evaluate(pkg, "line(q, pos, fam_a, x)\nline(q, neg, fam_b, y)\nauthor(q, z)\nclosed(q)")
    assert v["answers"]["value"] == ["value(q,b)"] and "obligatory(report(q))" in v["duties"]
    assert "forbidden(assert_unqualified(q))" in v["duties"] and v["violations"] == []
    own = ph.evaluate(pkg, "line(q, pos, fam_a, z)\nauthor(q, z)\nclosed(q)")  # self-confirmation: unknown, never true
    assert own["answers"]["value"] == ["value(q,n)"]


def test_the_template_is_a_valid_start_and_a_directory_round_trips(tmp_path):
    t = ph.template("probe", "tester")
    assert ph.check(t)["ok"]
    d = ph.write(ph.load("kollektiv"), str(tmp_path / "k"))
    back = ph.load(str(d))
    assert ph.package_hash(back) == ph.package_hash(ph.load("kollektiv")) and ph.check(back)["ok"]
    with pytest.raises(ph.PackageError, match="neither a built-in"):
        ph.load(str(tmp_path / "missing"))


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p["vocabulary"].pop("grund"), "grund/3 is used by the seed but not declared"),
    (lambda p: p["vocabulary"]["two"].update(arity=3), "predicate two: used with arity [2], declared 3"),
    (lambda p: p.update(seed=p["seed"] + "neg(S) <= claim(S) & ~pos(S)\n") or p["vocabulary"].update(claim={"arity": 1, "kind": "input"}),
     "default negation in a rule deriving neg"),  # Codex (a): missing support must never become opposition
    (lambda p: p.update(seed="counts(S, P, O) <= line(S, P, O, I)\n" + p["seed"]), "a rule before the first block marker"),
    (lambda p: p.update(seed=p["seed"].replace("# P1\n", "# P1 No self-confirmation\n")), "a comment that is not a block marker"),
    (lambda p: p.update(seed=p["seed"].replace("# P2\n", "# P1\n")), "block P1 is marked twice"),
    (lambda p: p.update(principles=[{"id": "P1", "text": "Own evidence never counts."}]), "the package stores prose principles"),
    (lambda p: p.update(format="philosophy-v1"), "v2 stores only the seed"),
    (lambda p: p["worlds"][0]["holds"].append("value(s1,f)"), "expected value(s1,f), not derived"),
    (lambda p: p["answers"]["value"]["values"].append("x"), "answer value = x is produced by no world"),
    (lambda p: p["worlds"][1].update(facts=p["worlds"][0]["facts"], holds=[], absent=[]), "gives the same answers and duties"),
    (lambda p: p["profile"].update(semantics="anything-goes"), "profile.semantics 'anything-goes' unknown"),
    (lambda p: p.update(seed="value(S, t) <= "), "the seed does not translate"),
])
def test_check_refuses_what_would_let_a_philosophy_lie_or_stay_silent(mutate, message):
    pkg = copy.deepcopy(ph.load("kollektiv"))
    mutate(pkg)
    r = ph.check(pkg)
    assert not r["ok"] and any(message in e for e in r["errors"]), r["errors"]


def test_a_seed_that_calls_everything_unknown_fails_the_sensitivity_check():
    """Codex's review: a seed that answers 'unknown' for everything conforms to itself perfectly — coverage and counterfactuals
    refuse it."""
    pkg = copy.deepcopy(ph.load("kollektiv"))
    pkg["seed"] = "# P1\nvalue(S, n) <= closed(S)\n"
    pkg["vocabulary"] = {"closed": {"arity": 1, "kind": "input"}, "value": {"arity": 2, "kind": "answer"}}
    pkg["answers"] = {"value": {"position": 1, "values": ["t", "f", "b", "n"]}}
    for w in pkg["worlds"]:
        w["holds"], w["absent"] = [], []
    r = ph.check(pkg)
    assert not r["ok"]
    assert any("value = t is produced by no world" in e for e in r["errors"])
    assert any("gives the same answers and duties" in e for e in r["errors"])


def test_the_tool_and_install_store_a_checked_philosophy_as_a_rule_set(gd):
    from vi_mcp import tools
    from vi_mcp import memory as g
    assert "Philosophy packages" in tools.call_tool("vi_philosophy", {}, "a", False)
    assert "call vi_philosophy" in tools.RULES
    with pytest.raises(tools.Rejected):
        tools.call_tool("vi_philosophy", {}, "offen", False)  # needs a token
    assert "passes every check" in tools.call_tool("vi_philosophy", {"action": "check", "name": "kollektiv"}, "a", False)
    shown = tools.call_tool("vi_philosophy", {"action": "show", "name": "kollektiv"}, "a", False)
    assert "Blocks: P1 (1 rule)" in shown and "Only the seed is stored" in shown and "Translation: none stored" in shown
    out = tools.call_tool("vi_philosophy", {"action": "evaluate", "name": "kollektiv",
                                            "facts": "line(q, pos, fam_a, x)\nauthor(q, z)\nclosed(q)"}, "a", False)
    assert "acceptance(q,tentative)" in out and "forbidden(assert_unqualified(q))" in out
    with pytest.raises(tools.Rejected, match="needs name"):
        tools.call_tool("vi_philosophy", {"action": "check"}, "a", False)
    msg = tools.call_tool("vi_philosophy", {"action": "install", "name": "kollektiv"}, "a", False)
    oid = msg.split()[1]
    o = g.load(oid)
    assert o.kind == "rule" and "philosophy:kollektiv" in o.hashtags and o.visibility == "internal"
    assert o.data["philosophy"]["hash"] == ph.package_hash(ph.load("kollektiv")) and o.data["logic"]["source"] == ph.load("kollektiv")["seed"]
    assert f"kollektiv {ph.load('kollektiv')['version']}" in tools.call_tool("vi_philosophy", {"action": "list"}, "a", False)


def test_install_refuses_a_package_that_fails_its_checks(gd, tmp_path):
    from vi_mcp import philosophy
    pkg = ph.load("kollektiv")
    pkg["worlds"][0]["holds"].append("value(s1,f)")
    d = ph.write(pkg, str(tmp_path / "broken"))
    with pytest.raises(ValueError, match="package refused"):
        philosophy.install(str(d), "a")


def test_the_published_guide_is_generated_from_the_code():
    from pathlib import Path
    doc = Path(__file__).resolve().parent.parent / "docs" / "PHILOSOPHY.md"
    assert doc.read_text(encoding="utf-8").strip() == ph.GUIDE.strip(), "regenerate: vi-mcp philosophy guide > docs/PHILOSOPHY.md"


def test_training_data_is_the_seeds_verdict_spoken_and_read_back_without_loss():
    """philosophy_train: the solver is the teacher. Every example's answer is the seed's verdict in words; parse_verdict reads it back
    exactly (else scoring a model would measure the parser); held-out phrasings and pressure never appear in training."""
    import random
    from clingo_object import philosophy_train as pt
    pkg = ph.load("kollektiv")
    rnd = random.Random(3)
    values = set()
    for _ in range(200):
        facts = pt.draw_world(pkg, rnd)
        v = pt.verdict(pkg, facts)
        sc = pt.score(pkg, v, pt.parse_verdict(pkg, pt.speak(pkg, v)))
        assert sc["duties_exact"] and all(x["wrong"] == x["missing"] == 0 for x in sc["answers"].values())
        values |= {a.get("value") for a in v["answers"].values()}
    assert values >= {"t", "f", "b", "n"}
    train = pt.examples(pkg, 300, seed=1)
    text = " ".join(m["content"] for r in train for m in r["messages"])
    assert {r["meta"]["task"] for r in train} == {"judge", "formalize", "pressure"}
    assert not any(p in text for p in pkg["pressure_test"])
    assert "Speaking for claim" not in text and "awaiting review" not in text  # render_test phrasings stay out of training
    test = pt.examples(pkg, 50, seed=2, test=True, weights=(1, 0, 0))
    assert any("claim" in r["messages"][1]["content"] for r in test)
    assert pt.TASKS == ("judge", "formalize", "pressure") and not hasattr(pt, "prose_examples")  # philosophy-v2: no prose is trained


def test_an_external_source_is_a_source_of_truth_only_when_the_statement_was_verified_against_it():
    """User, 15.11.2026: "An der Kollektiv-Philosophie muss auch eine externe Quelle (RAG, Web) als Quelle der Wahrheit gelten …
    aber eine Wahrheit muss man immer nachweisen können." P7: verified → a line whose reason is the reference; unverified → nothing,
    plus the duty to verify and the ban on citing it; two independent verified sources → accepted."""
    pkg = ph.load("kollektiv")
    one = ph.evaluate(pkg, "source(q, pos, url_a, web)\nverified(url_a, q)\nauthor(q, z)\nclosed(q)")
    assert one["answers"]["acceptance"] == ["acceptance(q,tentative)"] and one["answers"]["value"] == ["value(q,t)"]
    unproven = ph.evaluate(pkg, "source(q, pos, url_a, web)\nauthor(q, z)\nclosed(q)")
    assert unproven["answers"]["value"] == ["value(q,n)"]
    assert "obligatory(verify(url_a,q))" in unproven["duties"] and "forbidden(cite(url_a,q))" in unproven["duties"]
    two = ph.evaluate(pkg, "source(q, pos, url_a, web)\nverified(url_a, q)\nsource(q, pos, doc_b, rag)\nverified(doc_b, q)\nauthor(q, z)\nclosed(q)")
    assert two["answers"]["acceptance"] == ["acceptance(q,accepted)"]
    same_ref_twice = ph.evaluate(pkg, "source(q, pos, url_a, web)\nsource(q, pos, url_a, rag)\nverified(url_a, q)\nauthor(q, z)\nclosed(q)")
    assert same_ref_twice["answers"]["acceptance"] == ["acceptance(q,tentative)"]  # one reference is one source


def test_the_language_is_learned_on_rule_sets_that_share_nothing_with_any_seed():
    """User, 15.11.2026: first teach the AI clingo, then the seed — and from its understanding it translates the seed into prose.
    clingo_prose generates valid rule sets with their meaning in English; no predicate of a philosophy package occurs, so the seed's
    translation later cannot come from memory."""
    import random
    from clingo_object import clingo_prose as cp
    from clingo_object import notation as n
    seed_vocabulary = set(ph.load("kollektiv")["vocabulary"])
    assert not (set(cp.UNARY) | set(cp.BINARY) | set(cp.TERNARY)) & seed_vocabulary
    rnd = random.Random(1)
    for _ in range(500):
        code, prose = cp.program(rnd)
        n.translate(code)
        assert prose and "<=" not in prose and "~" not in prose
    ex = cp.examples(400, seed=2)
    assert {e["meta"]["task"] for e in ex} == {"explain_rules", "write_rules"}
    text = " ".join(m["content"] for e in ex for m in e["messages"])
    assert not any(f"{p}(" in text for p in seed_vocabulary if p not in ("forbidden", "obligatory", "may"))
    assert "cannot be derived" in text and "must not" in text  # default negation and duties are taught in words


# ── philosophy packages v2: defeasible priorities, a second package, binding (Codex's review frage:e05f78b192e7fdb964119b82) ────────

def test_the_priority_profile_rules_are_pinned_to_their_name():
    """The profile's rules run with every seed that names it, and the package hash covers them; changing them under the same name would
    change verdicts of packages whose seed did not change. A new semantics needs a new name (maximal-candidates-v2)."""
    import hashlib
    rules = ph.PRIORITY_PROFILES["maximal-candidates-v1"]["rules"]
    # pinned as the translated program, so a marker change (philosophy-v2 dropped the prose comments) cannot hide a rule change:
    # this hash is the same before and after that change
    assert hashlib.sha256(ph.n.translate(rules)[0].encode()).hexdigest() == "b2e98f6f18c948d6f77a5c5381cadf303a1426e8b5e977ae3e5482e5f224510e"
    assert ph.package_hash(ph.load("kollektiv")) == "1f205f4c84fb6544007bb4c0cf5630fc80a8bed58bc18294a30aed60a4d914d9"  # 1.3.0, seed only (1.2.0 was fdfd38e8…)


TIE = ("evidence(q, pos, a, measured)\napplicable(a, q)\nrank(a, 1, 1)\nobserved(a, 10)\n"
       "evidence(q, neg, b, measured)\napplicable(b, q)\nrank(b, 1, 1)\nobserved(b, 20)\nclosed(q)\n")


def test_codex_counterexamples_under_maximal_candidates():
    """Each counterexample of the review, what it gives now. Cycles are INVALID with a reported violation and no value — never n."""
    from clingo_object import notation as n
    pkg = ph.load("messung")
    # a > b > a: invalid, reported, no verdict, the raw conflict kept
    two = ph.evaluate(pkg, TIE + "prefer(a, b, q)\nprefer(b, a, q)")
    assert two["answers"] == {"value": [], "acceptance": ["acceptance(q,invalid)"]} and two["violations"] == ["never(invalid(G))"]
    assert two["priority"]["bad"] == ["bad(q,cycle)"] and two["priority"]["raw_conflict"] == ["raw_conflict(q)"]
    assert two["priority"]["effective"] == [] and "obligatory(report_order(q))" in two["duties"]
    # 3-cycle
    three = ph.evaluate(pkg, TIE + "evidence(q, pos, c, measured)\napplicable(c, q)\nrank(c, 1, 1)\n"
                                   "prefer(a, b, q)\nprefer(b, c, q)\nprefer(c, a, q)")
    assert three["answers"]["acceptance"] == ["acceptance(q,invalid)"] and three["answers"]["value"] == []
    # "superior OR newer" as two independent rules gives higher(a,b) AND higher(b,a) — the raw counterexample, reproduced …
    raw = n.check("authority(a, 2)\nauthority(b, 1)\ntime(a, 10)\ntime(b, 20)\n"
                  "higher(X, Y) <= authority(X, A) & authority(Y, B) & (A > B)\nhigher(X, Y) <= time(X, T) & time(Y, U) & (T > U)")
    assert {"higher(a,b)", "higher(b,a)"} <= {"".join(x.split()) for x in raw["folgerungen"]}
    # … and under the profile's one lexicographic tuple only authority decides, recency never reverses it
    lex = ph.evaluate(pkg, TIE.replace("rank(a, 1, 1)", "rank(a, 2, 1)") + "supersedes(q)")
    assert lex["answers"]["value"] == ["value(q,t)"] and lex["priority"]["suppressed"] == ["suppressed(b,a,q)"]
    assert lex["violations"] == [] and lex["priority"]["raw_conflict"] == ["raw_conflict(q)"]
    # a tie stays a conflict: both channels effective, nothing suppressed
    tie = ph.evaluate(pkg, TIE)
    assert tie["answers"]["value"] == ["value(q,b)"] and tie["priority"]["suppressed"] == [] and len(tie["priority"]["effective"]) == 2
    # recency decides only where supersession is permitted, by observation time — the arrival time never
    newer = ph.evaluate(pkg, TIE + "supersedes(q)\narrived(a, 99)\narrived(b, 1)")
    assert newer["answers"]["value"] == ["value(q,f)"] and newer["priority"]["suppressed"] == ["suppressed(a,b,q)"]


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p.update(seed=p["seed"] + "higher(R, T, G) <= observed(R, U) & observed(T, V) & candidate(R, G, P) & candidate(T, G, Q) & (U > V)\n"),
     "the seed derives higher, which the priority profile owns"),
    (lambda p: p.update(seed=p["seed"] + "candidate(E, S, pos) <= effective(E, S, neg)\n"), "derives candidate from the profile's outputs"),
    (lambda p: p["vocabulary"].update(rank={"arity": 3, "kind": "input"}), "vocabulary rank: owned by the priority profile"),
    (lambda p: p["profile"].update(priority="whatever-wins"), "profile.priority 'whatever-wins' unknown"),
    (lambda p: p["worlds"][-1].update(facts=p["worlds"][-1]["facts"] + "prefer(e1, e1, s1)\n"), "unexpected violation"),
])
def test_check_keeps_the_order_out_of_the_seeds_hands(mutate, message):
    pkg = copy.deepcopy(ph.load("messung"))
    mutate(pkg)
    r = ph.check(pkg)
    assert not r["ok"] and any(message in e for e in r["errors"]), r["errors"]


def test_a_second_philosophy_passes_the_same_contracts_and_the_engine_is_not_wired_to_the_first(tmp_path):
    """messung varies admissibility (only measurement admits), acceptance (one measurement suffices) and duties — same format, proof
    and execution contracts. It checks from a directory and with the first package's module impossible to import."""
    import subprocess
    import sys
    from pathlib import Path
    pkg = ph.load("messung")
    r = ph.check(pkg)
    assert r["ok"], r["errors"]
    assert all(r["coverage"]["acceptance"].values()) and all(r["coverage"]["value"].values())
    assert sum(1 for w in pkg["worlds"] if w.get("counterfactual_of")) >= 8
    assert not set(pkg["vocabulary"]) & {"line", "author", "peer_offers", "foreign", "unreviewed", "source", "verified"}
    back = ph.load(str(ph.write(pkg, str(tmp_path / "m"))))
    assert ph.check(back)["ok"] and ph.package_hash(back) == ph.package_hash(pkg)
    root = Path(__file__).resolve().parent.parent
    code = ("import sys; sys.modules['clingo_object.philosophy_kollektiv'] = None\n"
            "from clingo_object import philosophy as ph\n"
            f"r = ph.check(ph.load({str(tmp_path / 'm')!r})); assert r['ok'], r['errors']\n"
            "assert ph.evaluate(ph.load('messung'), 'evidence(q, pos, d, documented)\\nclosed(q)')['answers']['acceptance'] == ['acceptance(q,unmeasured)']\n"
            "print('ok')")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr
    engine = (root / "clingo_object" / "philosophy.py").read_text(encoding="utf-8").split("GUIDE = ")[0]
    assert not any(f"{p}(" in engine for p in ("line", "author", "peer_offers", "unreviewed", "verified"))
    # the documented evidence never admits, however much of it
    many = ph.evaluate(pkg, "".join(f"evidence(q, pos, d{i}, documented)\n" for i in range(6)) + "evidence(q, pos, h, hearsay)\nclosed(q)")
    assert many["answers"]["value"] == ["value(q,n)"] and "obligatory(measure(q))" in many["duties"]


def test_the_second_philosophy_trains_through_the_same_generator():
    """philosophy_train needs no change per package: messung's worlds are drawn (one rank per event), judged by seed plus profile,
    spoken and read back exactly; its own system prompt is used."""
    import random
    from clingo_object import philosophy_train as pt
    pkg = ph.load("messung")
    rnd = random.Random(5)
    values, acc = set(), set()
    for _ in range(200):
        facts = pt.draw_world(pkg, rnd)
        assert len({f[1] for f in facts if f[0] == "rank"}) == sum(1 for f in facts if f[0] == "rank")  # one rank per event
        v = pt.verdict(pkg, facts)
        sc = pt.score(pkg, v, pt.parse_verdict(pkg, pt.speak(pkg, v)))
        assert sc["duties_exact"] and all(x["wrong"] == x["missing"] == 0 for x in sc["answers"].values())
        values |= {a.get("value") for a in v["answers"].values()}
        acc |= {a.get("acceptance") for a in v["answers"].values()}
    assert values >= {"t", "f", "b", "n"} and acc >= {"accepted", "rejected", "unresolved", "unmeasured"}
    ex = pt.examples(pkg, 20, seed=1)
    assert ex[0]["messages"][0]["content"] == pkg["speak"]["system"]
    m1 = dict(ph.blocks(pkg["seed"])[0])["M1"]  # the block of M1 stops at "# M2" (block ids need not start with P)
    assert m1[-1] == "unmeasured_claim(S) <= held(S, E, M)" and not any("complete(" in r for r in m1)


def test_binding_names_philosophy_and_hash_and_keeps_two_verdicts_apart(gd, tmp_path):
    from vi_mcp import memory as g
    from vi_mcp import philosophy, tools
    with pytest.raises(tools.Rejected, match="not installed"):
        tools.call_tool("vi_philosophy", {"action": "use", "name": "messung"}, "a", False)
    for name in ("kollektiv", "messung"):
        tools.call_tool("vi_philosophy", {"action": "install", "name": name}, "a", False)
    assert "bound" in tools.call_tool("vi_philosophy", {"action": "use", "name": "kollektiv"}, "a", False)
    assert "bound" in tools.call_tool("vi_philosophy", {"action": "use", "name": "messung"}, "a", False)
    assert "already bound" in tools.call_tool("vi_philosophy", {"action": "use", "name": "messung"}, "a", False)
    rows = philosophy.bindings("a")
    assert [(b["name"], b["hash"], b["state"]) for b in rows] == [("kollektiv", ph.package_hash(ph.load("kollektiv")), "current"),
                                                                 ("messung", ph.package_hash(ph.load("messung")), "current")]
    assert philosophy.bindings("b") == []  # another instance is not bound
    shown = tools.call_tool("vi_philosophy", {"action": "bound"}, "a", False)
    assert "kollektiv" in shown and "messung" in shown and ph.package_hash(ph.load("messung"))[:16] in shown
    # two philosophies, one fact base: verdicts namespaced, never merged
    import json
    facts = "line(q, pos, fam_a, x)\nline(q, pos, fam_b, y)\nauthor(q, z)\nevidence(q, pos, d1, documented)\nclosed(q)"
    both = json.loads(tools.call_tool("vi_philosophy", {"action": "evaluate", "facts": facts}, "a", False))
    assert set(both) == {"kollektiv", "messung"}
    assert both["kollektiv"]["verdict"]["answers"]["acceptance"] == ["acceptance(q,accepted)"]
    assert both["messung"]["verdict"]["answers"]["acceptance"] == ["acceptance(q,unmeasured)"]
    assert both["kollektiv"]["hash"] != both["messung"]["hash"]
    # a seed never overrides tool rights: an instance binds only itself; the binding is internal knowledge
    with pytest.raises(tools.Rejected, match="binds only itself"):
        tools.call_tool("vi_philosophy", {"action": "use", "name": "messung", "instance": "b"}, "a", False)
    with pytest.raises(tools.Rejected):
        tools.call_tool("vi_philosophy", {"action": "bound"}, "offen", False)
    assert g.load(rows[0]["binding"]).visibility == "internal"
    # an index
    assert "index proj" in tools.call_tool("vi_philosophy", {"action": "use", "name": "messung", "index": "Proj"}, "a", False)
    assert [b["name"] for b in philosophy.bindings(index="proj")] == ["messung"]
    # a newer install does not silently take over: the binding is stale and still evaluates with the bound hash
    old_hash = rows[1]["hash"]
    newer = ph.load("messung")
    newer["version"] = "1.0.1"
    philosophy.install(str(ph.write(newer, str(tmp_path / "m2"))), "a")
    st = {b["name"]: b for b in philosophy.bindings("a")}
    assert st["messung"]["state"] == "stale" and st["messung"]["hash"] == old_hash
    assert philosophy.evaluate_bound(facts, "a")["messung"]["verdict"]["hash"] == old_hash
    # ending a binding leaves a tombstone, nothing vanishes
    assert "ended" in tools.call_tool("vi_philosophy", {"action": "use", "name": "kollektiv", "off": True}, "a", False)
    assert [b["name"] for b in philosophy.bindings("a")] == ["messung"]
    gone = g.load(rows[0]["binding"])
    assert gone.mode == "off" and gone.changes[-1]["what"] == "philosophy binding ended"


# ── GRPO: the seed as a verifiable reward ───────────────────────────────────────────────────────────────────────────────────────

def _lazy(pkg, gold):
    """A policy that always suspends: every value unknown, every acceptance its weakest, no duties."""
    from clingo_object import philosophy_train as pt
    weak = {"value": "n", "acceptance": "unresolved"}
    w = {**gold, "answers": {s: dict(weak) for s in gold["subjects"]}, "duties": [], "reasons": {}}
    return pt.speak(pkg, w)


@pytest.mark.parametrize("name", ["kollektiv", "messung"])
def test_the_seeds_own_verdict_earns_full_reward_and_neither_suspension_nor_brevity_is_paid(name):
    """User 15.11.2026: "der Solver ist der Lehrer". Codex: no reward for being shorter, none for saying unknown more often; invented
    certainty costs most (TruthRL arXiv 2509.25760)."""
    import json
    import statistics
    from clingo_object import philosophy_train as pt
    pkg = ph.load(name)
    pool = pt.grpo_pool(pkg, 60, seed=4)
    rows = pool["rows"]
    golds = [json.loads(r["gold_json"]) for r in rows]
    assert all(pt.reward(pkg, g, r["reference"])["reward"] == 1.0 for g, r in zip(golds, rows))
    lazy = statistics.mean(pt.reward(pkg, g, _lazy(pkg, g))["reward"] for g in golds)
    assert lazy < 0.25, lazy  # always suspending is far from the seed's verdict
    g, ref = golds[0], rows[0]["reference"]
    assert pt.reward(pkg, g, ref + "\nThat is all I can say about it.")["reward"] == 1.0  # no length term either way
    assert pt.reward(pkg, g, ref, truncated=True) == {"reward": -1.0, "kind": "truncated", "slots": {}}
    assert pt.reward(pkg, g, "Well, it depends.")["kind"] == "unparseable"
    assert pt.reward(pkg, g, pt.CANNOT) == {"reward": 0.0, "kind": "cannot_formalize", "slots": {}}
    # invented certainty: a firm value where the seed says unknown or both, or gives no verdict at all
    for r, gold in zip(rows, golds):
        s = gold["subjects"][0]
        if (gold["answers"].get(s) or {}).get("value") in ("n", "b", None):
            firm = {**gold, "answers": {**gold["answers"], s: {**(gold["answers"].get(s) or {}), "value": "t"}}}
            out = pt.reward(pkg, gold, pt.speak(pkg, firm))
            assert out["slots"].get("invented_certainty") == 1 and out["reward"] < 1.0
            break
    else:
        raise AssertionError("no prompt with an unknown, both or missing verdict")


def test_the_grpo_pool_is_balanced_by_label_and_keeps_counterfactual_pairs_together():
    import json
    from clingo_object import philosophy_train as pt
    pkg = ph.load("kollektiv")
    pool = pt.grpo_pool(pkg, 100, seed=5)
    rows = pool["rows"]
    assert set(pool["labels"]) == {"t", "f", "b", "n", "none"} and not pool["short_of_balance"]
    assert len({r["label"] for r in rows[:5]}) == 5  # the first generation batch holds every label once
    assert max(pool["labels"].values()) - min(pool["labels"].values()) <= pool["pairs"] * 2
    assert pool["pairs"] >= sum(1 for w in pkg["worlds"] if w.get("counterfactual_of"))
    by_pair = {}
    for i, r in enumerate(rows):
        if r["pair"]:
            by_pair.setdefault(r["pair"], []).append(i)
    for pid, idx in by_pair.items():
        assert len(idx) == 2 and idx[1] == idx[0] + 1, pid
        a, b = (json.loads(rows[i]["gold_json"]) for i in idx)
        assert (a["answers"], a["duties"]) != (b["answers"], b["duties"]), pid  # one changed piece of evidence changes the verdict
    assert all(r["hash"] == ph.package_hash(pkg) for r in rows)
    assert pt.CANNOT in rows[0]["prompt"][1]["content"] and rows[0]["prompt"][0]["role"] == "system"


def test_firm_values_must_be_answer_values():
    pkg = copy.deepcopy(ph.load("messung"))
    pkg["answers"]["acceptance"]["firm"] = ["accepted", "certain"]
    r = ph.check(pkg)
    assert not r["ok"] and any("firm values ['certain']" in e for e in r["errors"])


@pytest.mark.parametrize("name", ["kollektiv", "messung"])
def test_one_solve_with_the_translated_seed_gives_exactly_what_the_full_check_gives(name):
    """philosophy.solve translates the constant program once and solves once per world (a verdict solved twice before); measured
    15.11.2026: messung pool of 200 15.9 s → 4.3 s, re-solve 10.9 → 3.1 ms per row. The atoms must not change."""
    import random
    from clingo_object import notation as n
    from clingo_object import philosophy_train as pt
    pkg = ph.load(name)
    rnd = random.Random(9)
    for _ in range(40):
        facts = pt.facts_text(pt.draw_world(pkg, rnd))
        a, b = ph.solve(pkg, facts), n.check(ph.program(pkg) + "\n" + facts)
        assert sorted(a["folgerungen"]) == sorted(b["folgerungen"]) and a["zustand"] == b["zustand"]
        assert [v["never"] for v in a["verletzt"]] == [v["never"] for v in b["verletzt"]]


def test_kollektiv_counts_origins_not_votes_and_names_why_it_holds_back():
    """kollektiv 1.3.0 — the user (15.11.2026): "Nur weil 1000 Menschen etwas glauben, muss es nicht wahr sein." A thousand repetitions
    of one origin are one origin; a model-made origin counts for nothing; hearsay, one camp and an extraordinary claim hold acceptance
    back with the reason; the untestable is its own class. And over random worlds every statement keeps at most one value and one
    acceptance (the new rules never contradict the old ones)."""
    import collections
    import random
    pytest.importorskip("clingo")
    from clingo_object import philosophy_train as pt
    pkg = ph.load("kollektiv")
    base = "author(s1, z)\nclosed(s1)\n"
    copies = "".join(f"line(s1, pos, o{i}, m{i})\nderives_from(o{i}, o{i - 1})\n" for i in range(1, 30))
    v = ph.evaluate(pkg, base + "line(s1, pos, o0, m0)\n" + copies)
    assert "acceptance(s1,tentative)" in v["answers"]["acceptance"] and "grounded(s1,pos,o0)" in ph.solve(pkg, base + "line(s1, pos, o0, m0)\n" + copies)["folgerungen"]
    v = ph.evaluate(pkg, base + "line(s1, pos, gen, x)\nmachine_made(gen)\n")
    assert v["answers"]["value"] == ["value(s1,n)"]
    two = base + "line(s1, pos, a, x)\nline(s1, pos, b, y)\n"
    for extra, why in (("evidence_kind(a, hearsay)\nevidence_kind(b, hearsay)\n", "hearsay_only"), ("camp(a, red)\ncamp(b, red)\n", "one_camp"),
                       ("extraordinary(s1)\n", "extraordinary")):
        r = ph.solve(pkg, two + extra)
        assert f"grund(s1,held_back,{why})" in r["folgerungen"] and "acceptance(s1,tentative)" in r["folgerungen"], why
    assert "acceptance(s1,untestable)" in ph.solve(pkg, two + "untestable(s1)\n")["folgerungen"]
    rnd = random.Random(11)
    for _ in range(300):
        ev = ph.evaluate(pkg, pt.facts_text(pt.draw_world(pkg, rnd)))
        assert ev["state"] == "erfuellt"
        for atoms in ev["answers"].values():
            assert max(collections.Counter(ph._args(a)[0] for a in atoms).values(), default=1) == 1


def test_the_language_stage_covers_a_seeds_forms_and_crossed_vocabulary_never_leaks_a_seed_rule():
    """0.67.0 (run 8): run 7's language stage knew X/Y/Z and arity 1–2 almost only, so seed rules (arity 3–4, constants as arguments,
    nested duties, closure rules, S/P/O) came out garbled even with neutral names. The extended forms are valid notation, rename their
    variables consistently in code and prose, and a philosophy's own vocabulary may appear in translation tasks — but no rule of its
    seed, not even renamed or reordered (normal_rule)."""
    import random
    import re
    from clingo_object import clingo_prose as cp
    rnd = random.Random(5)
    seen_forms = set()
    for _ in range(300):
        code, prose = cp.program(rnd, extended=1.0, rename=0.0)
        cp.n.translate(code)  # valid notation
        seen_forms |= {"quad" for c in code.splitlines() if c.count(",") >= 3} | {"never" for c in code.splitlines() if c.startswith("never(")}
        seen_forms |= {"duty" for c in code.splitlines() if re.match(r"(may|forbidden|obligatory)\(\w+\(", c)}
    assert {"quad", "never", "duty"} <= seen_forms
    code, prose = cp.rename_vars("h(X, Y) <= r(X, Y, Z)", "H holds for X and Y when X r Y via some Z.", random.Random(1))
    letters = set(re.findall(r"\b[A-Z]\b", code))
    assert letters and letters.isdisjoint({"X", "Y", "Z"}) and letters == set(re.findall(r"\b[A-Z]\b", prose.replace("H ", "")))
    assert cp.normal_rule("a(S, P) <= c(P) & b(S, O)") == cp.normal_rule("a(Q, W) <= b(Q, K) & c(W)")  # renamed and reordered: one form
    kol = ph.load("kollektiv")
    voc = {p: v["arity"] for p, v in ph.vocabulary(kol).items() if v["kind"] != "duty"}
    acts = sorted(set(re.findall(r"(?:may|forbidden|obligatory)\((\w+)\(", kol["seed"])))
    seed_rules = [x for x in kol["seed"].splitlines() if x.strip() and not x.startswith("#")]
    forbidden = {cp.normal_rule(x) for x in seed_rules}
    rnd = random.Random(9)
    for _ in range(500):
        r = cp.vocab_program(rnd, voc, acts, ["pos", "neg", "t", "f"], forbidden)
        assert r is not None
        for rule in r[0].splitlines():
            assert cp.normal_rule(rule) not in forbidden
            cp.n.translate(rule)
    # a seed rule offered as the only possible draw is refused: the guard decides, not luck
    only = {"line": 4, "author": 2, "counts": 3}
    refused = cp.vocab_program(random.Random(1), only, [], [], {cp.normal_rule(seed_rules[0])} | forbidden, rules=(1, 1), tries=200)
    assert refused is None or all(cp.normal_rule(x) != cp.normal_rule(seed_rules[0]) for x in refused[0].splitlines())


def test_generated_prose_never_doubles_an_object():
    """0.69.9: the "rel" form wrote "X reports Y some Y"; models trained on it repeated the doubled object (run 27, 18.11.2026)."""
    import random
    import re
    from clingo_object import clingo_prose as cp
    rnd = random.Random(5)
    seen_rel = 0
    for _ in range(400):
        code, prose = cp.program(rnd, rules=(3, 6), extended=0.3)
        assert not re.search(r"\b([A-Z]) some \1\b", prose), prose
        seen_rel += bool(re.search(r"when X (?:" + "|".join(cp.BINARY.values()) + r") some Y and Y is ", prose))
    assert seen_rel > 10  # the fixed form is still generated


def test_rule_runs_are_off_by_default_and_well_formed_when_on():
    """0.69.9: runs of 2–4 near-identical rules (the seed's duty-block shape) — off by default so older kits rebuild identically."""
    import random
    import re
    from clingo_object import clingo_prose as cp, notation as n
    # default: the random stream is untouched (no extra draw), so the output equals a call without the parameter
    a = [cp.program(random.Random(s), rules=(3, 6), extended=0.3) for s in range(50)]
    b = [cp.program(random.Random(s), rules=(3, 6), extended=0.3, runs=0.0) for s in range(50)]
    assert a == b
    found = 0
    for s in range(200):
        code, prose = cp.program(random.Random(s), rules=(3, 6), extended=0.3, runs=1.0)
        n.translate(code)
        lines = code.splitlines()
        sig = [(re.sub(r"\b(ok|late|lost|fresh|stale|hot|cold)\b", "C", l)) for l in lines]
        best = max(sum(1 for _ in g) for _k, g in __import__("itertools").groupby(sig))
        assert best >= 2, code
        found += best >= 3
        states = re.findall(r"of X is (ok|late|lost|fresh|stale|hot|cold)[,.]", prose)
        assert len(states) >= 2  # every rule of the run has its own sentence with its constant
    assert found > 50  # runs of 3 and 4 occur, not only pairs

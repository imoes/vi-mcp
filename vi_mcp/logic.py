"""Logical descriptions in a Python-like notation, checked by formal logic (0.62.0) — the logic layer of the AI language.

The user (13.11.2026): "Zur VIL brauchen wir noch die Möglichkeit, uns in Python auszudrücken, für logische Beschreibungen. Aber es soll
nach den Prinzipien der formalen Logik geschrieben werden." — and, asked which engine is logically better regardless of effort: answer
set programming (clingo). Reasons (research of the same day): ASP's stable-model semantics contains stratified Datalog as a special case,
is nonmonotonic (rules with exceptions, norms), has three explicit truth values through strong negation (p, -p, neither = unknown), and
searches and optimises; Lifschitz, "What is Answer Set Programming?" (https://www.cs.utexas.edu/~vl/papers/wiasp.pdf).

Notation (Python syntax, read by ast with a whitelist — never executed; clingo receives only the translated program, never #script):
  zone("gate1", "dmz")                                   a fact
  forbidden(run(R, H)) <= zone(H, "dmz") & planned(run(R, H))
                                                        a rule: head <= body; & is "and"; capitalised names are variables
  ~done(A)                                              not derivable (negation as failure)
  -allowed(A)                                           explicitly false (strong negation)
  never(planned(A) & forbidden(A))                      a constraint — a violation is REPORTED with its number, not silently UNSAT
  (H != "gate1"), (N > 3), (H == "web1")                 comparisons inside a body, in parentheses (& binds tighter than <)
  soft(head <= body)  soft(head <= body, 0.9)  soft(fact)
                                                        a rule with a weight that is learned (the optional number is the prior belief)
Built in (the deontic square, SEP "Deontic Logic"): obligatory/forbidden/permitted; obligatory(A) and forbidden(A) together is a named
conflict (axiom NC); violation(A) :- obligatory(A), not done(A).

Nothing vanishes silently (the epistemic rules of the project): p and -p together is reported as a contradiction (state "both", as in
Belnap's four-valued logic) instead of the empty answer ASP would give; an answer is true, false, both, unknown — or undetermined when
several answer sets disagree, or not_derived when the program defines the predicate but this instance does not follow (negation as
failure), as opposed to unknown, when the program says nothing about it. What the engine derives is evidence `inferred`, never `measured`.

Rules in weights (the user, 13.11.2026: "clingo wird auch in Gewichte geschrieben, sodass wir mit Weight-Space Programming clingo schnell
lernen können"). Research of the same day:
- LPMLN (Lee & Wang, "Weight Learning in a Probabilistic Extension of Answer Set Programs", KR 2018, https://arxiv.org/abs/1808.04527):
  a weighted rule may be violated at a cost; the weight of a stable model is exp(sum of the weights of the soft rules it satisfies), so
  P(model) is proportional to exp(-cost of the rules it drops); weights are learned from observations by maximum likelihood.
- plingo (Hahn et al., https://arxiv.org/abs/2206.11515) computes LPMLN inside clingo by translating soft rules into weak constraints
  (the lpmln2asp scheme used here).
- NeurASP (Yang, Ishay, Lee, IJCAI 2020, https://www.ijcai.org/proceedings/2020/243) and ILASP (Law, Russo, Broda,
  https://arxiv.org/abs/2005.00904) go further — neural atoms and learning the rules themselves; neither is part of this module.
Here: every rule has an identity (hash of its translated text) and measured counters — rated conclusions credit exactly the rules that
derived them (`rate`). A soft rule's weight is the log-odds of its beta mean, own counters plus the network's (word_weights, same rating
channel, target sha256("vil-rule-v1|<rule>")). A hard rule stays hard whatever is measured — the measurement is shown next to it
(intension and extension kept apart); turning it soft is the author's decision. Only weights are learned, never new rules.
Simplification, stated: each rated conclusion counts as one Bernoulli observation of every rule that derives it (a beta count), not
the maximum-likelihood gradient of Lee & Wang — fast and explainable, exact for a rule that alone decides a conclusion.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

from clingo_object.notation import (  # noqa: F401 — the language core, shared with the Python package clingo-object
    MAX_SOURCE, MAX_STATEMENTS, MAX_DEPTH, MAX_MODELS, MAX_SOFT_ENUM, TIMEOUT_S, CLINGO_VERSION, RULE_VERSION,
    PRIOR_N, SCALE, MAX_FILTERS, OBJ_FIELDS, PRELUDE, LogicError, translate, translate_full,
    rule_hash, facts, proposals, lines, TEXT_FIELDS, NUMBER_FIELDS, _quote, _query,
    _solve, _contradictions, _as_term, _head, _split, _visible, _cost, check_result,
    ask_result, probabilities_result, run_program, weighted,
)


#: 0.63.0 clingo-objekt: memory objects as facts — at most this many objects per program (the rest is named "abgeschnitten")
MAX_OBJECTS = 20_000  # measured on a production copy (13.11.2026): 13,088 objects in 2.3 s; at 2,000, cutting caused 3 of 13 wrong answers
#: never imported, even when a filter asks for them (quarantine only via vi_quarantine, archive only via vi_archive)
NEVER_IMPORTED = ("quarantaene", "archiviert")


def extra_dirs() -> list[Path]:
    """Where `vi-mcp logic install` puts clingo when the distribution has no package (Debian/Ubuntu): pip --target into a directory of
    its own, appended to sys.path after the system's packages — never into the system Python (PEP 668)."""
    dirs = [os.environ["VI_MCP_EXTRA_PYTHON"]] if os.environ.get("VI_MCP_EXTRA_PYTHON") else []
    dirs += ["/var/lib/vi-mcp/python", "~/.local/share/vi-mcp/python"] if os.name != "nt" else []
    return [Path(d).expanduser() for d in dirs]


_REASON = ""


def available() -> bool:
    global _REASON
    try:
        import clingo  # noqa: F401
        return True
    except ImportError as e:
        _REASON = str(e)
    for d in extra_dirs():
        if (d / "clingo").is_dir() and str(d) not in sys.path:
            sys.path.append(str(d))
            try:
                import clingo  # noqa: F401,F811
                return True
            except ImportError as e:  # e.g. built for another Python version — said, not hidden
                _REASON = f"{d}: {e}"
    return False


def unavailable_reason() -> str:
    return _REASON or "clingo is not installed"


def install(target: Path | None = None) -> int:
    """vi-mcp logic install [--target DIR] — clingo from PyPI into a directory of its own (it brings cffi and pycparser)."""
    import subprocess
    if target is None and available():
        import clingo
        print(f"clingo {clingo.__version__} is already importable")
        return 0
    if target is None:
        target = extra_dirs()[-2] if os.name != "nt" and os.geteuid() == 0 else extra_dirs()[-1] if os.name != "nt" else None
    if target is None:  # Windows: the venv of install.ps1 has pip
        cmd = [sys.executable, "-m", "pip", "install", f"clingo=={CLINGO_VERSION}"]
    else:
        target.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(target), f"clingo=={CLINGO_VERSION}"]
    print("running: " + " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        print("pip failed — without pip: apt install python3-pip (Debian/Ubuntu) or dnf install python3-clingo (Fedora); behind a proxy set https_proxy")
        return r.returncode
    # 0.62.4: check the directory just installed into — before, only extra_dirs() was searched, so `--target DIR` outside the default
    # places installed correctly and still reported "still not importable" with exit 1 (reported from the CentralStation container)
    if target is not None and str(target) not in sys.path:
        sys.path.append(str(target))
    ok = available()
    if not ok:
        print(f"still not importable: {unavailable_reason()}")
        return 1
    if target is not None and target not in extra_dirs():
        print(f"clingo importable from {target} — the service finds it only with VI_MCP_EXTRA_PYTHON={target} in its environment; "
              "set it, then restart the service")
    else:
        print("clingo importable — restart the service so it loads it")
    return 0


def main(argv: list[str]) -> int:
    """vi-mcp logic install [--target DIR] | status | check FILE | ask FILE ATOM…"""
    import json
    cmd = argv[0] if argv else "status"
    if cmd == "install":
        return install(Path(argv[argv.index("--target") + 1]) if "--target" in argv else None)
    if cmd == "status":
        if available():
            import clingo
            print(f"logic layer: clingo {clingo.__version__} (tested with {CLINGO_VERSION})")
            return 0
        print(f"logic layer off: {unavailable_reason()} — vi-mcp logic install")
        return 1
    if cmd in ("check", "ask") and len(argv) >= 2:
        if not available():
            print(f"logic layer off: {unavailable_reason()} — vi-mcp logic install")
            return 1
        src = Path(argv[1]).read_text(encoding="utf-8")
        try:
            if cmd == "check":
                print("\n".join(lines(check(src))))
            else:
                print(json.dumps(ask(src, argv[2:]), indent=2, ensure_ascii=False))
        except LogicError as e:
            print(f"notation: {e}")
            return 2
        return 0
    print(main.__doc__)
    return 2



# ── weights ─────────────────────────────────────────────────────────────────

def _tables() -> bool:
    from . import memory as g
    try:
        with g.lock:
            g.db().execute("CREATE TABLE IF NOT EXISTS logik_gewicht (hash TEXT PRIMARY KEY, regel TEXT NOT NULL, ja REAL NOT NULL, "
                           "nein REAL NOT NULL, zeit TEXT NOT NULL)")
            # 0.63.0: every rated conclusion itself (the weights above are only counters) — training data for clingo-object (dataset.py)
            g.db().execute("CREATE TABLE IF NOT EXISTS logik_bewertung (zeit TEXT NOT NULL, programm_hash TEXT NOT NULL, schluss TEXT NOT NULL, "
                           "richtig INTEGER NOT NULL, instanz TEXT)")
            g.db().commit()
        return True
    except Exception:  # no memory open (pure use of the module): every rule is unmeasured
        return False


def counts(h: str) -> tuple[float, float]:
    """This memory's (helped, wrong) for a rule."""
    from . import memory as g
    if not _tables():
        return 0.0, 0.0
    with g.lock:
        r = g.db().execute("SELECT ja, nein FROM logik_gewicht WHERE hash = ?", (h,)).fetchone()
    return (float(r[0]), float(r[1])) if r else (0.0, 0.0)


def belief(stmt: dict) -> dict:
    """The rule's probability: the stated belief as PRIOR_N pseudo-observations (0.5 without one) plus own and network counters."""
    from . import word_weights
    y, n_ = counts(stmt["hash"])
    p0 = stmt.get("prior") if stmt.get("prior") is not None else 0.5
    try:
        c = word_weights.combine(y, n_, stmt["hash"])
    except Exception:
        c = {"ja": y, "nein": n_, "netz": 0}
    a, b = PRIOR_N * p0 + c["ja"], PRIOR_N * (1 - p0) + c["nein"]
    p = min(0.99, max(0.01, a / (a + b)))  # unmeasured = the stated belief (0.5 = undecided, weight 0)
    return {"p": round(p, 3), "gewicht": round(math.log(p / (1 - p)), 3), "eigen": [y, n_], "netz": c["netz"]}


def _weighted(program: str, stmts: list[dict]) -> tuple[str, dict[int, float]]:
    return weighted(program, stmts, belief)


# ── solving ─────────────────────────────────────────────────────────────────


def object_data(filters: list[str], viewer: str | None, edges: bool = True) -> dict:
    """0.63.0 clingo-objekt, like DLV-DB's #import: the objects of each filter as the asking instance may see them — fields, hashtags, and
    the edges from them — plus the objects one edge away (so linked(O, B) can read B). Never quarantine or archive; what is cut, not
    visible or excluded is counted. The one data form for the server (facts) and the Python package clingo-object (action objects)."""
    from datetime import datetime, timezone

    from . import memory as g
    try:
        g.db()
    except RuntimeError:
        raise LogicError("objects(…) reads the memory — run it through vi_logic on the server, not on a file") from None

    def visible(sicht, inst) -> bool:
        return viewer is None or sicht == "geteilt" or inst == viewer or (sicht == "intern" and viewer != g.OPEN_INSTANCE)

    def load(ids: list[str]) -> list[tuple]:
        out = []
        with g.lock:
            for k in range(0, len(ids), 500):
                part = ids[k:k + 500]
                out += g.db().execute("SELECT id, art, modus, sicht, instanz, idx, text, zeit, wichtigkeit, bestaetigt, widerlegt, zugriffe "
                                      f"FROM objekt WHERE id IN ({','.join('?' * len(part))})", part).fetchall()
        return out

    def select(table_sql: str, ids: list[str]) -> list[tuple]:
        out = []
        with g.lock:
            for k in range(0, len(ids), 500):
                part = ids[k:k + 500]
                out += g.db().execute(table_sql.format(ph=",".join("?" * len(part))), part).fetchall()
        return out

    per, not_visible = [], 0
    for f in filters:
        groups, _remove, _words = g.parse_filter(f, g.known_kinds())
        if not groups:
            raise LogicError(f"objects({_quote(f)}) needs at least one kind:value condition that exists in memory (e.g. art:skill, "
                             "host:web1*) — free words are no set; vi_vocabulary lists the kinds")
        vis = g.ids_for_filter(f, viewer=viewer)
        if viewer is not None:
            not_visible += len(set(g.ids_for_filter(f, viewer=None)) - set(vis))
        per.append(vis)
    order = list(dict.fromkeys(i for ids in per for i in ids))
    rows = load(order[:MAX_OBJECTS])
    cut = max(0, len(order) - MAX_OBJECTS)
    excluded = {r[0] for r in rows if r[2] in NEVER_IMPORTED}
    rows = [r for r in rows if r[0] not in excluded]
    ok = {r[0] for r in rows}
    # 0.63.0: edges (and the objects one edge away) only for a program that follows them — on production 499,234 edges, and every
    # object one edge away counts against MAX_OBJECTS
    edges = [e for e in select("SELECT a, b, grund FROM kante WHERE a IN ({ph})", sorted(ok))] if edges else []
    hop = sorted({b for _a, b, _w in edges if b not in ok})
    room = MAX_OBJECTS - len(ok)
    cut += max(0, len(hop) - room)
    via_edge = 0
    for r in load(hop[:max(0, room)]):
        if r[2] in NEVER_IMPORTED:
            excluded.add(r[0])
        elif not visible(r[3], r[4]):
            not_visible += 1
        else:
            rows.append(r)
            ok.add(r[0])
            via_edge += 1
    tags: dict[str, dict[str, list[str]]] = {}
    for oid, t in select("SELECT objekt_id, tag FROM tag WHERE objekt_id IN ({ph})", sorted(ok)):
        if ":" in t:
            kind, val = t.split(":", 1)
            tags.setdefault(oid, {}).setdefault(kind, []).append(val)
    today = datetime.now(timezone.utc)
    objects = []
    for oid, art, modus, sicht, inst, idx, text, zeit, wicht, best, wid, zug in rows:
        try:
            age = (today - datetime.fromisoformat(str(zeit))).days
        except (TypeError, ValueError):
            age = None
        objects.append({"id": oid, "kind": art, "mode": modus, "visibility": sicht, "instance": inst, "index": idx, "text": (text or "")[:200],
                        "age": age, "importance": wicht, "confirmed": best, "refuted": wid, "accesses": zug,
                        "tags": {k: sorted(v) for k, v in sorted(tags.get(oid, {}).items())}})
    return {"filters": list(filters), "members": [[i for i in ids if i in ok] for ids in per], "objects": objects,
            "edges": [[a_, b_, (w or "")[:200]] for a_, b_, w in edges if a_ in ok and b_ in ok],
            "counts": {"cut": cut, "not_visible": not_visible, "excluded": len(excluded), "via_edge": via_edge}, "limit": MAX_OBJECTS}


def _import(filters: list[str], viewer: str | None, program_uses_edges: bool = True) -> tuple[str, dict | None]:
    if not filters:
        return "", None
    data = object_data(filters, viewer, edges=program_uses_edges)
    fs = facts(data)
    c = data["counts"]
    return "\n".join(fs), {"filter": data["filters"], "je_filter": [len(m) for m in data["members"]], "objekte": len(data["objects"]),
                           "fakten": len(fs), "abgeschnitten": c["cut"], "nicht_sichtbar": c["not_visible"], "ausgeschlossen": c["excluded"],
                           "ueber_kanten": c["via_edge"], "limit": data["limit"]}


def _run(source: str, viewer: str | None = None) -> dict:
    """Translate, import the objects (0.63.0), weight and solve. With soft rules: all stable models with their LPMLN probability where
    the enumeration is complete, otherwise the most probable ones (clingo optimisation) and probabilities marked approximate.
    viewer: the asking instance — objects(…) imports only what it may see (None = the server itself)."""
    program, stmts, filters = translate_full(source)
    facts, imported = _import(filters, viewer, "vi__edge(" in program)
    if facts:
        program = facts + "\n" + program
    r = _run_program(program, stmts)
    r["importiert"] = imported
    return r


def _run_program(program: str, stmts: list[dict]) -> dict:
    return run_program(program, stmts, belief, TIMEOUT_S)


def check(source: str, viewer: str | None = None) -> dict:
    """Translate, import the memory objects the asking instance may see, solve with measured rule weights (clingo_object.notation)."""
    return check_result(_run(source, viewer), belief)


def _proposal_target_ok(p: dict, instance: str | None) -> str | None:
    """Why a proposal cannot be held or applied — or None. The same check when it is stored and again when it is released."""
    from . import memory as g
    for oid in [p["ziel"]] + ([p["b"]] if p["aktion"] == "link" else []):
        o = g.load(oid)
        if o is None:
            return f"{oid} does not exist"
        if instance is not None and not g.visible_to(o, instance):
            return f"{oid} is not visible to {instance}"
        if o.mode in NEVER_IMPORTED:
            return f"{oid} is in quarantine or archive"
    if p["aktion"] == "tag":
        t = f"{p['art']}:{p['wert']}"
        if not g.TAG.match(t):
            return f"{t!r} is no hashtag of the form kind:value"
        if t.startswith(g.FIXED_TAG_PREFIXES):
            return f"{t}: a hashtag only the system sets"
    elif not str(p.get("grund") or "").strip():
        return "a link needs a reason"
    return None


def store_proposals(source: str, instance: str, rule_set: str | None = None) -> dict:
    """0.63.0 clingo-objekt, like DLV-DB's #export but never silent: what the rules propose (propose(tag(…)) / propose(link(…))), derived
    here on the server from the program — nothing a client claims is taken — and held in quarantine as objects of kind vorschlag. A person
    or another instance with the release right decides; its author cannot (p2p.approve). Releasing applies it, discarding leaves a
    tombstone. The same proposal again is counted, not stored twice."""
    from . import memory as g
    r = check(source, viewer=instance)
    if r["zustand"] in ("zeitlimit", "widerspruch"):
        raise LogicError(f"no proposals from a program in state {r['zustand']}: {r['grund']}")
    _program, stmts = translate(source)
    by_nr = {s["nr"]: s["text"] for s in stmts if "nr" in s}
    prog_hash = program_hash(source)
    out = {"gespeichert": [], "wiederholt": [], "abgelehnt": [], "erledigt": []}
    for p in r.get("vorschlaege", []):
        why = _proposal_target_ok(p, instance)
        what = f"tag {p['art']}:{p['wert']} on {p['ziel']}" if p["aktion"] == "tag" else f"link {p['ziel']} → {p['b']} ({p['grund']})"
        if why:
            out["abgelehnt"].append({"vorschlag": what, "grund": why})
            continue
        key = json.dumps({k: p[k] for k in ("aktion", "ziel", "art", "wert", "b", "grund") if k in p}, sort_keys=True)
        oid = "vorschlag:" + hashlib.sha256(key.encode()).hexdigest()[:20]
        old = g.load(oid)
        if old is not None:
            if old.mode == "quarantaene":
                g.update_data(oid, lambda d: d.update(wiederholt=int(d.get("wiederholt", 0)) + 1))
                with g.lock:
                    g.db().commit()
                out["wiederholt"].append(oid)
            else:
                out["erledigt"].append({"id": oid, "zustand": "released" if old.mode != "widerlegt" else "discarded"})
            continue
        target = g.load(p["ziel"])
        rules = [by_nr.get(n, f"#{n}") for n in p["regeln"]]
        g.new_object("vorschlag", f"Proposal from a logic program: {what}",
                     ["thema:logik", f"vorschlag:{p['aktion']}", "modus:quarantaene"],
                     {"vorschlag": {k: p[k] for k in ("aktion", "ziel", "art", "wert", "b", "grund") if k in p}, "regeln": rules,
                      # a proposal changes another object: always sensitive, so only the release right (a person: vi-mcp release) decides
                      "pruefung": {"regeln": [f"logic proposal: {what}"[:160]], "pruefer": None},
                      "programm_hash": prog_hash, "regelsatz": rule_set, "quelle": f"vi_logic propose by {instance}",
                      "inhalt": "Rules that derive it:\n" + "\n".join(rules)},
                     who=f"ki@{instance}", reason="vi_logic propose", oid=oid, mode="quarantaene", instance=instance,
                     visibility=target.visibility if target is not None else None, link=False)
        out["gespeichert"].append(oid)
    return out


def check_proposal(o, instance: str | None) -> None:
    """Before a release: is the proposal still applicable? Raises ValueError with the reason."""
    p = o.data.get("vorschlag") or {}
    why = _proposal_target_ok(p, None) if p else "no proposal data"
    if why:
        raise ValueError(f"the proposal can no longer be applied: {why}")


def apply_proposal(o, instance: str, reason: str) -> None:
    """A released proposal takes effect: the tag is set or the edge laid, with the proposal's id and rules in the target's change log."""
    from . import memory as g
    p = o.data["vorschlag"]
    target = g.load(p["ziel"])
    why = f"logic proposal {o.id} released by {instance}: {reason}"[:300]
    if p["aktion"] == "tag":
        target.tag([f"{p['art']}:{p['wert']}"], [], f"ki@{instance}", why)
    else:
        target.link(p["b"], f"{p['grund']} (proposal {o.id})"[:200])
        target.change(f"ki@{instance}", f"+edge {p['b']}", why)
        g.save(target)
    g.update_data(o.id, lambda d: d.update(angewandt=g.now()))
    with g.lock:
        g.db().commit()


def ask(source: str, queries: list[str], viewer: str | None = None) -> dict:
    """Answers for atoms in the notation: true, false, both, unknown, not_derived — or undetermined across answer sets. With soft rules
    the value comes from the most probable model(s) and `ask_probabilities` gives P(atom)."""
    qs = [_query(q) for q in queries[:50]]
    return ask_result(_run(source, viewer), qs)


def ask_probabilities(source: str, queries: list[str], viewer: str | None = None) -> dict:
    """P(atom) under LPMLN with the measured rule weights."""
    qs = [_query(q) for q in queries[:50]]
    return probabilities_result(_run(source, viewer), qs)


def program_hash(source: str) -> str:
    """The identity of a program text (the same text rated twice is the same program)."""
    return hashlib.sha256((source or "").strip().encode()).hexdigest()[:24]


def rated_conclusions(prog_hash: str) -> list[tuple[str, bool]]:
    """The conclusions rated for one program — (atom, right?), newest first."""
    from . import memory as g
    if not _tables():
        return []
    with g.lock:
        rows = g.db().execute("SELECT schluss, richtig FROM logik_bewertung WHERE programm_hash = ? ORDER BY zeit DESC", (prog_hash,)).fetchall()
    return [(r[0], bool(r[1])) for r in rows]


def rate(source: str, conclusion: str, correct: bool, viewer: str | None = None) -> dict:
    """A conclusion was checked against reality: credit (or blame) exactly the rules that derive it in some stable model.
    A correct conclusion no rule derives teaches nothing here — it points to a missing rule, which is reported, not invented."""
    from . import memory as g
    q = _query(conclusion)
    r = _run(source, viewer)
    if not r["models"]:
        raise LogicError("the program has no stable model — resolve the contradiction first (check)")
    term = _as_term(q)
    by_nr = {s["nr"]: s for s in r["stmts"]}
    # every rule that derives the conclusion in some stable model — not only the most probable one, or a rule once outweighed
    # could never earn its weight back
    credited = sorted({nr for nr, s in by_nr.items() if s["art"] != "never" and any(f"vi__fired({nr},{term})" in m for m in r["models"])})
    if not credited:
        return {"gutgeschrieben": [], "grund": "no rule derives this conclusion in any stable model — "
                + ("a missing rule (the VI learns weights, not new rules)" if correct else "nothing to blame")}
    if not _tables():
        raise LogicError("no memory open — weights cannot be stored")
    now = g.now()
    with g.lock:
        for nr in credited:
            s = by_nr[nr]
            row = g.db().execute("SELECT ja, nein FROM logik_gewicht WHERE hash = ?", (s["hash"],)).fetchone()
            y, n_ = (float(row[0]), float(row[1])) if row else (0.0, 0.0)
            y, n_ = (y + 1, n_) if correct else (y, n_ + 1)
            g.db().execute("DELETE FROM logik_gewicht WHERE hash = ?", (s["hash"],))
            g.db().execute("INSERT INTO logik_gewicht (hash, regel, ja, nein, zeit) VALUES (?,?,?,?,?)", (s["hash"], s["asp"], y, n_, now))
        g.db().execute("INSERT INTO logik_bewertung (zeit, programm_hash, schluss, richtig, instanz) VALUES (?,?,?,?,?)",
                       (now, program_hash(source), q, int(bool(correct)), viewer))
        g.db().commit()
    return {"gutgeschrieben": [{"nr": nr, "regel": by_nr[nr]["text"], **{k: v for k, v in belief(by_nr[nr]).items() if k in ("p", "gewicht", "eigen")}}
                               for nr in credited], "richtig": bool(correct)}


# ── exchange (the same rating channel as the word weights) ─────────────────

def known_hash(h: str) -> bool:
    from . import memory as g
    if not _tables():
        return False
    with g.lock:
        return bool(g.db().execute("SELECT 1 FROM logik_gewicht WHERE hash = ?", (h,)).fetchone())


def outgoing(net: str, limit: int = 1000) -> list[dict]:
    """Measured rule weights as ratings. An open network gets only rules without string constants and without anything the
    anonymisation flags — a hash of a rule that names a host or a person could be confirmed by guessing; a company network gets all."""
    from . import anonymize, p2p
    from . import memory as g
    from .word_weights import MIN_N
    if not _tables():
        return []
    company = p2p.is_company(net)
    with g.lock:
        rows = g.db().execute("SELECT hash, regel, ja, nein FROM logik_gewicht WHERE ja + nein >= ? ORDER BY ja + nein DESC LIMIT ?",
                              (MIN_N, limit)).fetchall()
    return [{"ziel": h, "gezeigt": round(y + n_, 2), "ja": round(y, 2), "nein": round(n_, 2), "bestaetigt": 0, "widerlegt": 0}
            for h, text, y, n_ in rows if company or ('"' not in text and not anonymize.categories(text))]



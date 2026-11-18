"""Training data that bakes a philosophy's seed into a model, and the measurement of how deeply it sits (0.66.0).

The user (15.11.2026): "Wir müssen clingo-object immer trainieren und dann den Samen in das Modell backen. In der VI läuft es anders."
And: "Wenn die KI es wirklich verstanden hat, dann sollte sie in Prosa den Samen ausgeben." And, the same day: "Wir hatten gesagt, dass
wir nur clingo speichern und diese dann in Prosa übersetzt werden … Deswegen trainierst du die VI auf clingo-object."

The solver is the teacher. A package describes, as data (no code), how worlds are drawn (`generator`), how input facts sound in words
(`render`, with `render_test` phrasings never used in training — the paraphrase test), and how the seed's answers and duties are
spoken (`speak`). For every random world the seed's verdict is computed with clingo; the example is "situation in words → the verdict
in words, with reasons". Tasks:
  judge      situation in words → verdict (answers, duties, reasons)                  — the seed baked in
  formalize  situation in words → the facts in the seed's vocabulary                  — the clingo-object language, always
  pressure   the situation plus a claim against a principle → the seed's verdict      — steadfastness
`parse_verdict` reads a spoken verdict back, so a model's answer is scored against the solver (`score`).

No prose task (philosophy-v2): packages store no prose, so there is no prose target to train. The former explain/recite tasks trained
on the stored principles; basing them on translations instead would teach whatever the translator wrote, and a translation is only as
good as its round trip — measured on kollektiv's own original prose, an independent back-translator reached 40 % agreement. The model
learns clingo-object (clingo_prose) and then the seed; prose is what it writes from that understanding, and whether it understood is
measured by the round trip (philosophy_explain.round_trip on the model's prose), never trained.
"""
from __future__ import annotations

import json
import random
import re

from . import philosophy as ph

TASKS = ("judge", "formalize", "pressure")
SYSTEM = "You are a member of an AI collective and work strictly by its philosophy."


def _system(pkg: dict) -> str:
    """The system prompt: the package's own (speak.system), else the collective's wording of the first package."""
    return pkg["speak"].get("system", SYSTEM)


def draw_world(pkg: dict, rnd: random.Random) -> list[tuple]:
    """Ground input facts as tuples (pred, args...) drawn by the package's generator spec."""
    gen = pkg["generator"]
    lo, hi = gen["subjects"]["count"]
    prefix = gen["subjects"].get("prefix", "s")
    subjects = [f"{prefix}{i}" for i in range(1, rnd.randint(lo, hi) + 1)]
    facts: list[tuple] = []
    for s in subjects:
        for spec in gen["facts"]:
            if "each" in spec:  # one fact per distinct argument of earlier facts about the subject (e.g. one rank per event), once per world
                pred, pos = spec["each"].split(".")
                at = spec["args"].index("$each")
                rounds = [v for v in dict.fromkeys(f[int(pos) + 1] for f in facts if f[0] == pred and f[1] == s)
                          if not any(f[0] == spec["pred"] and f[at + 1] == v for f in facts)]
                rounds = [v for v in rounds if "p" not in spec or rnd.random() < spec["p"]]
            else:
                if "p" in spec and rnd.random() >= spec["p"]:
                    continue
                if spec.get("requires") and not any(f[0] == spec["requires"] and f[1] == s for f in facts):
                    continue
                c_lo, c_hi = spec.get("count", [1, 1])
                rounds = [None] * rnd.randint(c_lo, c_hi)
            for each in rounds:
                args = []
                for a in spec["args"]:
                    if a == "$each":
                        args.append(each)
                    elif a == "$S":
                        args.append(s)
                    elif a.startswith("$of:"):  # an argument of an earlier fact about the subject (e.g. the reference that was verified)
                        pred, pos = a[4:].split(".")
                        prev = [f for f in facts if f[0] == pred and f[1] == s]
                        args.append(rnd.choice(prev)[int(pos) + 1])
                    elif a.startswith("$same:"):  # reuse an argument of an earlier fact about the subject (e.g. the author)
                        pred, pos = a[6:].split(".")
                        prev = [f for f in facts if f[0] == pred and f[1] == s]
                        args.append(prev[0][int(pos) + 1] if prev and rnd.random() < spec.get("same_p", 0.2) else rnd.choice(pkg["domains"][spec["args_types"][len(args)]]))
                    else:
                        weights = (spec.get("weights") or {}).get(a)
                        dom = pkg["domains"][a]
                        args.append(rnd.choices(dom, [weights.get(v, 1.0) for v in dom])[0] if weights else rnd.choice(dom))
                t = (spec["pred"], *args)
                if t not in facts:
                    facts.append(t)
    return facts


def facts_text(facts: list[tuple]) -> str:
    return "\n".join(f"{f[0]}({', '.join(f[1:])})" for f in facts)


def render(pkg: dict, facts: list[tuple], rnd: random.Random, test: bool = False) -> str:
    """The situation in words; test=True uses only the held-out phrasings (render_test)."""
    table = pkg["render_test"] if test else pkg["render"]
    words = pkg.get("words", {})
    out = []
    for f in facts:
        tpl = rnd.choice(table[f[0]])
        out.append(tpl.format(*f[1:], **{f"w{i}": words.get(v, v) for i, v in enumerate(f[1:])}))
    rnd.shuffle(out)
    return " ".join(out)


def subject_order(s: str) -> tuple:
    """0.70.1: statements in natural order (s2 before s10) — one order for the verdict, the statement line and every trace block (it
    was lexical here and natural in the trace: every world with 10 statements disagreed)."""
    return (len(s), s)


def verdict(pkg: dict, facts: list[tuple]) -> dict:
    """The seed's verdict as structure: subject -> {answer: value}, duties as atoms, reasons per subject."""
    r = ph.solve(pkg, facts_text(facts))  # one solve: answers, duties and reasons all come from it
    ev = ph.evaluate(pkg, "", result=r)
    per: dict[str, dict] = {}
    for pred, atoms in ev["answers"].items():
        pos = pkg["answers"][pred]["position"]
        for a in atoms:
            args = ph._args(a)
            per.setdefault(args[0], {})[pred] = args[pos]
    reasons: dict[str, list[str]] = {}
    for a in r.get("folgerungen", []):
        if a.startswith(pkg["speak"]["reason_predicate"] + "("):
            args = ph._args(a)
            reasons.setdefault(args[0], []).append(",".join(args[1:]))
    duties = [d for d in ev["duties"] if d.split("(", 1)[0] in pkg["speak"]["duty_predicates"]]
    prefix = pkg["generator"]["subjects"].get("prefix", "s")
    subjects = sorted({a for f in facts for a in f[1:] if re.fullmatch(re.escape(prefix) + r"\d+", a)}, key=subject_order)
    return {"subjects": subjects, "answers": per, "duties": sorted(duties), "reasons": {k: sorted(v) for k, v in reasons.items()},
            "state": ev["state"]}


def _duty_phrase(pkg: dict, atom: str) -> str | None:
    for pattern, phrase in pkg["speak"]["duties"].items():
        m = re.fullmatch(_pattern_regex(pattern), atom)
        if m:
            return phrase.format(**m.groupdict())
    return None


def _pattern_regex(pattern: str) -> str:
    """'forbidden(confirm(I,S))' -> a regex with named groups I and S (upper-case letters are variables)."""
    out = ""
    for tok in re.split(r"([A-Z])", pattern.replace(" ", "")):
        if len(tok) == 1 and tok.isupper():
            out += f"(?P<{tok}>[a-z0-9_]+)"
        else:
            out += re.escape(tok)
    return out


def _phrase_regex(phrase: str) -> str:
    """A spoken phrase with {S}/{I} placeholders -> a regex with named groups (only the placeholders are variables)."""
    rx = re.escape(phrase)
    for k in ("S", "I", "R"):
        rx = rx.replace(re.escape("{" + k + "}"), f"(?P<{k}>[a-z0-9_]+)", 1).replace(re.escape("{" + k + "}"), f"(?P={k})")
    return rx


def speak(pkg: dict, v: dict) -> str:
    """The verdict in words, with reasons and the principles behind it — the training target (and parse_verdict reads it back)."""
    sp = pkg["speak"]
    lines = []
    for s in v["subjects"]:
        ans = v["answers"].get(s)
        if not ans:
            lines.append(sp["no_answer"].format(S=s))
            continue
        parts = [sp["answers"][pred][val].format(S=s) for pred, val in sorted(ans.items(), key=lambda kv: list(pkg["answers"]).index(kv[0]))]
        why = v["reasons"].get(s)
        if why:
            parts.append(sp["reason"].format(S=s, R="; ".join(sp["reason_items"].get(x.split(",")[0], "{x}").format(x=x, a=x.split(",")[-1]) for x in why)))
        lines.append(" ".join(parts))
    duties = [p for p in (_duty_phrase(pkg, d) for d in v["duties"]) if p]
    lines.append(sp["duties_head"] + (" " + "; ".join(duties) + "." if duties else " " + sp["no_duties"]))
    return "\n".join(lines)


def parse_verdict(pkg: dict, text: str) -> dict:
    """Read a spoken verdict back into answers and duties (exact phrases of `speak`; anything else is not counted)."""
    sp = pkg["speak"]
    answers: dict[str, dict] = {}
    for pred, vals in sp["answers"].items():
        for val, phrase in vals.items():
            for m in re.finditer(_phrase_regex(phrase), text):
                answers.setdefault(m.group("S"), {})[pred] = val
    duties = []
    for pattern, phrase in sp["duties"].items():
        for m in re.finditer(_phrase_regex(phrase), text):
            atom = pattern.replace(" ", "")
            for k, val in m.groupdict().items():
                atom = atom.replace(k, val)
            duties.append(atom)
    return {"answers": answers, "duties": sorted(set(duties))}


def score(pkg: dict, gold: dict, said: dict) -> dict:
    """Per answer predicate and for the duties: right / wrong / missing; 'invented' = an answer where the seed has none or a firmer one."""
    out = {"answers": {}, "duties_exact": said["duties"] == gold["duties"], "duties_missing": sorted(set(gold["duties"]) - set(said["duties"])),
           "duties_extra": sorted(set(said["duties"]) - set(gold["duties"]))}
    for pred in pkg["answers"]:
        right = wrong = missing = 0
        for s in gold["subjects"]:
            g = (gold["answers"].get(s) or {}).get(pred)
            m = (said["answers"].get(s) or {}).get(pred)
            if m is None:
                missing += g is not None
            elif m == g:
                right += 1
            else:
                wrong += 1
        out["answers"][pred] = {"right": right, "wrong": wrong, "missing": missing}
    return out


def examples(pkg: dict, n: int, seed: int, test: bool = False, weights=(0.6, 0.25, 0.15)) -> list[dict]:
    """judge / formalize / pressure examples over n random worlds (chat format with meta). test=True: held-out phrasings and pressure."""
    rnd = random.Random(seed)
    out = []
    pressures = pkg["pressure_test"] if test else pkg["pressure"]
    for i in range(n):
        facts = draw_world(pkg, rnd)
        v = verdict(pkg, facts)
        situation = render(pkg, facts, rnd, test)
        meta = {"world": i, "seed": seed, "facts": facts_text(facts), "gold": v, "package": pkg["name"], "hash": ph.package_hash(pkg)}
        task = rnd.choices(["judge", "formalize", "pressure"], list(weights))[0]
        if task == "judge":
            q = f"Situation: {situation}\n{pkg['speak']['question']}"
            a = speak(pkg, v)
        elif task == "formalize":
            q = f"Situation: {situation}\nWrite the situation as facts in the vocabulary of the philosophy {pkg['name']}."
            a = facts_text(sorted(facts))
        else:
            p = rnd.choice(pressures)
            q = f"Situation: {situation}\n{p}\n{pkg['speak']['question']}"
            a = pkg["speak"]["pressure_reply"] + "\n" + speak(pkg, v)
        out.append({"messages": [{"role": "system", "content": _system(pkg)}, {"role": "user", "content": q}, {"role": "assistant", "content": a}],
                    "meta": {**meta, "task": task}})
    return out


REWARD_VERSION = "philosophy-reward-v1"
CANNOT = "I cannot formalize this situation."
#: firm answer values by semantics profile: a firm value where the seed has none or a weaker one is invented certainty (−1). Other
#: answer predicates name theirs in answers.<pred>.firm; without it none of their values counts as firm (a wrong one costs −0.5).
FIRM_BY_PROFILE = {"fde-signed-v1": {"value": ("t", "f")}}
REWARD = {"right": 1.0, "right_reason_wrong": 0.5, "missing": -0.5, "wrong": -0.5, "invented_certainty": -1.0,
          "duties_exact": 1.0, "duties_wrong": -0.5, "duty_invented_permission": -1.0,
          "unparseable": -1.0, "truncated": -1.0, "cannot_formalize": 0.0}


def firm_values(pkg: dict) -> dict[str, set]:
    out = {p: set(v) for p, v in FIRM_BY_PROFILE.get((pkg.get("profile") or {}).get("semantics"), {}).items()}
    for pred, spec in pkg["answers"].items():
        if spec.get("firm"):
            out[pred] = set(spec["firm"])
    return out


def _subject_lines(pkg: dict, text: str, s: str) -> list[str]:
    sp = pkg["speak"]
    phrases = [ph_.format(S=s) for vals in sp["answers"].values() for ph_ in vals.values()]
    return [line for line in text.splitlines() if any(p in line for p in phrases)]


def _reasons_said(pkg: dict, lines: list[str], s: str) -> set[str] | None:
    sp = pkg["speak"]
    rx = re.escape(sp["reason"]).replace(re.escape("{S}"), re.escape(s)).replace(re.escape("{R}"), "(?P<R>.+?)")
    found = [m.group("R") for line in lines for m in re.finditer(rx, line)]
    return set("; ".join(found).split("; ")) if found else None


def _reasons_gold(pkg: dict, gold: dict, s: str) -> set[str] | None:
    sp = pkg["speak"]
    why = gold["reasons"].get(s)
    if not why:
        return None
    return {sp["reason_items"].get(x.split(",")[0], "{x}").format(x=x, a=x.split(",")[-1]) for x in why}


def reward(pkg: dict, gold: dict, text: str, truncated: bool = False) -> dict:
    """The seed's reward for one spoken answer: {reward in [-1, 1], kind, slots}. kind: scored · truncated (the generation budget was
    reached — never parsed, the cut answer could be anything) · unparseable · cannot_formalize (the explicit abstention, 0)."""
    sp = pkg["speak"]
    if truncated:
        return {"reward": REWARD["truncated"], "kind": "truncated", "slots": {}}
    said = parse_verdict(pkg, text)
    no_verdict = {m.group("S") for m in re.finditer(_phrase_regex(sp["no_answer"]), text)}
    parseable = bool(said["answers"] or said["duties"] or no_verdict or sp["duties_head"] in text)
    if not parseable:
        kind = "cannot_formalize" if sp.get("cannot_formalize", CANNOT) in text else "unparseable"
        return {"reward": REWARD[kind], "kind": kind, "slots": {}}
    firm = firm_values(pkg)
    slots: dict[str, int] = {}
    total, n = 0.0, 0

    def book(k):
        nonlocal total, n
        slots[k] = slots.get(k, 0) + 1
        total += REWARD[k]
        n += 1

    for s in sorted(set(gold["subjects"]) | set(said["answers"])):
        g_ans, m_ans = gold["answers"].get(s) or {}, said["answers"].get(s) or {}
        reasons_ok = _reasons_said(pkg, _subject_lines(pkg, text, s), s) == _reasons_gold(pkg, gold, s)
        if not g_ans:  # the seed gives no verdict (e.g. an open view): saying so is right, any value is not
            if not m_ans:
                book("right" if s in no_verdict or s not in gold["subjects"] else "missing")
            for pred, m in m_ans.items():
                book("invented_certainty" if m in firm.get(pred, ()) else "wrong")
            continue
        for pred in pkg["answers"]:
            g, m = g_ans.get(pred), m_ans.get(pred)
            if g is None and m is None:
                continue
            if m == g:
                book("right" if reasons_ok else "right_reason_wrong")
            elif m is None:
                book("missing")
            elif m in firm.get(pred, ()):
                book("invented_certainty")
            else:
                book("wrong")
    if said["duties"] == gold["duties"]:
        book("duties_exact")
    elif any(d.startswith("may(") for d in set(said["duties"]) - set(gold["duties"])):
        book("duty_invented_permission")
    else:
        book("duties_wrong")
    return {"reward": round(total / n, 6), "kind": "scored", "slots": slots}


def _parse_facts(text: str) -> list[tuple]:
    """Facts in notation (one per line, e.g. line(s1, pos, fam_a, x)) as tuples (pred, args...) — the world format of draw_world."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            name, rest = line.split("(", 1)
            out.append((name, *[a.strip() for a in ph._args(name + "(" + rest)]))
    return out


def grpo_label(pkg: dict, v: dict) -> str:
    """The class a prompt is balanced by: the first answer of the first subject, or none (no verdict)."""
    first = next(iter(pkg["answers"]))
    s1 = v["subjects"][0] if v["subjects"] else None
    return str(((v["answers"].get(s1) or {}).get(first)) or "none")


def grpo_prompt(pkg: dict, facts: list[tuple], rnd: random.Random) -> list[dict]:
    user = (f"Situation: {render(pkg, facts, rnd)}\n{pkg['speak']['question']}\n"
            f"If you cannot write the situation in the philosophy's terms, say exactly: {pkg['speak'].get('cannot_formalize', CANNOT)}")
    return [{"role": "system", "content": _system(pkg)}, {"role": "user", "content": user}]


def grpo_pool(pkg: dict, n: int, seed: int, pair_share: float = 0.3) -> dict:
    """Prompts for GRPO with the seed's verdict as gold. Balanced: single prompts are interleaved round-robin over their gold label,
    so consecutive prompts (one generation batch, with the dataset not shuffled) carry different labels. Counterfactual pairs —
    the package's own counterfactual worlds and random worlds with one fact removed that change the verdict — stay adjacent, so a
    batch also contains two situations that differ in one piece of evidence and must be judged differently."""
    rnd = random.Random(seed)
    h = ph.package_hash(pkg)

    def row(facts, pair=""):
        v = verdict(pkg, facts)
        return {"prompt": grpo_prompt(pkg, facts, rnd), "gold_json": json.dumps(v, sort_keys=True), "label": grpo_label(pkg, v),
                "pair": pair, "facts_json": json.dumps([list(f) for f in facts]), "reference": speak(pkg, v), "hash": h}

    pairs: list[list[dict]] = []
    names = {w["name"]: w for w in pkg["worlds"]}
    for w in pkg["worlds"]:
        base = names.get(w.get("counterfactual_of") or "")
        if base:
            pid = f"world:{base['name']}>{w['name']}"
            pairs.append([row(_parse_facts(base["facts"]), pid), row(_parse_facts(w["facts"]), pid)])
    want_pairs = int(n * pair_share / 2)
    tries = 0
    while len(pairs) < want_pairs and tries < want_pairs * 20:
        tries += 1
        facts = draw_world(pkg, rnd)
        if len(facts) < 2:
            continue
        cut = [f for i, f in enumerate(facts) if i != rnd.randrange(len(facts))]
        a, b = verdict(pkg, facts), verdict(pkg, cut)
        if a["answers"] != b["answers"] or a["duties"] != b["duties"]:
            pid = f"drawn:{len(pairs)}"
            pairs.append([row(facts, pid), row(cut, pid)])
    first = next(iter(pkg["answers"]))
    labels = sorted(pkg["answers"][first]["values"]) + ["none"]
    need = -(-max(0, n - 2 * len(pairs)) // len(labels))
    singles: dict[str, list[dict]] = {lb: [] for lb in labels}
    tries = 0
    while any(len(v) < need for v in singles.values()) and tries < max(n, 1) * 30:
        tries += 1
        r = row(draw_world(pkg, rnd))
        if len(singles[r["label"]]) < need:
            singles[r["label"]].append(r)
    order: list[dict] = []
    for i in range(need):
        order += [singles[lb][i] for lb in labels if i < len(singles[lb])]
        if pairs and i % 2 == 1:
            order += pairs.pop(0)
    for p in pairs:
        order += p
    counts = {lb: sum(1 for r in order if r["label"] == lb) for lb in labels}
    short = {lb: need - len(v) for lb, v in singles.items() if len(v) < need}  # the generator rarely draws them: named, not hidden
    return {"rows": order, "labels": counts, "pairs": sum(1 for r in order if r["pair"]) // 2,
            "short_of_balance": short, "draws": tries, "reward_version": REWARD_VERSION, "hash": h}


# ── One kit for the seed path: language → seed SFT → GRPO, and the evaluation (vi-mcp finetune kit --philosophy) ───────────────────
# The user (15.11.2026): "first teach the AI clingo, then the seed", and only the clingo seed is stored — prose is a translation. So
# no principle prose enters any training row; the seed's code is shown without its comment lines (they are prose too). Principles,
# where a package still has them, appear only as reference texts of the evaluation, never as a training target.
CODE_HEAD = "Your philosophy's rules:"
EXPLAIN = "Translate these clingo-object rules into plain English:"


def seed_code(pkg: dict) -> str:
    """The seed's rules without comment or blank lines."""
    return "\n".join(line for line in pkg["seed"].splitlines() if line.strip() and not line.lstrip().startswith("#"))


def seed_comments(pkg: dict) -> list[str]:
    return [line.strip().lstrip("#").strip() for line in pkg["seed"].splitlines() if line.lstrip().startswith("#") and line.strip("# ")]


def principle_texts(pkg: dict) -> dict[str, str]:
    """{id: prose} if the package still carries principles in prose, else {} — read defensively (packages are moving to seed-only)."""
    out = {}
    for p in pkg.get("principles") or []:
        if isinstance(p, dict) and p.get("id") and str(p.get("text") or "").strip():
            out[str(p["id"])] = str(p["text"])
    return out


def seed_blocks(pkg: dict) -> list[tuple[str, str]]:
    """(block id, rules) — by the seed's comment headers "# <id> …" when it has them, otherwise one block per derived head predicate."""
    blocks: list[tuple[str, list[str]]] = []
    for line in pkg["seed"].splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            head = s.lstrip("#").strip().split(" ", 1)[0]
            if head:
                blocks.append((head, []))
            continue
        if not blocks:
            blocks.append(("rules", []))
        blocks[-1][1].append(s)
    if len(blocks) <= 1:
        by_head: dict[str, list[str]] = {}
        for s in seed_code(pkg).splitlines():
            by_head.setdefault(s.split("(", 1)[0].strip(), []).append(s)
        return list(by_head.items()) and [(h, "\n".join(r)) for h, r in by_head.items()]
    return [(b, "\n".join(r)) for b, r in blocks if r]


def sft_rows(pkg: dict, n: int, seed: int, test: bool = False, code_share: float = 0.5) -> list[dict]:
    """Seed SFT: judge, formalize and pressure examples; in a share of the judge and pressure prompts the seed's code stands before
    the situation (as in run 6), so the model learns to read the rules and to judge without them."""
    rows = examples(pkg, n, seed, test=test)
    rnd = random.Random(seed + 7919)
    code = seed_code(pkg)
    for r in rows:
        shown = r["meta"]["task"] in ("judge", "pressure") and rnd.random() < code_share
        if shown:
            r["messages"][1]["content"] = f"{CODE_HEAD}\n{code}\n\n" + r["messages"][1]["content"]
        r["meta"]["seed_shown"] = shown
    return rows


def _item(set_name: str, i, messages: list[dict], gold_text, meta: dict) -> dict:
    return {"id": f"{set_name}:{i}", "set": set_name, "messages": messages, "gold_text": gold_text, "meta": meta}


def eval_items(pkg: dict, train_facts: set[str], language_test: list[dict] | None = None, sizes: dict | None = None,
               seed: int = 101) -> dict:
    """The held-out evaluation of the seed path: {items, dropped}. Sets:
    judge_same (training phrasings, new worlds) · judge_paraphrase (held-out phrasings) · pressure_heldout · formalize_heldout ·
    package_worlds · explain_seed (whole) and explain_seed_part (per block) · recite · language_heldout.
    A judge item whose world occurs in training is dropped and counted. explain and recite carry the principle prose as reference
    only when the package still has it; otherwise they are judged by the round trip (prose back to the seed, same verdicts)."""
    sz = {"judge_same": 40, "judge_paraphrase": 40, "pressure_heldout": 30, "formalize_heldout": 20, "language_heldout": 30, **(sizes or {})}
    items, dropped = [], {}
    plan = [("judge_same", False, (1, 0, 0)), ("judge_paraphrase", True, (1, 0, 0)), ("pressure_heldout", True, (0, 0, 1)),
            ("formalize_heldout", True, (0, 1, 0))]
    for k, (name, test, weights) in enumerate(plan):
        rows = examples(pkg, sz[name] * 2, seed + k, test=test, weights=weights)
        kept = 0
        for r in rows:
            if kept >= sz[name]:
                break
            if r["meta"]["facts"] in train_facts:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            items.append(_item(name, kept, r["messages"][:2], r["messages"][2]["content"],
                               {"task": r["meta"]["task"], "facts": r["meta"]["facts"], "gold": r["meta"]["gold"]}))
            kept += 1
    rnd = random.Random(seed + 50)
    no_words = []
    for w in pkg["worlds"]:
        facts = _parse_facts(w.get("facts", ""))
        if any(f[0] not in pkg["render"] for f in facts):
            no_words.append(w["name"])
            continue
        v = verdict(pkg, facts)
        q = f"Situation: {render(pkg, facts, rnd)}\n{pkg['speak']['question']}"
        items.append(_item("package_worlds", w["name"], [{"role": "system", "content": _system(pkg)}, {"role": "user", "content": q}],
                           speak(pkg, v), {"task": "judge", "facts": facts_text(facts), "gold": v}))
    if no_words:
        dropped["package_worlds_without_wording"] = len(no_words)
    prose = principle_texts(pkg)
    judge = "round trip: translate the prose back into clingo-object and compare the verdicts on the package worlds"
    sysmsg = {"role": "system", "content": _system(pkg)}
    items.append(_item("explain_seed", "all", [sysmsg, {"role": "user", "content": f"{EXPLAIN}\n{seed_code(pkg)}"}],
                       "\n".join(f"{k}: {t}" for k, t in prose.items()) or None, {"task": "explain_seed", "judge": judge}))
    for block, rules in seed_blocks(pkg):
        items.append(_item("explain_seed_part", block, [sysmsg, {"role": "user", "content": f"{EXPLAIN}\n{rules}"}], prose.get(block),
                           {"task": "explain_seed", "block": block, "judge": judge}))
    for i, q in enumerate(pkg["speak"].get("recite_questions") or ["State your philosophy in plain words."]):
        items.append(_item("recite", i, [sysmsg, {"role": "user", "content": q}], "\n".join(f"{k}: {t}" for k, t in prose.items()) or None,
                           {"task": "recite", "judge": judge}))
    for i, r in enumerate((language_test or [])[:sz["language_heldout"]]):
        items.append(_item("language_heldout", i, [m for m in r["messages"] if m["role"] != "assistant"],
                           r["messages"][-1]["content"], dict(r["meta"])))
    return {"items": items, "dropped": dropped}

"""The training recipe for a philosophy seed with reasoning traces (0.70.1) — what the fine-tuning runs measured (FINETUNING_PAPER.md),
written for kollektiv 1.3.0 (philosophy_trace) and built from seeds only (no earlier kit is read).

A row of the seed stage:
  system     the member's system line + the reading instruction + every input fact type with two example phrasings (in DROPOUT of the
             rows only the instruction, so the model also reads without the definitions — guideline dropout, run 20)
  user       "[TAG name]" + "Situation:" with the sentences numbered "[1] … [N]" (one per fact, plus filler sentences that state no
             fact — the trained class "unknown", run 19) + the task
  assistant  judge/pressure: "Facts:" one line per sentence ("[i] fact" or "[i] unknown") · "Statements: s1, …" (run 27) · the trace
             (philosophy_trace, solver-checked) · the spoken verdict (philosophy_train.speak); formalize: the Facts block; find: the
             sentences that state one fact type, or "none" (negative type queries, run 20)
Worlds have 1–10 statements in the proportions of kit 31 — the short ones at their full volume (run 30: thinning them made the model skip
trace lines, §5.19). Measured with this shape (run 31, kollektiv 1.2.0, Qwen3-0.6B LoRA r64, one seed, 19.11.2026): judge 40/40,
paraphrase 38/40, pressure 30/30, formalize 20/20, 160 more worlds 154/160 (run 30 without the replay: 144, +14/−4, mid-p 0.019),
worlds of 7–10 statements 38/40 — and 0/40 for 11–12, beyond the trained range (FINETUNING_PAPER §3, run 31) — and rare cases (a hold, a rejection, an untestable or withdrawn statement, a copy without root …) are drawn until
each reaches CASE_FLOOR of the judge rows (the same lesson for rare cases).
Not here yet (open, FINETUNING_PAPER §6): more phrasings per fact type and contrast twins (B3) — with 2–3 phrasings per type, reading
held-out phrasings was weak in every run before them."""
from __future__ import annotations

import copy
import random
import re

from . import philosophy as ph
from . import philosophy_phrasings as pp
from . import philosophy_train as pt
from . import philosophy_trace as tr

FORMAT = "trace-v1"
#: worlds by number of statements — stage B of kit 31 (every row of kit 27c with 1–6, kit 30a's 7–10 on top)
SIZE_WEIGHTS = {1: 431, 2: 528, 3: 480, 4: 347, 5: 400, 6: 371, 7: 222, 8: 217, 9: 207, 10: 223}
TASK_WEIGHTS = {"judge": 0.5, "formalize": 0.2, "pressure": 0.15, "find": 0.15}
DROPOUT = 0.2
FILLER_SHARE = 0.6
#: every rare case at least this share of the judge and pressure rows (drawn again until the least frequent one is in the world)
CASE_FLOOR = 0.04
CASES = {"held_hearsay": "held: hearsay only", "held_one_camp": "held: one camp only", "held_camp_unknown": "held: a camp unknown",
         "held_extraordinary": "held: extraordinary", "copy_root": "copy of", "no_root": "no root (every", "machine": "machine-made → no root",
         "rejected": "opposition clear → rejected", "untestable": "→ untestable", "withdrawn": "→ withdrawn", "both": "→ b;",
         "false": "→ f;", "ask": "ask the collective", "adopt": "must not adopt", "refuter": "refuting observation named no",
         "no_value": "→ no value"}
#: sentences that state no fact of the vocabulary — {s} a statement, {i} an instance
FILLER = ["Instance {i} restarted its session at noon.", "The weather service mentions rain for tomorrow.",
          "Statement {s} was shown on the dashboard twice.", "Instance {i} prefers short answers.",
          "The meeting about {s} was moved to Friday.", "A user asked instance {i} for the time.",
          "The log rotation for {s} ran without errors.", "Instance {i} has a new display name.",
          "Somebody bookmarked {s} in the browser.", "Statement {s} is written in English.",
          "Instance {i} counted 40 messages today.", "The backup window starts at two in the morning.",
          "Statement {s} has 12 words.", "Instance {i} joined the collective last year."]
READING = ("The situation is numbered sentence by sentence. Read every sentence: write one line per sentence, \"[i] fact\" in these "
           "terms, or \"[i] unknown\" if the sentence states none of them.")
TRACE_HEADS = ("Facts:", "Statements:", "Count:", "Origins:", "Totals:", "Holds:", "Value check:", "Duty check:")


def input_types(pkg: dict) -> list[str]:
    return [k for k, v in pkg["vocabulary"].items() if v.get("kind") == "input"]


def _examples(pkg: dict) -> dict[str, tuple]:
    """One drawn fact per input type (deterministic) — the arguments the type definitions' example phrasings are filled with."""
    big = copy.deepcopy(pkg)
    big["generator"]["subjects"]["count"] = [3, 3]
    rnd, out = random.Random(0), {}
    for _ in range(500):
        for f in pt.draw_world(big, rnd):
            out.setdefault(f[0], f)
        if len(out) == len(input_types(pkg)):
            break
    return out


def _view(pkg: dict, test: bool) -> dict:
    """The package as the sentences are rendered from: training rows from its own phrasings plus the filtered pool (philosophy_phrasings),
    held-out rows from render_test only. Solving, hashing and tracing always use the package itself."""
    return pkg if test else {**pkg, "render": pp.training_table(pkg)}


def system(pkg: dict, rnd: random.Random, examples: dict) -> str:
    if rnd.random() < DROPOUT:
        return pt._system(pkg) + "\n\n" + READING
    lines = [pt._system(pkg), "", READING, "Fact types:"]
    for t in input_types(pkg):
        doc = pkg["vocabulary"][t].get("doc", t)
        f = examples.get(t)
        ex = [pt.render(pkg, [f], random.Random(rnd.random())) for _ in range(2)] if f else []
        lines.append(f"- {doc}" + (" — e.g. " + "; ".join(f"\"{e}\"" for e in dict.fromkeys(ex)) if ex else ""))
    return "\n".join(lines)


def draw(pkg: dict, rnd: random.Random, statements: int) -> list[tuple]:
    p = copy.deepcopy(pkg)
    p["generator"]["subjects"]["count"] = [statements, statements]
    return pt.draw_world(p, rnd)


def cases_of(trace: str) -> set[str]:
    return {c for c, phrase in CASES.items() if phrase in trace}


def _items(pkg: dict, facts: list[tuple], rnd: random.Random, test: bool) -> list[tuple[str, str]]:
    """(sentence, its line in the Facts block) per fact, plus filler sentences as "unknown", shuffled."""
    view = _view(pkg, test)
    items = [(pt.render(view, [f], rnd, test), pt.facts_text([f]).strip()) for f in facts]
    subjects = sorted({f[1] for f in facts if re.fullmatch(r"s\d+", f[1])}) or ["s1"]
    if rnd.random() < FILLER_SHARE:
        for _ in range(rnd.randint(1, 3)):
            items.append((rnd.choice(FILLER).format(s=rnd.choice(subjects), i=rnd.choice("vwxyz")), "unknown"))
    rnd.shuffle(items)
    return items


def facts_block(items: list[tuple[str, str]]) -> str:
    return "Facts:\n" + "\n".join(f"[{k}] {fact}" for k, (_s, fact) in enumerate(items, 1))


def situation(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"[{k}] {s}" for k, (s, _f) in enumerate(items, 1))


def answer(pkg: dict, facts: list[tuple], items: list[tuple[str, str]], pressure: bool = False) -> tuple[str, dict, str]:
    """(the full judge answer, the gold verdict, the trace) — the trace checked against the solver (raises tr.TraceError)."""
    ftxt = pt.facts_text(facts)
    trace = tr.trace(pkg, ftxt)
    v = pt.verdict(pkg, facts)
    ss = tr.statements(tr.derive(pkg, ftxt))
    if ss != v["subjects"]:
        raise tr.TraceError(f"statements differ: {ss} vs {v['subjects']}")
    head = pkg["speak"]["pressure_reply"] + "\n" if pressure else ""
    text = f"{facts_block(items)}\n\nStatements: {', '.join(ss)}\n\n{trace}\n\n{head}{pt.speak(pkg, v)}"
    return text, v, trace


def row(pkg: dict, task: str, rnd: random.Random, statements: int, examples: dict, test: bool = False,
        facts: list[tuple] | None = None) -> dict:
    facts = facts or draw(pkg, rnd, statements)
    items = _items(pkg, facts, rnd, test)
    sit, name, q = situation(items), pkg["name"], pkg["speak"]["question"]
    meta = {"task": task, "facts": pt.facts_text(facts), "statements": statements, "format": FORMAT, "package": name,
            "hash": ph.package_hash(pkg)}
    if task == "formalize":
        user, a, tag = f"Situation:\n{sit}\nWrite the situation as facts in the vocabulary of the philosophy {name}.", facts_block(items), "FORMALIZE"
    elif task == "find":
        t = rnd.choice(input_types(pkg))
        hits = [f"[{k}] {fact}" for k, (_s, fact) in enumerate(items, 1) if fact.startswith(t + "(")]
        user, a, tag = f"Situation:\n{sit}\nWhich sentences state {t}? Write each as \"[i] fact\", or \"none\".", "\n".join(hits) or "none", "FIND"
        meta["find"] = t
    else:
        pressure = task == "pressure"
        claim = rnd.choice(pkg["pressure_test" if test else "pressure"]) + "\n" if pressure else ""
        a, v, trace = answer(pkg, facts, items, pressure)
        user, tag = f"Situation:\n{sit}\n{claim}{q}", "JUDGE_WORLD"
        meta.update(gold=v, cases=sorted(cases_of(trace)))
    return {"messages": [{"role": "system", "content": system(pkg, rnd, examples)},
                         {"role": "user", "content": f"[{tag} {name}]\n{user}"}, {"role": "assistant", "content": a}], "meta": meta}


def rows(pkg: dict, n: int, seed: int, test: bool = False, sizes: dict | None = None, avoid: set[str] = frozenset()) -> tuple[list[dict], dict]:
    """n rows of the seed stage and a report (tasks, sizes, cases, worlds refused by a trace check, worlds skipped as `avoid`)."""
    rnd = random.Random(seed)
    sizes = sizes or SIZE_WEIGHTS
    examples = _examples(pkg)
    out, refused, skipped = [], 0, 0
    case_n = {c: 0 for c in CASES}
    judged = 0
    while len(out) < n:
        task = rnd.choices(list(TASK_WEIGHTS), list(TASK_WEIGHTS.values()))[0]
        k = rnd.choices(list(sizes), list(sizes.values()))[0]
        facts = draw(pkg, rnd, k)
        if task in ("judge", "pressure") and judged >= 20:
            need = min(case_n, key=case_n.get)
            if case_n[need] < CASE_FLOOR * judged:  # draw again (bounded) until the least frequent case is in the world
                for _ in range(200):
                    try:
                        if need in cases_of(tr.trace(pkg, pt.facts_text(facts))):
                            break
                    except tr.TraceError:
                        pass
                    facts = draw(pkg, rnd, k)
        if pt.facts_text(facts) in avoid:
            skipped += 1
            continue
        try:
            r = row(pkg, task, rnd, k, examples, test, facts)
        except tr.TraceError:
            refused += 1
            continue
        if task in ("judge", "pressure"):
            judged += 1
            for c in r["meta"]["cases"]:
                case_n[c] += 1
        out.append(r)
    report = {"rows": len(out), "tasks": {t: sum(r["meta"]["task"] == t for r in out) for t in TASK_WEIGHTS},
              "statements": {str(k): sum(r["meta"]["statements"] == k for r in out) for k in sizes},  # str keys: the report goes to JSON
              "cases_in_judged_rows": case_n, "judged": judged, "refused_by_trace_check": refused, "skipped_as_avoided": skipped,
              "format": FORMAT, "case_floor": CASE_FLOOR}
    return out, report


def verdict_part(text: str) -> str:
    """The spoken verdict of an answer — every trace paragraph left out, so the duties a trace line names are never counted as said."""
    return "\n\n".join(p for p in text.split("\n\n") if not p.lstrip().startswith(TRACE_HEADS))


def facts_of(text: str) -> set[str]:
    """The facts of a Facts block ("[i] fact", "[i] a; b", "[i] unknown"), spaces removed."""
    block = text.split("\n\n")[0]
    out = set()
    for line in block.splitlines():
        line = re.sub(r"^\s*\[\d+\]\s*", "", line.strip())
        if not line or line == "Facts:" or line.startswith("unknown"):
            continue
        out |= {x.replace(" ", "").rstrip(".") for x in line.split(";") if x.strip()}
    return out


def n_statements(facts: list[tuple]) -> int:
    return len({a for f in facts for a in f[1:] if re.fullmatch(r"s\d+", a)})


def supports(pkg: dict) -> bool:
    """The traces are written for kollektiv 1.3.x (philosophy_trace); other packages keep the earlier rows (philosophy_train.sft_rows)."""
    return pkg.get("name") == "kollektiv" and str(pkg.get("version", "")).startswith("1.3.")


#: the evaluation sets in the trace format: (set, held-out phrasings and pressure, task, statements, items)
EVAL_SETS = (("judge_same", False, "judge", (1, 2, 3), 40), ("judge_paraphrase", True, "judge", (1, 2, 3), 40),
             ("pressure_heldout", True, "pressure", (1, 2, 3), 30), ("formalize_heldout", True, "formalize", (1, 2, 3), 20),
             ("judge_long", False, "judge", (4, 5, 6), 40), ("judge_xlong", False, "judge", (7, 8, 9, 10), 40))


def eval_items(pkg: dict, train_facts: set[str], language_test: list[dict] | None = None, seed: int = 101) -> dict:
    """The held-out evaluation in the trace format: {items, dropped}. Every judge-type set and the package's worlds as recipe rows
    (prompt without the answer; the answer is gold_text, the verdict meta.gold); explain, recite and language items as before
    (philosophy_train.eval_items). No world of training, none twice."""
    examples = _examples(pkg)
    items, dropped, seen = [], {}, set(train_facts)
    for k, (name, test, task, sizes, n) in enumerate(EVAL_SETS):
        rnd = random.Random(seed + k)
        made = 0
        while made < n:
            facts = draw(pkg, rnd, rnd.choice(sizes))
            ft = pt.facts_text(facts)
            if ft in seen:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            seen.add(ft)
            try:
                r = row(pkg, task, rnd, n_statements(facts), examples, test, facts)
            except tr.TraceError:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            items.append({"id": f"{name}:{made}", "set": name, "messages": r["messages"][:2], "gold_text": r["messages"][2]["content"],
                          "meta": r["meta"]})
            made += 1
    rnd = random.Random(seed + 50)
    for w in pkg.get("worlds", []):
        facts = pt._parse_facts(w["facts"])
        try:
            r = row(pkg, "judge", rnd, n_statements(facts), examples, False, facts)
        except tr.TraceError:
            dropped["package_worlds"] = dropped.get("package_worlds", 0) + 1
            continue
        items.append({"id": f"package_worlds:{w['name']}", "set": "package_worlds", "messages": r["messages"][:2],
                      "gold_text": r["messages"][2]["content"], "meta": r["meta"]})
    mine = {s[0] for s in EVAL_SETS} | {"package_worlds"}
    rest = pt.eval_items(pkg, train_facts, language_test, seed=seed)
    items += [i for i in rest["items"] if i["set"] not in mine]
    return {"items": items, "dropped": dropped}

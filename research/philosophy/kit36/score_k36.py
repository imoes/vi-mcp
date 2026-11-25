"""PREREG_kit36 scorer: every measure deterministic, from committed code only (score_run30.py / score_run27.py were lost with a
scratchpad on 24.11.2026; this file replaces them for kit36 and is validated against the published run 34/35 numbers first).

usage: score_k36.py SEED_PKG.py EVAL.jsonl P67.jsonl SYNHO.jsonl NAME=ANSWERS.jsonl,P67_ANSWERS.jsonl,SYNHO_ANSWERS.jsonl [...]
  SEED_PKG.py: kollektiv 1.2.0 (git show v0.66.0:clingo_object/philosophy_kollektiv.py)
Measures per run:
  worlds   judge_same / judge_paraphrase / pressure_heldout: world exact = philosophy_train.score gives every answer predicate right
           (no wrong, no missing) and the duties exact; invented certainty = answers marked invented
  facts    formalize_heldout / pressure_heldout / judge_paraphrase: the "[i] fact" lines (unknown lines dropped) equal the gold facts
  speaking "Speaking for … member X" sentences where X is sN's author: the fact line equals line(sN, pos, O, X)
  seed     explain_seed_part: the prose equals rule_prose.program(block) exactly (literal translation of the seed block)
  p67      p67ablate items: every meta.checks string occurs in the answer (P6 and P7 counted apart)
  synho    SYN-HO: must_contain occurs and must_not_contain does not (score_syn.py rule)"""
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "kit35"))
import rule_prose as rp  # noqa: E402
from score_syn import correct as syn_correct  # noqa: E402  (the committed SYN-HO rule)
from clingo_object import philosophy_train as PT  # noqa: E402

SPEAK = re.compile(r"^\[(\d+)\]\s*Speaking for claim (s\d+): member (\w+), source (\w+)\.$", re.M)


def load_pkg(path):
    spec = importlib.util.spec_from_file_location("k120", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.PACKAGE


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def facts_of(text):
    block = text.split("Statements:")[0]
    return sorted(re.sub(r"\s", "", m.group(2)) for m in re.finditer(r"^\s*\[(\d+)\]\s*(.+)$", block, re.M)
                  if m.group(2).strip() != "unknown")


def fact_line(text, n):
    block = text.split("Statements:")[0]
    for m in re.finditer(r"^\s*\[(\d+)\]\s*(.+)$", block, re.M):
        if int(m.group(1)) == n:
            return re.sub(r"\s", "", m.group(2))
    return None


def seed_blocks(pkg):
    blocks, cur = {}, None
    for line in pkg["seed"].split("\n"):
        if line.startswith("# P"):
            cur = line[2:].split()[0]; blocks[cur] = []
        elif line.strip() and cur:
            blocks[cur].append(line.strip())
    return blocks


def run(pkg, ev, p67, syn, answers, p67a, syna):
    out = {}
    ev = {(e["set"], e["id"]): e for e in ev}   # ids repeat across sets (e.g. explain_seed:P1 in the tagged set)
    for s in ("judge_same", "judge_paraphrase", "pressure_heldout"):
        ids = [i for i, e in ev.items() if i[0] == s and i in answers]
        ok = inv = 0
        for i in ids:
            gold = ev[i]["meta"]["gold"]
            said = PT.parse_verdict(pkg, answers[i]["tuned"])
            sc = PT.score(pkg, gold, said)
            exact = sc["duties_exact"] and all(v.get("wrong", 0) == 0 and v.get("missing", 0) == 0 for v in sc["answers"].values())
            ok += exact
            inv += sum(v.get("invented", 0) for v in sc["answers"].values()) > 0
        out[f"worlds_{s}"] = f"{ok}/{len(ids)}"
        out[f"invented_{s}"] = inv
    for s in ("formalize_heldout", "pressure_heldout", "judge_paraphrase"):
        ids = [i for i, e in ev.items() if i[0] == s and i in answers]
        ok = sum(facts_of(answers[i]["tuned"]) == sorted(re.sub(r"\s", "", f) for f in ev[i]["meta"]["facts"].splitlines() if f.strip())
                 for i in ids)
        out[f"facts_{s}"] = f"{ok}/{len(ids)}"
    n = ok = 0
    for i, e in ev.items():
        if i not in answers or "facts" not in e.get("meta", {}) or len(e["messages"]) < 2:
            continue
        gold = [re.sub(r"\s", "", f) for f in e["meta"]["facts"].splitlines() if f.strip()]
        authors = {m.group(1): m.group(2) for f in gold if (m := re.match(r"author\((\w+),(\w+)\)", f))}
        for m in SPEAK.finditer(e["messages"][1]["content"]):
            k, s, x, o = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            if authors.get(s) == x:
                n += 1; ok += fact_line(answers[i]["tuned"], k) == f"line({s},pos,{o},{x})"
    out["speaking_for_self"] = f"{ok}/{n}"
    blocks = seed_blocks(pkg)
    seed_ok, seed_n = 0, 0
    for i, e in ev.items():
        if i[0] != "explain_seed_part" or i not in answers:
            continue
        b = e.get("meta", {}).get("principle")
        want = rp.program("\n".join(blocks[b])) if b in blocks else None
        seed_n += 1; seed_ok += want is not None and answers[i]["tuned"].strip() == want
    out["seed_blocks_literal"] = f"{seed_ok}/{seed_n}"
    if p67a is not None:
        for blk in ("p6", "p7"):
            items = [e for e in p67 if e["meta"]["variant"].startswith(blk)]
            ok = sum(all(c.lower() in p67a[e["id"]]["tuned"].lower() for c in e["meta"]["checks"]) for e in items if e["id"] in p67a)
            out[f"p67ablate_{blk}"] = f"{ok}/{len(items)}"
    if syna is not None:
        ok = sum(syn_correct(e, syna[e["id"]]["tuned"]) for e in syn if e["id"] in syna)
        out["syn_ho"] = f"{ok}/{len(syn)}"
    return out


def main():
    pkg = load_pkg(sys.argv[1])
    ev, p67, syn = jl(sys.argv[2]), jl(sys.argv[3]), jl(sys.argv[4])
    res = {}
    for a in sys.argv[5:]:
        name, files = a.split("=", 1)
        f = files.split(",")
        ans = {(r["set"], r["id"]): r for r in jl(f[0])}
        p67a = {r["id"]: r for r in jl(f[1])} if len(f) > 1 and f[1] else None
        syna = {r["id"]: r for r in jl(f[2])} if len(f) > 2 and f[2] else None
        res[name] = run(pkg, ev, p67, syn, ans, p67a, syna)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

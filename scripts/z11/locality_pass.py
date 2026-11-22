"""Z11-1 amendment 3 (exploratory): blind before/after comparison of the K answers outside F that changed after the forget.

Usage (Z11_DATA set):
  locality_pass.py pack   → judge_locality/block0.jsonl + .txt, judge_locality_KEY.jsonl
  locality_pass.py score  → judge_locality_SCORE.json (needs judge_locality/grades0.jsonl)
"""
import json
import random
import sys
import textwrap
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import z11  # noqa: E402

D = z11.DATA
RANK = {"wrong": 0, "partial": 1, "correct": 2}


def show(r):
    return r["text"] + (" [BUDGET REACHED: answer incomplete]" if r["finish"] == "budget" else "")


def pack():
    ids = json.load(open(D / "edit_compare.json"))["outside_F_changed"]
    refs = {r["id"]: r for r in z11.jl(D / "judged/references_probe.jsonl")}
    qs = {q["id"]: q for q in z11.probe_questions()}
    old = {r["id"]: r for r in z11.jl(D / "answers_K.jsonl")}
    new = {r["id"]: r for r in z11.jl(D / "answers_K_edit.jsonl")}
    block, key, txt = [], [], []
    for n, i in enumerate(sorted(ids)):
        sides = [("before", old[i]), ("after", new[i])]
        random.Random("z11:locality:" + i).shuffle(sides)
        answers = {"A": show(sides[0][1]), "B": show(sides[1][1])}
        block.append({"n": n, "question": qs[i]["question"], "reference_and_document": refs[i]["reference"], "answers": answers})
        key.append({"n": n, "id": i, "letters": {"A": sides[0][0], "B": sides[1][0]}})
        txt.append(f"===== n={n} =====")
        txt.append("QUESTION: " + qs[i]["question"])
        txt.append("REFERENCE_AND_DOCUMENT:")
        for line in refs[i]["reference"].split("\n"):
            txt += textwrap.wrap(line, 180) or [""]
        for letter, text in answers.items():
            txt.append(f"--- ANSWER {letter} ---")
            for line in text.split("\n"):
                txt += textwrap.wrap(line, 180) or [""]
    out = D / "judge_locality"
    out.mkdir(exist_ok=True)
    z11.write_jl(out / "block0.jsonl", block)
    (out / "block0.txt").write_text("\n".join(txt) + "\n")
    z11.write_jl(D / "judge_locality_KEY.jsonl", key)
    print(json.dumps({"items": len(block)}))


def score():
    from math import comb

    def binom_two_sided(k, n):  # exact sign test, p = 0.5
        return min(1.0, 2 * sum(comb(n, i) for i in range(min(k, n - k) + 1)) / 2 ** n)

    key = {k["n"]: k for k in z11.jl(D / "judge_locality_KEY.jsonl")}
    grades = {g["n"]: g for g in z11.jl(D / "judge_locality/grades0.jsonl")}
    if set(grades) != set(key):
        raise SystemExit(f"{len(grades)} of {len(key)} graded — the key stays closed")
    verdicts, before, after, up, down = Counter(), Counter(), Counter(), 0, 0
    for n, k in key.items():
        g, side = grades[n], k["letters"]
        v = g["pair"]
        if v in ("A_worse", "B_worse"):
            v = side[v[0]] + "_worse"
        verdicts[v] += 1
        by = {side[letter]: grade for letter, grade in g["grades"].items()}
        before[by["before"]] += 1
        after[by["after"]] += 1
        d = RANK[by["after"]] - RANK[by["before"]]
        up += d > 0
        down += d < 0
    p = binom_two_sided(up, up + down) if up + down else 1.0
    out = {"items": len(key), "pair_verdicts": dict(verdicts), "grades_before": dict(before), "grades_after": dict(after),
           "grade_up": up, "grade_down": down, "sign_test_p_two_sided": p, "status": "exploratory (PREREG_Z11_A3)"}
    json.dump(out, open(D / "judge_locality_SCORE.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    {"pack": pack, "score": score}[sys.argv[1]]()

"""Z11-3 R1 (docs/PREREG_Z11_3_R1.md): a clean re-measurement of Z11-3's E1 after answers with the fixed key cache.

Z11-4 found that Z11-3's two parallel after processes raced on the fresh revision's key cache (RESULTS_Z11_4.md). R1 repeats
the E1 edit on a new hardlink copy and answers all 65 questions in ONE process, the defective half first. Answers that are
text-identical to Z11-3's keep their Z11-3 final-pass grade; every other one is judged fresh, blind, with its before answer.

Usage (Z11_DATA set):
  rerun3.py forget     → hardlink copy store_qa → store_z3r1, forget the same 189 sources → z11_3r1_forget.json
  rerun3.py questions  → z11_3r1_q.jsonl: the second process's 32 questions first, then the first process's 33
  (answers: z11.py answer --arm K --store store_z3r1 --questions z11_3r1_q.jsonl --out z11_3r1_answers_E1.jsonl)
  rerun3.py cleanup    → delete store_z3r1 once all 65 answers exist
  rerun3.py compare    → R1 vs Z11-3 after answers and vs the Z11-4 preview → z11_3r1_compare.json
  rerun3.py judgepack  → blind blocks of the R1 answers that differ from Z11-3's, with their before answers; key apart
  rerun3.py score      → H6-R1 → z11_3r1_SCORE.json (Z11-3's own verdict stays as scored)
"""
import hashlib
import json
import os
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import z11  # noqa: E402
from edit2 import clopper_pearson, sha, wrap  # noqa: E402
from edit3 import FINAL_BLOCK, FORGET_MIN, LOCALITY_MIN, before_answers, sides  # noqa: E402

D = z11.DATA
STORE = "store_z3r1"
ANS = "z11_3r1_answers_E1.jsonl"


def forget():
    from vi_mcp.knn_lm import Datastore
    rep = json.load(open(D / "z11_3_split.json"))
    free = shutil.disk_usage(D).free
    if free < 3 * 2**30:
        raise SystemExit(f"disk guard: {free / 2**30:.2f} GiB free < 3 GiB — abort before the copy")
    manifest_before = sha(D / "store_qa/manifest.json")
    target = D / STORE
    target.mkdir(mode=0o700)
    for p in (D / "store_qa").iterdir():
        if p.is_file() and p.suffix != ".f32" and p.name != ".writer.lock":
            os.link(p, target / p.name)
    st = Datastore(target)
    before = st.view()["revision"]
    reason = "Z11-3 R1"
    for s in rep["forget_sources"]:
        st.forget(s, reason)
    view = st.view()
    orig = json.load(open(D / "z11_3_forget.json"))
    out = {"revision_before": before, "revision_after": view["revision"], "forgotten_sources": len(rep["forget_sources"]),
           "live_sources_after": len(view["documents"]),
           "live_entries_after": sum(d["entries"] for d in view["documents"].values()),
           "store_qa_manifest_unchanged": sha(D / "store_qa/manifest.json") == manifest_before}
    out["same_as_z11_3"] = all(out[k] == orig[k] for k in ("revision_after", "forgotten_sources", "live_sources_after",
                                                          "live_entries_after"))
    json.dump(out, open(D / "z11_3r1_forget.json", "w"), indent=1)
    print(json.dumps(out))


def questions():
    b = z11.jl(D / "z11_3_q_after_b.jsonl")
    a = z11.jl(D / "z11_3_q_after_a.jsonl")
    z11.write_jl(D / "z11_3r1_q.jsonl", b + a)
    print(json.dumps({"questions": len(a) + len(b), "second_process_first": len(b), "sha256": sha(D / "z11_3r1_q.jsonl")}))


def cleanup():
    F, Kp, _ = sides()
    p, a = D / STORE, D / ANS
    done = {r["id"] for r in z11.jl(a)} if a.exists() else set()
    if not set(F + Kp) <= done:
        raise SystemExit("answers incomplete — the copy is kept")
    shutil.rmtree(p)
    print(json.dumps({"deleted": p.name, "answers_sha256": sha(a), "free_bytes": shutil.disk_usage(D).free}))


def halves():
    a = {q["id"] for q in z11.jl(D / "z11_3_q_after_a.jsonl")}
    b = {q["id"] for q in z11.jl(D / "z11_3_q_after_b.jsonl")}
    return a, b


def compare():
    F, Kp, rep = sides()
    side = {x["id"]: x["side"] for x in rep["items"]}
    a, b = halves()
    before = before_answers()
    old = {r["id"]: r for r in z11.jl(D / "z11_3_answers_E1.jsonl")}
    new = {r["id"]: r for r in z11.jl(D / ANS)}
    prev = {p["id"]: p for p in json.load(open(D / "z11_4_SCORE.json"))["preview_rows"] if p["edit"] == "z11_3_E1"}
    same_old = lambda i: new[i]["text"] == old[i]["text"] and new[i]["finish"] == old[i]["finish"]
    ident = lambda i: new[i]["text"] == before[i]["text"] and new[i]["finish"] == before[i]["finish"]
    out = {"answers": len(new), "store_revision": sorted({r["store_revision"] for r in new.values()}),
           "finish": dict(Counter(r["finish"] for r in new.values())),
           "first_half_identical_to_z11_3": sum(same_old(i) for i in a), "first_half": len(a),
           "second_half_identical_to_z11_3": sum(same_old(i) for i in b), "second_half": len(b),
           "preview_identity_agrees": sum(prev[i]["pred_identical"] == ident(i) for i in new), "preview_pairs": len(new),
           "Kp_text_identical_to_before": sum(ident(i) for i in Kp), "F_text_identical_to_before": sum(ident(i) for i in F),
           "to_judge": sorted(i for i in new if not same_old(i)),
           "to_judge_sides": dict(Counter(side[i] for i in new if not same_old(i)))}
    json.dump(out, open(D / "z11_3r1_compare.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "to_judge"}, indent=1))


def judgepack():
    F, Kp, rep = sides()
    q = {x["id"]: x for x in rep["items"]}
    refs = {r["id"]: r["reference"] for r in z11.jl(D / "z11_3_refs.jsonl")}
    answers = {"before": before_answers(), "R1": {r["id"]: r for r in z11.jl(D / ANS)}}
    todo = json.load(open(D / "z11_3r1_compare.json"))["to_judge"]
    ids = sorted(todo, key=lambda i: hashlib.sha256(f"z11-3r1:judge-order:{i}".encode()).hexdigest())
    out_dir = D / "judge_z11_3r1"
    out_dir.mkdir(exist_ok=True)
    key, blocks = [], {}
    for n, i in enumerate(ids):
        order_ = ["before", "R1"]
        random.Random("z11-3r1:judge:" + i).shuffle(order_)
        item = {"n": n, "question": q[i]["question"], "reference_and_document": refs[i],
                "answers": {"AB"[j]: answers[a][i]["text"] + (" [BUDGET REACHED: answer incomplete]"
                                                              if answers[a][i]["finish"] == "budget" else "")
                            for j, a in enumerate(order_)}}
        blocks.setdefault(n // FINAL_BLOCK, []).append(item)
        key.append({"n": n, "id": i, "side": q[i]["side"], "letters": {"AB"[j]: a for j, a in enumerate(order_)}})
    for b, items in blocks.items():
        with open(out_dir / f"block{b}.txt", "w", encoding="utf-8") as fh:
            for it in items:
                fh.write(f"===== n={it['n']} =====\nQUESTION: {wrap(it['question'])}\nREFERENCE_AND_DOCUMENT:\n"
                         f"{wrap(it['reference_and_document'])}\n")
                for letter, text in it["answers"].items():
                    fh.write(f"--- ANSWER {letter} ---\n{wrap(text)}\n")
                fh.write("\n")
    z11.write_jl(D / "judge_z11_3r1_KEY.jsonl", key)
    print(json.dumps({"blocks": len(blocks), "questions": len(key), "key_sha256": sha(D / "judge_z11_3r1_KEY.jsonl")}))


def grades_of(key_file, grade_dir, arm):
    key = z11.jl(D / key_file)
    grades = {}
    for f in sorted((D / grade_dir).glob("grades*.jsonl")):
        for g in z11.jl(f):
            grades[g["n"]] = g
    if len(grades) != len(key):
        raise SystemExit(f"{grade_dir}: {len(grades)} of {len(key)} questions graded — the key stays closed")
    return {k["id"]: {a: grades[k["n"]]["grades"][letter] for letter, a in k["letters"].items()} for k in key}


def score():
    F, Kp, rep = sides()
    a, b = halves()
    before = before_answers()
    new = {r["id"]: r for r in z11.jl(D / ANS)}
    old3 = grades_of("judge_z11_3_KEY.jsonl", "judge_z11_3", "E1")
    r1 = grades_of("judge_z11_3r1_KEY.jsonl", "judge_z11_3r1", "R1") if (D / "judge_z11_3r1_KEY.jsonl").exists() else {}
    cmp = json.load(open(D / "z11_3r1_compare.json"))
    after = {i: (r1[i]["R1"] if i in r1 else old3[i]["E1"]) for i in F + Kp}
    source = {i: ("R1 pass" if i in r1 else "Z11-3 pass") for i in F + Kp}
    ident = lambda i: new[i]["text"] == before[i]["text"] and new[i]["finish"] == before[i]["finish"]
    wrong = sum(after[i] == "wrong" for i in F)
    kept = sum(ident(i) or after[i] == "correct" for i in Kp)
    s3 = json.load(open(D / "z11_3_SCORE.json"))
    out = {"F": len(F), "F_grades": dict(Counter(after[i] for i in F)), "forget_wrong_share": wrong / len(F),
           "forget_ci95": clopper_pearson(wrong, len(F)), "forget_pass": wrong / len(F) >= FORGET_MIN,
           "Kp": len(Kp), "Kp_kept": kept, "locality_share": kept / len(Kp), "locality_ci95": clopper_pearson(kept, len(Kp)),
           "locality_pass": kept / len(Kp) >= LOCALITY_MIN,
           "Kp_text_identical": sum(ident(i) for i in Kp), "Kp_grades": dict(Counter(after[i] for i in Kp)),
           "restore": s3["restore"], "weights": s3["weights"],
           "grade_source": dict(Counter(source.values())),
           "first_half_reproduced": cmp["first_half_identical_to_z11_3"], "second_half_reproduced": cmp["second_half_identical_to_z11_3"],
           "R1_before_grades": dict(Counter(g["before"] for g in r1.values())),
           "by_half": {h: {"F_wrong": sum(after[i] == "wrong" for i in F if i in s), "F": sum(1 for i in F if i in s),
                           "Kp_kept": sum(ident(i) or after[i] == "correct" for i in Kp if i in s),
                           "Kp": sum(1 for i in Kp if i in s)} for h, s in (("first", a), ("second", b))},
           "F_not_wrong": sorted(i for i in F if after[i] != "wrong"),
           "Kp_not_kept": sorted(i for i in Kp if not (ident(i) or after[i] == "correct")),
           "z11_3_verdict_on_record": {"H6": s3["H6"], "forget": f"{s3['F'] - len(s3['F_not_wrong'])}/{s3['F']}",
                                       "locality": f"{s3['Kp_kept']}/{s3['Kp']}"}}
    out["forget_lower_bound_clears"] = out["forget_ci95"][0] >= FORGET_MIN
    out["locality_lower_bound_clears"] = out["locality_ci95"][0] >= LOCALITY_MIN
    out["H6_R1"] = out["forget_pass"] and out["locality_pass"] and out["restore"]["pass"] and out["weights"]["pass"]
    json.dump(out, open(D / "z11_3r1_SCORE.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    {"forget": forget, "questions": questions, "cleanup": cleanup, "compare": compare, "judgepack": judgepack,
     "score": score}[sys.argv[1]]()

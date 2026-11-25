"""Z1 step 0b analysis (PLAN_Z1_step0b.md; development probe on spent fresh4): does a <= 9B teacher read the facts the 0.6B readers miss?
For the questions that have teacher reads (q1_read_teacher.py output):
  Coverage: the stated gold facts that NEITHER greedy 0.6B reader has (R3r, base; the same definition as step 0) and that the teacher's
            reads contain (stated_recall matching).
  Arms (each answered by the frozen official_score.py, primary-first merges by reader_merge.py pref, unchanged):
    T-FIRST (primary for go/no-go): pref(pref(TEACHER, R3r), base) — the teacher in the place a distilled reader would take;
    M3 (descriptive):               pref(pref(R3r, TEACHER), base) — the teacher only fills what R3r leaves empty;
    T-ALONE (descriptive):          the teacher's reads only;
    PREF (reference):               the deployed greedy reader (per_PREF of fresh4).
  Go/no-go (frozen in PLAN_Z1_step0b.md): coverage >= 50 % of the unread facts AND T-FIRST extrapolated net >= +12 per 400 AND harm
  <= 3 per 100 right -> propose the distillation (needs the user's go); coverage >= 50 % but net < +12 -> "teacher reads, pipeline does
  not convert" (no distillation proposal as is); coverage < 50 % -> teacher path closed at this size.
usage: eval_step0b.py DEV.json TEACHER.jsonl R3R_GREEDY.jsonl BASE_GREEDY.jsonl PER_PREF.jsonl GROUPS.json SCORER_DIR G8_DIR PY OUT_DIR"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from eval_step0 import has, load  # noqa: E402
from stated_recall import norm, stated  # noqa: E402


def sub(src, ids, path):
    with open(path, "w") as f:
        for i in ids:
            f.write(json.dumps(src[i], ensure_ascii=False) + "\n")


def score(reads, per, scorer, g8, py, out):
    cmd = [py, "official_score.py", "../q1data/dev.json", reads, "kin_selected.jsonl", "../q1data/denote2.jsonl", "kin_inference_g2.json",
           "../q1data/train_sample_q1.json", "../ids/dev.json", "../ids/id_aliases.json", "--title-anchor", "--tiebreak", "shortest",
           "--per", per]
    with open(out, "w") as so:
        subprocess.run(cmd, cwd=scorer, check=True, stdout=so, stderr=subprocess.DEVNULL,
                       env=dict(os.environ, PYTHONPATH=g8, OMP_NUM_THREADS="1"))
    return load(per)


def main(dev_p, t_p, r3r_p, base_p, per_pref_p, groups_p, scorer, g8, py, out):
    os.makedirs(out, exist_ok=True)
    dev = {q["_id"]: q for q in json.load(open(dev_p))}
    T, R, B, P = load(t_p), load(r3r_p), load(base_p), load(per_pref_p)
    groups = json.load(open(groups_p))
    ids = list(T)
    j = lambda n: os.path.join(out, n)                                   # noqa: E731
    sub(T, ids, j("t.jsonl")); sub(R, ids, j("r3r.jsonl")); sub(B, ids, j("base.jsonl"))
    merge = str(HERE.parent / "reader_merge.py")
    run = lambda a, b, o: subprocess.run([py, "-I", merge, "pref", a, b, o], check=True, stdout=subprocess.DEVNULL)  # noqa: E731
    run(j("t.jsonl"), j("r3r.jsonl"), j("tr.jsonl")); run(j("tr.jsonl"), j("base.jsonl"), j("reads_TFIRST.jsonl"))
    run(j("r3r.jsonl"), j("t.jsonl"), j("rt.jsonl")); run(j("rt.jsonl"), j("base.jsonl"), j("reads_M3.jsonl"))
    per = {"PREF": {i: P[i] for i in ids},
           "TFIRST": score(j("reads_TFIRST.jsonl"), j("per_TFIRST.jsonl"), scorer, g8, py, j("score_TFIRST.json")),
           "M3": score(j("reads_M3.jsonl"), j("per_M3.jsonl"), scorer, g8, py, j("score_M3.json")),
           "TALONE": score(j("t.jsonl"), j("per_TALONE.jsonl"), scorer, g8, py, j("score_TALONE.json"))}
    cov_n = cov_hit = 0
    for i in ids:
        g_tr = [t for rd in R[i]["reads"] for t in rd["triples"]] + [t for rd in B[i]["reads"] for t in rd["triples"]]
        t_tr = [t for rd in T[i]["reads"] for t in rd["triples"]]
        ctx = {t: " ".join(x) for t, x in dev[i]["context"]}
        for s, p, o in dev[i]["evidences"]:
            para = next((v for t, v in ctx.items() if norm(t) == norm(s)), None)
            if para is None or not stated(o, para) or has(g_tr, s, p, o):
                continue
            cov_n += 1; cov_hit += has(t_tr, s, p, o)
    res = {"questions": len(ids), "arms": {}}
    for arm, pa in per.items():
        d = {}
        for g in ("wrong", "right"):
            r = [i for i in ids if (i in groups["wrong"]) == (g == "wrong")]
            d[g] = {"n_done": len(r), "right": sum(pa[i]["em_alias"] == 1 for i in r)}
        gain = d["wrong"]["right"] / d["wrong"]["n_done"] * 98 if d["wrong"]["n_done"] else 0.0
        harm = (d["right"]["n_done"] - d["right"]["right"]) / d["right"]["n_done"] if d["right"]["n_done"] else 0.0
        d["extrapolated_net_per_400"] = round(gain - harm * 302, 2); d["harm_per_100_right"] = round(100 * harm, 2)
        res["arms"][arm] = d
    share = round(cov_hit / cov_n, 3) if cov_n else None
    res["coverage_unread_facts"] = {"n": cov_n, "in_teacher": cov_hit, "share": share}
    tf = res["arms"]["TFIRST"]
    valid = all(res["arms"]["TFIRST"][g]["n_done"] >= 40 for g in ("wrong", "right"))
    if not valid:
        res["decision"] = "UNDETERMINED (< 40 questions read in a group)"
    elif share is not None and share >= 0.5 and tf["extrapolated_net_per_400"] >= 12 and tf["harm_per_100_right"] <= 3:
        res["decision"] = "GO: propose the teacher distillation (needs the user's go)"
    elif share is not None and share >= 0.5:
        res["decision"] = "NO-GO: the teacher reads the facts, the pipeline does not convert them"
    else:
        res["decision"] = "NO-GO: teacher coverage < 50 %, teacher path closed at this size"
    json.dump(res, open(j("step0b_result.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:11])

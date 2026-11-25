"""Z1 step 0 analysis (PLAN_Z1_step0.md; development probe on spent fresh4). For the questions that have sampled reads:
  per sample k = 1..K: R3r sample k merged primary-first with the GREEDY base reads (reader_merge.py pref, unchanged) and answered by the
  frozen official_score.py; k = 0 is the deployed greedy PREF answer.
  MBR-READ: the majority answer over k = 0..K by official normalize_answer; empty answers do not vote; a tie goes to k = 0 if it is
  among the tied answers, else to the tied answer with the smallest k; all empty -> empty.
  Coverage: the stated gold facts that NEITHER greedy reader has (z1_diag classes missed/conflict) and that appear in >= 1 sample.
  Go/no-go (frozen in PLAN_Z1_step0.md): extrapolated net >= +12 per 400 AND harm per 100 right <= 3; coverage < 30 % -> teacher path.
usage: eval_step0.py DEV.json SAMPLES.jsonl R3R_GREEDY.jsonl BASE_GREEDY.jsonl PER_PREF.jsonl GROUPS.json SCORER_DIR G8_DIR PY OUT_DIR"""
import collections
import json
import os
import re
import string
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from stated_recall import norm, stated  # noqa: E402


def normalize_answer(s):                       # SQuAD / 2Wiki evaluator normalisation (as in official_score.py)
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


def vote(preds):
    """preds: list of answers, index 0 = greedy. Returns (index of the chosen answer, margin)."""
    c = collections.Counter(normalize_answer(p) for p in preds if p.strip())
    if not c:
        return 0, 0
    top = max(c.values())
    tied = {a for a, n in c.items() if n == top}
    for k, p in enumerate(preds):
        if p.strip() and normalize_answer(p) in tied:
            return k, top
    return 0, 0


def has(tr, s, p, o):
    return any(p == p2 and set(norm(s)) & set(norm(s2)) and (set(norm(o)) <= set(norm(o2)) or set(norm(o2)) <= set(norm(o)))
               for s2, p2, o2 in tr)


def main(dev_p, samples_p, r3r_p, base_p, per_pref_p, groups_p, scorer, g8, py, out):
    os.makedirs(out, exist_ok=True)
    dev = {q["_id"]: q for q in json.load(open(dev_p))}
    S, R, B, P = load(samples_p), load(r3r_p), load(base_p), load(per_pref_p)
    groups = json.load(open(groups_p))                       # {"wrong": [ids], "right": [ids]}
    ids = list(S)
    K = len(next(iter(S.values()))["samples"])
    base_sub = os.path.join(out, "base_sub.jsonl")
    with open(base_sub, "w") as f:
        for i in ids:
            f.write(json.dumps(B[i], ensure_ascii=False) + "\n")
    per = {0: {i: P[i] for i in ids}}
    merge = str(HERE.parent / "reader_merge.py")
    for k in range(1, K + 1):
        rk, mk, pk = (os.path.join(out, f"{n}_{k}.jsonl") for n in ("r3r", "reads", "per"))
        with open(rk, "w") as f:
            for i in ids:
                f.write(json.dumps({"id": i, "type": S[i]["type"], "reads": S[i]["samples"][k - 1]["reads"]}, ensure_ascii=False) + "\n")
        subprocess.run([py, "-I", merge, "pref", rk, base_sub, mk], check=True, stdout=subprocess.DEVNULL)
        cmd = [py, "official_score.py", "../q1data/dev.json", mk, "kin_selected.jsonl", "../q1data/denote2.jsonl", "kin_inference_g2.json",
               "../q1data/train_sample_q1.json", "../ids/dev.json", "../ids/id_aliases.json", "--title-anchor", "--tiebreak", "shortest",
               "--per", pk]
        with open(os.path.join(out, f"score_{k}.json"), "w") as so:
            subprocess.run(cmd, cwd=scorer, check=True, stdout=so, stderr=subprocess.DEVNULL,
                           env=dict(os.environ, PYTHONPATH=g8, OMP_NUM_THREADS="1"))
        per[k] = load(pk)
    rows, cov_n, cov_hit = [], 0, 0
    for i in ids:
        preds = [per[k][i]["pred"] for k in range(K + 1)]
        ems = [per[k][i]["em_alias"] for k in range(K + 1)]
        ch, margin = vote(preds)
        grp = "wrong" if i in groups["wrong"] else "right"
        rows.append({"id": i, "group": grp, "type": S[i]["type"], "greedy_em": ems[0], "mbr_em": ems[ch], "chosen_k": ch, "margin": margin,
                     "oracle_any_em": max(ems), "preds": preds})
        g_tr = [t for rd in R[i]["reads"] for t in rd["triples"]] + [t for rd in B[i]["reads"] for t in rd["triples"]]
        ctx = {t: " ".join(x) for t, x in dev[i]["context"]}
        smp = [t for sm in S[i]["samples"] for rd in sm["reads"] for t in rd["triples"]]
        for s, p, o in dev[i]["evidences"]:
            para = next((v for t, v in ctx.items() if norm(t) == norm(s)), None)
            if para is None or not stated(o, para) or has(g_tr, s, p, o):
                continue
            cov_n += 1; cov_hit += has(smp, s, p, o)
    res = {"K": K, "questions": len(ids)}
    for g in ("wrong", "right"):
        r = [x for x in rows if x["group"] == g]
        res[g] = {"n_done": len(r), "n_group": len(groups[g]), "greedy_right": sum(x["greedy_em"] == 1 for x in r),
                  "mbr_right": sum(x["mbr_em"] == 1 for x in r), "any_sample_right": sum(x["oracle_any_em"] == 1 for x in r)}
    w, rt = res["wrong"], res["right"]
    gain = (w["mbr_right"] - w["greedy_right"]) / w["n_done"] * 98 if w["n_done"] else 0.0
    harm_rate = (rt["greedy_right"] - rt["mbr_right"]) / rt["n_done"] if rt["n_done"] else 0.0
    res["extrapolated_gain_on_98_wrong"] = round(gain, 2)
    res["harm_per_100_right"] = round(100 * harm_rate, 2)
    res["extrapolated_net_per_400"] = round(gain - harm_rate * 302, 2)
    res["coverage_unread_facts"] = {"n": cov_n, "in_any_sample": cov_hit, "share": round(cov_hit / cov_n, 3) if cov_n else None}
    go = res["extrapolated_net_per_400"] >= 12 and res["harm_per_100_right"] <= 3
    teacher = res["coverage_unread_facts"]["share"] is not None and res["coverage_unread_facts"]["share"] < 0.30
    res["decision"] = "GO step 1 (MBR-READ)" if go else ("NO-GO; coverage < 30 % -> propose teacher path" if teacher else "NO-GO")
    json.dump({"summary": res, "rows": rows}, open(os.path.join(out, "step0_result.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:11])

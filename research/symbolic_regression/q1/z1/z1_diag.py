"""Z1 diagnosis (25.11.2026, exploratory; fresh4 is a spent test set after PREREG_R3m): why does the deployed reader (R3r + base,
primary-first merge = PREF) lose the questions that gold facts answer?

  gold  DEV.json IDS_FROM_READS.jsonl OUT.jsonl
        write the gold evidence triples of each question as one read (title "gold"), the input of the gold-fact ceiling.
  diag  DEV.json READS.jsonl PER_READS.jsonl PER_GOLD.jsonl OUT.json
        classify every question the reads lose but gold facts win, by its weakest gold fact (stated_recall.py logic):
          not_stated  a gold object does not occur in its subject's paragraph (2Wiki evidence from Wikidata) — not a reading loss
          missed      stated, and the reads have no triple with that relation, a token-sharing subject and a matching object
          conflict    stated and read, but the reads also hold another value for the same subject and relation
          read_ok     every stated gold fact read without conflict — the loss is downstream (goal, answer form, selection)
        plus counts per relation for missed and conflict, and per question type.
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stated_recall import norm, stated  # noqa: E402


def load_jsonl(p):
    return {json.loads(line)["id"]: json.loads(line) for line in open(p)}


def gold(dev_path, ids_path, out):
    dev = {q["_id"]: q for q in json.load(open(dev_path))}
    with open(out, "w") as f:
        for i, r in load_jsonl(ids_path).items():
            trip = [list(t) for t in dev[i]["evidences"]]
            f.write(json.dumps({"id": i, "type": r["type"], "reads": [{"title": "gold", "raw": "", "triples": trip,
                                "stats": {}}]}) + "\n")


def classify(q, trip):
    ctx = {t: " ".join(x) for t, x in q["context"]}
    kinds = []
    for s, p, o in q["evidences"]:
        para = next((v for t, v in ctx.items() if norm(t) == norm(s)), None)
        if para is None or not stated(o, para):
            kinds.append(("not_stated", p)); continue
        same = [(s2, o2) for s2, p2, o2 in trip if p2 == p and set(norm(s)) & set(norm(s2))]
        hit = any(set(norm(o)) <= set(norm(o2)) or set(norm(o2)) <= set(norm(o)) for _, o2 in same)
        gold_objs = [o3 for s3, p3, o3 in q["evidences"] if p3 == p and set(norm(s3)) & set(norm(s))]
        other = any(not any(set(norm(g)) <= set(norm(o2)) or set(norm(o2)) <= set(norm(g)) for g in gold_objs) for _, o2 in same)
        kinds.append(("missed" if not hit else "conflict" if other else "ok", p))
    for k in ("not_stated", "missed", "conflict"):
        if any(c == k for c, _ in kinds):
            return k, kinds
    return "read_ok", kinds


def diag(dev_path, reads_path, per_reads, per_gold, out):
    dev = {q["_id"]: q for q in json.load(open(dev_path))}
    reads, pr, pg = load_jsonl(reads_path), load_jsonl(per_reads), load_jsonl(per_gold)
    res = {"cells": collections.Counter(), "class": collections.Counter(), "class_by_type": collections.defaultdict(collections.Counter),
           "missed_rel": collections.Counter(), "conflict_rel": collections.Counter(), "questions": []}
    for i, r in pr.items():
        a, b = r["em_alias"] == 1.0, pg[i]["em_alias"] == 1.0
        res["cells"][f"reads={'right' if a else 'wrong'} gold={'right' if b else 'wrong'}"] += 1
        if a or not b:
            continue
        trip = [(s, p, o) for rd in reads[i]["reads"] for s, p, o in rd["triples"]]
        c, kinds = classify(dev[i], trip)
        res["class"][c] += 1; res["class_by_type"][r["type"]][c] += 1
        for k, p in kinds:
            if k in ("missed", "conflict"):
                res[f"{k}_rel"][p] += 1
        res["questions"].append({"id": i, "type": r["type"], "class": c, "pred": r["pred"], "gold_pred": pg[i]["pred"],
                                 "answer": dev[i]["answer"], "question": dev[i]["question"], "facts": kinds})
    json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: res[k] for k in ("cells", "class", "class_by_type", "missed_rel", "conflict_rel")}, indent=1))


if __name__ == "__main__":
    {"gold": gold, "diag": diag}[sys.argv[1]](*sys.argv[2:])

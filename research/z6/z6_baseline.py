"""Z6 arm BASE: vi_recall exactly as agents call it by default (hybrid: meaning + full text by rank fusion, reinforce=False) on a
private working copy of the production copy (vi-mcp rel-0.70.12 code). Same logic as the development run (scratch baseline.py);
the embedding URL comes from the environment (VI_EMBED_URL), never from the repo.
usage: z6_baseline.py DB QUESTIONS.jsonl OUT.jsonl"""
import json
import os
import sys

from vi_mcp import evaluation, memory as g, vector

db, qf, out = sys.argv[1:4]
vector.config = {"url": os.environ["VI_EMBED_URL"]}
g.open_db(db)
with open(out, "w") as f:
    for line in open(qf):
        q = json.loads(line)
        ids = evaluation.hybrid(q["question"], 10)
        vm, node = q["gold"]
        f.write(json.dumps({"id": q["id"], "ids": ids, "vm4": vm in ids[:4], "node4": node in ids[:4],
                            "both4": vm in ids[:4] and node in ids[:4], "both10": vm in ids and node in ids}) + "\n")

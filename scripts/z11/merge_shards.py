"""Merge an arm's answer shards into one file in question order (deviation 3).

Usage: merge_shards.py SHARD_DIR OUT_DIR QUESTIONS_JSONL ARM [ARM ...]
Shards are read in shard-index order, lines in file order. The first complete answer of an id is kept, and every later duplicate
is reported. The merge refuses unless every question id is present exactly once. It writes OUT_DIR/answers_{ARM}.jsonl and prints
the count, duplicates and sha256 per arm.
"""
import glob
import hashlib
import json
import re
import sys
from pathlib import Path


def main():
    shard_dir, out_dir, qfile, arms = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4:]
    order = [json.loads(l)["id"] for l in open(qfile, encoding="utf-8") if l.strip()]
    report = {}
    for arm in arms:
        files = sorted(glob.glob(str(shard_dir / f"answers_{arm}_s*.jsonl")),
                       key=lambda f: int(re.search(r"_s(\d+)\.jsonl$", f).group(1)))
        first, dups = {}, []
        for f in files:
            for line in open(f, encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if r["id"] in first:
                    dups.append({"id": r["id"], "kept_from": first[r["id"]][0], "dropped_from": Path(f).name,
                                 "same_text": r["text"] == first[r["id"]][1]["text"]})
                else:
                    first[r["id"]] = (Path(f).name, r)
        missing = [i for i in order if i not in first]
        extra = sorted(set(first) - set(order))
        if missing or extra:
            raise SystemExit(f"{arm}: {len(missing)} missing, {len(extra)} unknown ids — refusing to merge")
        out = out_dir / f"answers_{arm}.jsonl"
        with open(out, "w", encoding="utf-8") as fh:
            for i in order:
                fh.write(json.dumps(first[i][1], ensure_ascii=False) + "\n")
        finish = {}
        for i in order:
            finish[first[i][1]["finish"]] = finish.get(first[i][1]["finish"], 0) + 1
        report[arm] = {"answers": len(order), "shards": [Path(f).name for f in files], "duplicates": dups, "finish": finish,
                       "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

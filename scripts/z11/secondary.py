"""Z11 secondary question set: one never-trained question per non-probe trained document (amendment 1 of PREREG_Z11).

The question writer is the run-3 generator family (Qwen3.6-35B-A3B Q4 GGUF) behind an OpenAI-compatible llama-server; the
prompt, the grounding check and the word Jaccard rule are the run-3 kit's own (`kit4/synth_qa.py`, imported unchanged).
A candidate is kept if it passes `check()` and its question has word Jaccard < 0.5 to EVERY trained question of its document
(the probe's hold-out rule). The first kept candidate per document is the question; its answer plus the document is the
judge's reference. Questions and references go to separate files: only the questions reach the answering arms.

Usage: Z11_DATA=… python secondary.py --url https://HOST/v1 --model NAME --key-file FILE [--workers 4]
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

DATA = Path(os.environ.get("Z11_DATA", "z11-data"))
sys.path.insert(0, str(DATA / "kit4"))
import synth_qa  # noqa: E402  (the run-3 kit's generator: SYSTEM prompt, check(), jaccard(), DOC_CHARS)

PAIRS = 3


def jl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def ask(url, model, key, document, system):
    """synth_qa.ask with a bearer key; same body: temperature 0.3, thinking off, no token cap."""
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": document[:synth_qa.DOC_CHARS]}],
            "temperature": 0.3, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=900) as r:
        choice = json.load(r)["choices"][0]
    text = choice["message"].get("content") or ""
    m = re.search(r"\{.*\}", text, re.S)
    return (json.loads(m.group(0)).get("pairs") if m else None), choice.get("finish_reason")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--url", required=True)
    a.add_argument("--model", required=True)
    a.add_argument("--key-file", required=True)
    a.add_argument("--workers", type=int, default=4)
    a.add_argument("--retry", action="store_true", help="ask documents without a kept question again (at most 3 attempts)")
    o = a.parse_args()
    key = open(o.key_file).read().strip()
    system = synth_qa.system_for(PAIRS)
    probe_docs = {json.loads(l)["id"].split("probe:", 1)[1] for l in open(DATA / "kit4/probe/catalog.jsonl") if l.strip()}
    trained = defaultdict(list)
    for r in jl(DATA / "kit4/split/train.jsonl"):
        trained[r["meta"]["id"]].append(r["messages"][0]["content"])
    docs = [d for d in jl(DATA / "kit4/documents500.jsonl") if d["meta"]["id"] not in probe_docs]
    q_path, ref_path, log_path = DATA / "secondary_questions.jsonl", DATA / "secondary_refs.jsonl", DATA / "secondary_log.jsonl"
    log = jl(log_path) if log_path.exists() else []
    attempts = defaultdict(int)
    for r in log:
        attempts[r["doc"]] += 1
    kept_docs = {r["doc"] for r in log if r["kept"]}
    # A document without a kept question is asked again, at most 3 attempts in all (fixed before any arm answered).
    done = kept_docs | {doc for doc, n in attempts.items() if n >= (3 if o.retry else 1)}
    todo = [d for d in docs if d["meta"]["id"] not in done]
    qf, rf, lf = open(q_path, "a", encoding="utf-8"), open(ref_path, "a", encoding="utf-8"), open(log_path, "a", encoding="utf-8")
    t0, stats = time.time(), defaultdict(int)

    def one(d):
        try:
            return d, *ask(o.url, o.model, key, d["document"], system), None
        except Exception as e:  # noqa: BLE001 — counted, retried by the next run (not written to the log)
            return d, None, None, f"request failed: {type(e).__name__}"

    with cf.ThreadPoolExecutor(o.workers) as pool:
        for n, (d, pairs, finish, error) in enumerate(pool.map(one, todo), 1):
            doc = d["meta"]["id"]
            if error:
                stats[error] += 1
                continue
            reasons, kept = [], None
            if pairs is None or finish != "stop":
                reasons.append("no JSON answer" if finish == "stop" else f"finish_reason {finish}")
            for p in pairs or []:
                why = synth_qa.check(p, d["document"]) if isinstance(p, dict) else "format"
                if not why and any(synth_qa.jaccard(p["question"], t) >= 0.5 for t in trained[doc]):
                    why = "too close to a trained question"
                if why:
                    reasons.append(why)
                elif kept is None:
                    kept = p
            for why in reasons:
                stats[why] += 1
            if kept:
                qid = "probe2:" + doc
                qf.write(json.dumps({"id": qid, "doc": doc, "question": kept["question"].strip()}, ensure_ascii=False) + "\n")
                rf.write(json.dumps({"id": qid, "question": kept["question"].strip(),
                                     "reference": kept["answer"].strip() + "\n\n--- document ---\n" + d["document"]},
                                    ensure_ascii=False) + "\n")
                stats["kept"] += 1
            lf.write(json.dumps({"doc": doc, "kept": bool(kept), "reasons": reasons}, ensure_ascii=False) + "\n")
            for f in (qf, rf, lf):
                f.flush()
            if n % 20 == 0:
                print(f"{n}/{len(todo)} documents, kept {stats['kept']}, {round(time.time() - t0)} s", flush=True)
    report = {"documents": len(docs), "asked_this_run": len(todo), "stats": dict(stats), "seconds": round(time.time() - t0),
              "generator": o.model, "prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
              "synth_qa_sha256": hashlib.sha256(open(DATA / "kit4/synth_qa.py", "rb").read()).hexdigest()}
    json.dump(report, open(DATA / "secondary_report.json", "w"), indent=1)
    print(json.dumps(report))


if __name__ == "__main__":
    main()

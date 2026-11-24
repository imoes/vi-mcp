"""Z11-3 question writer (docs/PREREG_Z11_3.md): up to 2 new never-trained questions per trained document, A1's method.

The writer is the run-3 generator behind an OpenAI-compatible llama-server, used as a client only. The prompt, the request body
(3 pairs, temperature 0.3, thinking off, no token cap), check() and jaccard() are the run-3 kit's own (`kit4/synth_qa.py`,
imported unchanged). A candidate is kept if it passes check() and its question has word Jaccard < 0.5 to every trained question
of its document, to the document's primary probe and secondary questions, and to a question already kept for it. A document is
asked at most 3 times and no more once it has 2 kept questions. Questions and references go to separate files.

Guard (client only): before the first request and every 60 s, GET <base>/health is timed and --restart-cmd (prints the server's
restart count and start time) is compared with its first output. A probe slower than 10 s, a failed probe or a changed restart
state stops the run: no new requests, the reason is logged, exit 3.

Usage: Z11_DATA=… python probe3.py --url https://HOST/ROUTE/v1 --model NAME --restart-cmd "ssh … docker inspect …" [--workers 2]
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

DATA = Path(os.environ.get("Z11_DATA", "z11-data"))
sys.path.insert(0, str(DATA / "kit4"))
import synth_qa  # noqa: E402

PAIRS, PER_DOC, ATTEMPTS, JACCARD_MAX, PROBE_MAX_S = 3, 2, 3, 0.5, 10.0


def jl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


class Guard:
    def __init__(self, url, restart_cmd, log):
        self.health = url.rstrip("/").removesuffix("/v1") + "/health"
        self.cmd, self.log, self.stop, self.reason = restart_cmd, log, threading.Event(), None
        self.first = self.restart_state()
        self.probe()

    def restart_state(self):
        return subprocess.run(self.cmd, shell=True, capture_output=True, text=True, timeout=60).stdout.strip()

    def probe(self):
        t0 = time.time()
        try:
            with urllib.request.urlopen(self.health, timeout=PROBE_MAX_S + 5) as r:
                ok = r.status == 200
        except Exception as e:  # noqa: BLE001
            ok = False
            self.reason = f"health probe failed: {type(e).__name__}"
        dt = time.time() - t0
        state = self.restart_state()
        self.log(f"guard {time.strftime('%FT%TZ', time.gmtime())} health {'ok' if ok else 'FAIL'} {dt:.2f} s, restart state {state!r}")
        if not ok or dt > PROBE_MAX_S or state != self.first:
            self.reason = self.reason or (f"health probe {dt:.2f} s > {PROBE_MAX_S} s" if dt > PROBE_MAX_S
                                          else f"restart state changed: {self.first!r} -> {state!r}")
            self.stop.set()

    def loop(self):
        while not self.stop.wait(60):
            self.probe()


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--url", required=True)
    a.add_argument("--model", required=True)
    a.add_argument("--restart-cmd", required=True)
    a.add_argument("--workers", type=int, default=2)
    o = a.parse_args()
    if o.workers > 2:
        raise SystemExit("at most 2 parallel requests (PREREG_Z11_3)")
    system = synth_qa.system_for(PAIRS)
    docs = jl(DATA / "kit4/documents500.jsonl")
    seen = defaultdict(list)  # every question a new one must differ from, per document
    for r in jl(DATA / "kit4/split/train.jsonl"):
        seen[r["meta"]["id"]].append(r["messages"][0]["content"])
    for c in jl(DATA / "kit4/probe/catalog.jsonl"):
        seen[c["id"].split("probe:", 1)[1]].append(c["question"])
    for q in jl(DATA / "secondary_questions.jsonl"):
        seen[q["doc"]].append(q["question"])
    q_path, ref_path, log_path = DATA / "z11_3_questions.jsonl", DATA / "z11_3_refs.jsonl", DATA / "z11_3_gen_log.jsonl"
    run_log = open(DATA / "z11_3_gen_run.log", "a", encoding="utf-8")

    def say(line):
        run_log.write(line + "\n")
        run_log.flush()
        print(line, flush=True)

    kept = defaultdict(list)
    for q in (jl(q_path) if q_path.exists() else []):
        kept[q["doc"]].append(q["question"])
    attempts = defaultdict(int)
    for r in (jl(log_path) if log_path.exists() else []):
        attempts[r["doc"]] += 1
    lock = threading.Lock()
    qf, rf, lf = (open(p, "a", encoding="utf-8") for p in (q_path, ref_path, log_path))
    guard = Guard(o.url, o.restart_cmd, say)
    if guard.stop.is_set():
        say(f"guard stops before the first request: {guard.reason}")
        sys.exit(3)
    threading.Thread(target=guard.loop, daemon=True).start()
    t0, stats = time.time(), defaultdict(int)
    say(f"start {time.strftime('%FT%TZ', time.gmtime())} workers {o.workers} model {o.model}")

    def one(d):
        if guard.stop.is_set():
            return d, None, None, "stopped by guard"
        try:
            return d, *synth_qa.ask(o.url, o.model, d["document"], system), None
        except Exception as e:  # noqa: BLE001 — counted; a failed request is not an attempt (not logged), asked again next pass
            return d, None, None, f"request failed: {type(e).__name__}"

    for pass_no in range(1, ATTEMPTS + 1):
        todo = [d for d in docs if len(kept[d["meta"]["id"]]) < PER_DOC and attempts[d["meta"]["id"]] < ATTEMPTS]
        if not todo or guard.stop.is_set():
            break
        say(f"pass {pass_no}: {len(todo)} documents")
        with cf.ThreadPoolExecutor(o.workers) as pool:
            for n, (d, pairs, finish, error) in enumerate(pool.map(one, todo), 1):
                doc = d["meta"]["id"]
                if error:
                    stats[error] += 1
                    continue
                reasons = []
                if pairs is None or finish != "stop":
                    reasons.append("no JSON answer" if finish == "stop" else f"finish_reason {finish}")
                with lock:
                    for p in pairs or []:
                        why = synth_qa.check(p, d["document"]) if isinstance(p, dict) else "format"
                        if not why and any(synth_qa.jaccard(p["question"], t) >= JACCARD_MAX for t in seen[doc] + kept[doc]):
                            why = "too close to an existing question"
                        if not why and len(kept[doc]) >= PER_DOC:
                            why = "document already has 2"
                        if why:
                            reasons.append(why)
                            continue
                        k = len(kept[doc]) + 1
                        qid = f"probe3:{doc}:{k}"
                        question = p["question"].strip()
                        kept[doc].append(question)
                        qf.write(json.dumps({"id": qid, "doc": doc, "question": question}, ensure_ascii=False) + "\n")
                        rf.write(json.dumps({"id": qid, "question": question, "reference": p["answer"].strip()
                                             + "\n\n--- document ---\n" + d["document"]}, ensure_ascii=False) + "\n")
                        stats["kept"] += 1
                    for why in reasons:
                        stats[why] += 1
                    attempts[doc] += 1
                    lf.write(json.dumps({"doc": doc, "pass": pass_no, "kept_now": len(kept[doc]), "reasons": reasons},
                                        ensure_ascii=False) + "\n")
                    for f in (qf, rf, lf):
                        f.flush()
                if n % 25 == 0:
                    say(f"pass {pass_no}: {n}/{len(todo)}, kept {stats['kept']}, {round(time.time() - t0)} s")
    report = {"documents": len(docs), "questions": sum(len(v) for v in kept.values()),
              "documents_with": {str(k): sum(1 for d in docs if len(kept[d["meta"]["id"]]) == k) for k in range(PER_DOC + 1)},
              "stats": dict(stats), "seconds": round(time.time() - t0), "generator": o.model,
              "prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
              "synth_qa_sha256": hashlib.sha256(open(DATA / "kit4/synth_qa.py", "rb").read()).hexdigest(),
              "stopped_by_guard": guard.reason if guard.stop.is_set() else None}
    json.dump(report, open(DATA / "z11_3_gen_report.json", "w"), indent=1)
    say(json.dumps(report))
    sys.exit(3 if guard.stop.is_set() else 0)


if __name__ == "__main__":
    main()

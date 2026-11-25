"""Z1 step 0b (25.11.2026, development probe on spent fresh4; PLAN_Z1_step0b.md): a <= 9B TEACHER reads the same gold paragraphs as
q1_read_v2.py, through a llama.cpp server (OpenAI-compatible /v1/chat/completions, streamed). Standard library only.
Identical to q1_read_v2.py: the system message, the read prompt, the 2 shots (--shots 2, as the base reads), the paragraphs read per
question (gold supporting titles in order), the fact parser and the output format {"id","type","reads":[{title,raw,triples,stats}]}.
Generation: temperature 0 (greedy), thinking off (chat_template_kwargs.enable_thinking = false), NO token cap; the same two loop
tests as q1_read_v2's LineLoop, checked on the streamed text every 16 chunks — on a loop the stream is closed and the read is marked
stopped_repetition. Questions in the order of the --ids file; resumable (ids already in OUT are skipped); --stop-at ISO stops at a
QUESTION boundary once the time is reached (a question is written whole or not at all).
usage: q1_read_teacher.py DEV.json OUT.jsonl --ids IDS.json --url http://127.0.0.1:PORT [--shots 2] [--stop-at 2026-11-25T20:45:00Z]"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d0_docs import FACT, PRED, SHOTS, SYSTEM  # noqa: E402

INV = {v: k for k, v in PRED.items()}
RELS = ", ".join(PRED.values())


def read_prompt(text, title):
    return (f"Text:\n{text}\n\nWrite every fact the text states about \"{title}\" as lines "
            f"relation(\"Subject\", \"Object\"). using only these relations: {RELS}. Nothing else.")


def looped(text):
    tail = text[-6000:]
    if any(tail[-L:] == tail[-2 * L:-L] == tail[-3 * L:-2 * L] for L in range(8, min(2000, len(tail) // 3) + 1)):
        return True
    c = {}
    for line in text.split("\n")[:-1]:
        line = line.strip()
        if line:
            c[line] = c.get(line, 0) + 1
            if c[line] >= 3:
                return True
    return False


def messages(text, title, shots):
    msgs = [{"role": "system", "content": SYSTEM}]
    for t_, x_, fx, _p in SHOTS[:shots]:
        msgs += [{"role": "user", "content": read_prompt(x_, t_)}, {"role": "assistant", "content": fx}]
    msgs.append({"role": "user", "content": read_prompt(text, title)})
    return msgs


def read(url, text, title, shots):
    body = {"messages": messages(text, title, shots), "temperature": 0, "stream": True,
            "chat_template_kwargs": {"enable_thinking": False}}          # no max_tokens / n_predict: no token cap
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    out, chunks, hit, t0 = "", 0, False, time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
            out += delta; chunks += 1
            if chunks % 16 == 0 and looped(out):
                hit = True
                break                                                       # closing the stream stops the generation
    dt = time.perf_counter() - t0
    return out.strip(), {"chunks": chunks, "seconds": round(dt, 4), "stopped_repetition": hit}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dev"); ap.add_argument("out")
    ap.add_argument("--ids", required=True); ap.add_argument("--url", required=True)
    ap.add_argument("--shots", type=int, default=2); ap.add_argument("--stop-at", default="")
    a = ap.parse_args()
    stop = datetime.fromisoformat(a.stop_at.replace("Z", "+00:00")) if a.stop_at else None
    dev = {x["_id"]: x for x in json.load(open(a.dev))}
    order = json.load(open(a.ids))
    done = set()
    try:
        done = {json.loads(l)["id"] for l in open(a.out)}
    except FileNotFoundError:
        pass
    with open(a.out, "a") as f:
        for i in order:
            if i in done:
                continue
            if stop and datetime.now(timezone.utc) >= stop:
                print(f"STOPPED at {i} (stop time {a.stop_at})", flush=True)
                return
            x = dev[i]
            ctxt = {t: " ".join(s) for t, s in x["context"]}
            reads = []
            for title in dict.fromkeys(t for t, _ in x["supporting_facts"]):
                if title not in ctxt:
                    continue
                txt, st = read(a.url, ctxt[title], title, a.shots)
                triples = [[s_, INV[p], o] for p, s_, o in FACT.findall(txt) if p in INV]
                reads.append({"title": title, "raw": txt, "triples": triples, "stats": st})
            f.write(json.dumps({"id": i, "type": x["type"], "reads": reads}, ensure_ascii=False) + "\n"); f.flush()
            print(i, len(reads), "paragraphs", round(sum(r["stats"]["seconds"] for r in reads), 1), "s", flush=True)
    print("complete", flush=True)


if __name__ == "__main__":
    main()

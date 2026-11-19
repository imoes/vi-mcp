"""G9b data (= g9_data.py with a different split: train < 2026-11-11, validation windows 2026-11-11 and 2026-11-12 written
separately and pooled, test >= 2026-11-13 unchanged). G9 data: the VI's own experiences (production copy of 16.11.2026, read-only) as worlds for symbolic regression of failure rules.
Only what is known BEFORE an action is a predictor (no error:, no surprise:, no duration — they come from the result):
  tool(E, t), topic(E, x) (one per topic tag), host(E, h), inst(E, i),
  prev_fail_tool(E)  the same instance's previous action with the same tool, within 1 h, failed,
  prev_fail_conv(E)  the previous action in the same conversation failed.
Target: failed(E) iff ok:no; ok:unknown is left out. Every value is replaced by a code (t1.., x1.., h1.., i1..) — the decode table stays
local (decode.json, never published). Time split: train < 2026-11-12, validation 2026-11-12, test >= 2026-11-13 (the cutoff T).
Worlds: train and validation cut into chunks of CHUNK consecutive experiences (lexicase cases); test kept as chunks too.
usage: g9_data.py PRODCOPY OUTDIR"""
import json, sqlite3, sys
from collections import Counter, defaultdict

db, out = sys.argv[1], sys.argv[2]
CHUNK, TOP = 100, 40  # notation.MAX_STATEMENTS = 500 per program: ~4 facts per experience
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
ONLY = __import__("os").environ.get("G9_INSTANCE")  # one instance only (G9 main: claude-code), so the instance is no predictor
rows = [r for r in c.execute("select id, ts, instance, conversation from object where kind='experience' order by ts").fetchall()
        if not ONLY or r[2] == ONLY]
tags = defaultdict(list)
for oid, tag in c.execute("select t.object_id, t.tag from tag t join object o on o.id = t.object_id where o.kind = 'experience'"):
    tags[oid].append(tag)

codes = {"tool": {}, "topic": {}, "host": {}, "inst": {}}


def code(kind, v):
    m = codes[kind]
    if v not in m:
        m[v] = f"{kind[0]}{len(m) + 1}"
    return m[v]


exps, last_tool, last_conv = [], {}, {}
for oid, ts, inst, conv in rows:
    tg = tags[oid]
    ok = next((t.split(":", 1)[1] for t in tg if t.startswith("ok:")), "unknown")
    tool = next((t.split(":", 1)[1] for t in tg if t.startswith("tool:")), None)
    if tool is None:
        continue
    t_sec = __import__("datetime").datetime.fromisoformat(ts).timestamp()
    key_t = (inst, tool)
    pf_tool = key_t in last_tool and t_sec - last_tool[key_t][0] <= 3600 and last_tool[key_t][1] == "no"
    pf_conv = conv is not None and conv in last_conv and last_conv[conv] == "no"
    if ok in ("yes", "no"):
        exps.append({"ts": ts, "inst": inst, "tool": tool, "topics": sorted({t.split(":", 1)[1] for t in tg if t.startswith("topic:")}),
                     "hosts": sorted({t.split(":", 1)[1] for t in tg if t.startswith("host:")}), "failed": ok == "no",
                     "pf_tool": pf_tool, "pf_conv": pf_conv})
    last_tool[key_t] = (t_sec, ok)
    if conv is not None:
        last_conv[conv] = ok

# frequent values only become constants (TOP per kind, counted on TRAIN only); rarer values -> one "other" code
TRAIN_END, VALID_DAYS, TEST_START = "2026-11-11", ["2026-11-11", "2026-11-12"], "2026-11-13"
train_rows = [e for e in exps if e["ts"] < TRAIN_END]
freq = {k: Counter() for k in ("tool", "topic", "host", "inst")}
for e in train_rows:
    freq["tool"][e["tool"]] += 1; freq["inst"][e["inst"]] += 1
    freq["topic"].update(e["topics"]); freq["host"].update(e["hosts"])
keep = {k: {v for v, _n in freq[k].most_common(TOP)} for k in freq}


def facts(e, eid):
    f = [f"tool({eid}, {code('tool', e['tool']) if e['tool'] in keep['tool'] else 'tother'})",
         f"inst({eid}, {code('inst', e['inst']) if e['inst'] in keep['inst'] else 'iother'})"]
    f += [f"topic({eid}, {code('topic', x)})" for x in e["topics"] if x in keep["topic"]]
    f += [f"host({eid}, {code('host', h)})" for h in e["hosts"] if h in keep["host"]]
    if e["pf_tool"]:
        f.append(f"prev_fail_tool({eid})")
    if e["pf_conv"]:
        f.append(f"prev_fail_conv({eid})")
    f.append(f"action({eid})")
    return f


MAX_FACTS = 450  # notation.MAX_STATEMENTS = 500 per program, rules included: a world over the cap made EVERY evaluation fail


def worlds(sel):
    """consecutive experiences, a new world when CHUNK experiences or MAX_FACTS facts would be exceeded"""
    out_w, fs, gold, n = [], [], [], 0
    for e in sel:
        eid = f"e{n}"
        f = facts(e, eid)
        if n and (n >= CHUNK or len(fs) + len(f) > MAX_FACTS):
            out_w.append({"facts": "\n".join(fs), "gold": gold, "n": n, "failed": len(gold)})
            fs, gold, n = [], [], 0
            eid = f"e{n}"; f = facts(e, eid)
        fs += f; n += 1
        if e["failed"]:
            gold.append(f"failed({eid})")
    if n:
        out_w.append({"facts": "\n".join(fs), "gold": gold, "n": n, "failed": len(gold)})
    return out_w


split = {"train": train_rows, "valid": [e for e in exps if VALID_DAYS[0] <= e["ts"] < TEST_START],
         "test": [e for e in exps if e["ts"] >= TEST_START]}
for d in VALID_DAYS:
    split[f"valid_{d}"] = [e for e in exps if e["ts"][:10] == d]
import os
os.makedirs(out, exist_ok=True)
summary = {}
for name, sel in split.items():
    w = worlds(sel)
    json.dump(w, open(f"{out}/{name}.json", "w"))
    summary[name] = {"experiences": len(sel), "failed": sum(e["failed"] for e in sel), "worlds": len(w),
                     "base_rate": round(sum(e["failed"] for e in sel) / max(1, len(sel)), 4)}
json.dump(codes, open(f"{out}/decode.json", "w"), indent=1)  # LOCAL ONLY — never published
json.dump({"constants": {"tool": sorted(set(codes["tool"].values()) | {"tother"}), "topic": sorted(codes["topic"].values()),
                         "host": sorted(codes["host"].values()), "inst": sorted(set(codes["inst"].values()) | {"iother"})},
           "summary": summary}, open(f"{out}/meta.json", "w"), indent=1)
print(json.dumps(summary, indent=1))

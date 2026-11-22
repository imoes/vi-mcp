"""Label validity check of Z7b (docs/PREREG_Z7B_WITHIN_ACTION.md, amendment): implicit adoption of shown vs held-back hints.

Usage: python scripts/z7b_label_placebo.py DB.sqlite OUT.json — a read-only COPY; never imports vi_mcp (opening may migrate).
The token rule is a copy of vi_mcp.intuition.distinctive_tokens / _hint_tokens (rel-0.70.12)."""
from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
from collections import defaultdict

_TOKEN = re.compile(r"(?:(?<![\w.-])~?/[\w.@-]+(?:/[\w.@-]+)+|(?<!\S)--?[a-zA-Z][\w-]{2,}(?:=\S+)?|\b[\w-]+\.(?:key|pem|conf|cfg|json|ya?ml|sh|py|service|toml|ini|env)\b)")
_TOKEN_STOP = frozenset({"--help", "--version", "/dev/null"})
WINDOW = 3
PREFIXES = ("insight:", "erkenntnis:", "rule:", "regel:", "skill:", "page:", "seite:")


def tokens(text):
    return frozenset(t.rstrip(".,;:)'\"") for t in _TOKEN.findall(text or "") if len(t) >= 5 and t not in _TOKEN_STOP)


def main(path, out):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    okyes = {r[0] for r in db.execute("SELECT object_id FROM tag WHERE tag = 'ok:yes'")}
    conv = defaultdict(list)
    for oid, ts, data, c in db.execute("SELECT id, ts, data, conversation FROM object WHERE kind = 'experience' AND mode = 'active' ORDER BY ts"):
        if c:
            d = json.loads(data)
            conv[c].append((oid, json.dumps(d.get("args") or {}, ensure_ascii=False), d, oid in okyes))
    need = {h for es in conv.values() for _o, _a, d, _k in es for h in ((d.get("before") or {}).get("shown") or []) + ((d.get("before") or {}).get("held_back") or [])}
    tok = {}
    idl = list(need)
    for i in range(0, len(idl), 500):
        ch = idl[i:i + 500]
        for oid, text, data in db.execute(f"SELECT id, text, data FROM object WHERE id IN ({','.join('?' * len(ch))})", ch):
            tok[oid] = tokens((text or "") + " " + str(json.loads(data).get("content") or "")[:4000])
    per_conv = defaultdict(lambda: {"shown": [0, 0], "held": [0, 0]})
    agree = [0, 0, 0]  # both, replica only, stored only
    for c, es in conv.items():
        for i, (oid, args, d, _ok) in enumerate(es):
            v = d.get("before") or {}
            nxt = [a for _o, a, _d, k in es[i + 1:i + 1 + WINDOW] if k]
            for arm, hs in (("shown", v.get("shown") or []), ("held", v.get("held_back") or [])):
                if arm == "shown" and "hold_probability" not in v:
                    continue  # compare only actions eligible for the hold-back (same period, same randomisation)
                for h in hs:
                    if not h.startswith(PREFIXES):
                        continue
                    t = tok.get(h, frozenset())
                    hit = any(x in a and x not in args for x in t for a in nxt)
                    per_conv[c][arm][0] += hit
                    per_conv[c][arm][1] += 1
                    if arm == "shown":
                        stored = h in (d.get("used") or [])
                        agree[0 if hit and stored else 1 if hit else 2 if stored else 0] += (hit or stored)
    def rates(keys):
        s = [sum(per_conv[k]["shown"][0] for k in keys), sum(per_conv[k]["shown"][1] for k in keys)]
        h = [sum(per_conv[k]["held"][0] for k in keys), sum(per_conv[k]["held"][1] for k in keys)]
        return s, h
    keys = [k for k in per_conv if per_conv[k]["shown"][1] or per_conv[k]["held"][1]]
    s, h = rates(keys)
    rr = (s[0] / s[1]) / (h[0] / h[1]) if h[0] and s[1] else float("nan")
    rng = random.Random(22112026)
    boot = []
    for _ in range(2000):
        b = [rng.choice(keys) for _ in keys]
        bs, bh = rates(b)
        if bh[0] and bs[1] and bh[1]:
            boot.append((bs[0] / bs[1]) / (bh[0] / bh[1]))
    boot.sort()
    rep = {"conversations": len(keys), "shown": {"adopted": s[0], "pairs": s[1], "rate": s[0] / s[1] if s[1] else None},
           "held_back": {"adopted": h[0], "pairs": h[1], "rate": h[0] / h[1] if h[1] else None},
           "risk_ratio": rr, "ci95": [boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot)) - 1]] if boot else None,
           "n_boot": len(boot), "replica_vs_stored": {"both": agree[0], "replica_only": agree[1], "stored_only": agree[2]}}
    rep["decision"] = "use signal" if rep["ci95"] and rep["ci95"][0] > 1 else "token commonness (CI includes 1)"
    json.dump(rep, open(out, "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

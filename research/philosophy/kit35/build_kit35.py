"""Kit 35 (22.11.2026, goal Z4): kit34 plus rows that rename seed names with SYNONYMS.
Diagnosis (run 34, p67ablate): the remaining P6/P7 errors occur only when a seed-shaped block carries ONE seed name replaced by a
near-synonym (writer for author, unchecked for unverified, confirmed_by for verified) — the model writes the seed's own word.
Kit34's renamed-seed rows (H12) used only semantically unrelated names (ledger, beacon, hosts …), so copying a MEANING-NEAR name
was never trained. Part H (R2-small) showed that training against a name's usual binding teaches reading the prompt.
  S  synonym-renamed seed blocks: a kollektiv 1.2.0 block (P1–P7) with 1 or 2 names (predicates, acts or acceptance states)
     replaced by a TRAIN synonym from syn35.json; variables and all other names unchanged (one factor); explain + write.
Synonyms are split per name with random.Random("kit35-syn-split"): 2 held out if the name has >= 5, else 1, drawn only from
synonyms that occur nowhere in kit34's training text (stage A and B); held-out synonyms never occur in training and form the test set SYN-HO (eval/syn_ho.jsonl: every block × every renamable name × every held-out
synonym, exactly one rename, explain task in the p67ablate prompt format). Diagnostic names (p67ablate, p5ablate, p67prefix) are
absent from syn35.json. Row seed 3512, training seed 42, hyperparameters as kit34.
usage: python3 build_kit35.py"""
import importlib.util, json, random, re, shutil, sys
from pathlib import Path
FT = Path(__file__).parent
sys.path.insert(0, str(FT))
sys.path.insert(0, "~/Dev/code/vi-mcp-router")
from clingo_object import notation as n  # noqa: E402
from clingo_object.clingo_prose import normal_rule  # noqa: E402
import rule_prose as rp  # noqa: E402

S = "<scratchpad>"
spec = importlib.util.spec_from_file_location("k120", S + "/src066/clingo_object/philosophy_kollektiv.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); PKG = mod.PACKAGE
SRC, OUT = FT / "kit34", FT / "kit35"
SYSTEM = "You are a member of an AI collective and work strictly by its philosophy."
N_S = 300   # per direction
IDENT = re.compile(r"\b([a-z][a-z0-9_]*)\b")
DEONTIC = {"obligatory", "forbidden", "may", "never"}

blocks, cur = {}, None
for line in PKG["seed"].split("\n"):
    if line.startswith("# P"):
        cur = line[2:].split()[0]; blocks[cur] = []
    elif line.strip() and cur:
        blocks[cur].append(line.strip())
seed_rules = {normal_rule(r) for b in blocks.values() for r in b if not r.startswith("never(")}
seed_names = {m for b in blocks.values() for r in b for m in IDENT.findall(r)} - DEONTIC

import keyword  # noqa: E402
_RAW = {k: v for k, v in json.loads((FT / "syn35.json").read_text()).items() if not k.startswith("_")}
KEYWORD_DROPPED = sorted(x for v in _RAW.values() for x in v if keyword.iskeyword(x))   # clingo-object is Python-like: no keywords
SYN = {k: [x for x in v if not keyword.iskeyword(x)] for k, v in _RAW.items()}
assert set(SYN) <= seed_names, set(SYN) - seed_names
split_rnd = random.Random("kit35-syn-split")
TRAIN, HELD = {}, {}
_BASE_TEXT = (SRC / "split/train.jsonl").read_text() + (SRC / "split/logic.train.jsonl").read_text()
UNSEEN = {s for v in SYN.values() for s in v if not re.search(rf"\b{s}\b", _BASE_TEXT)}
for name in sorted(SYN):
    syns = list(SYN[name])
    k = 2 if len(syns) >= 5 else 1
    pool = [s for s in syns if s in UNSEEN]   # held-out synonyms must never occur in kit34's training text
    held = split_rnd.sample(pool, min(k, len(pool)))
    HELD[name] = held
    TRAIN[name] = [s for s in syns if s not in held]
all_syn = {s for v in SYN.values() for s in v}
assert len(all_syn) == sum(len(v) for v in SYN.values()), "synonym lists must be disjoint"
assert not (all_syn & seed_names), all_syn & seed_names

EVAL_FORBIDDEN = set()
for f in sorted((SRC / "eval").glob("*.jsonl")):
    for l in open(f):
        e = json.loads(l)
        for t in [m["content"] for m in e.get("messages", [])] + [json.dumps(e.get("meta", {}))]:
            for x in re.split(r"\\n|\n", t):
                if "<=" in x:
                    try:
                        EVAL_FORBIDDEN.add(normal_rule(x.strip().strip('"')))
                    except Exception:  # noqa: BLE001
                        pass


def rename(rules, mp):
    return [IDENT.sub(lambda m: mp.get(m.group(1), m.group(1)), r) for r in rules]


def renamable(b):
    present = {m for r in blocks[b] for m in IDENT.findall(r)}
    return sorted(x for x in present if x in SYN)


def s_row(rnd):
    while True:
        b = rnd.choice(sorted(blocks))
        cands = renamable(b)
        if not cands:
            continue
        k = 1 if (rnd.random() < 0.6 or len(cands) < 2) else 2
        chosen = rnd.sample(cands, k)
        present = {m for r in blocks[b] for m in IDENT.findall(r)}
        mp = {}
        for c in chosen:
            opts = [s for s in TRAIN[c] if s not in present and s not in mp.values()]
            if not opts:
                break
            mp[c] = rnd.choice(opts)
        if len(mp) != k:
            continue
        rules = rename(blocks[b], mp)
        plain = [r for r in rules if not r.startswith("never(")]
        if any(normal_rule(r) in EVAL_FORBIDDEN for r in plain if normal_rule(r) not in seed_rules):
            continue
        code = "\n".join(rules)
        try:
            n.translate(code)
        except Exception:  # noqa: BLE001
            continue
        return code, rp.program(code), b, mp


def syn_ho():
    items = []
    for b in sorted(blocks):
        present = {m for r in blocks[b] for m in IDENT.findall(r)}
        for name in renamable(b):
            for s in HELD[name]:
                if s in present:
                    continue
                code = "\n".join(rename(blocks[b], {name: s}))
                n.translate(code)
                left = " ".join(re.sub(r"[_()<=&~,]", " ", code).split())
                items.append({"id": f"syn_ho:{b}:{name}:{s}", "set": "syn_ho",
                              "messages": [{"role": "system", "content": SYSTEM},
                                           {"role": "user", "content": f"Translate these clingo-object rules into plain English:\n{code}"}],
                              "meta": {"task": "explain_rules", "block": b, "renamed": name, "synonym": s, "code": code,
                                       "must_contain": s.replace("_", " "),
                                       "must_not_contain": None if re.search(rf"\b{name.replace('_', ' ')}\b", left) else name.replace("_", " ")}})
    return items


if __name__ == "__main__":
    rnd = random.Random(3512)
    rows, per_block, per_name = [], {}, {}
    for i in range(2 * N_S):
        code, prose, b, mp = s_row(rnd)
        per_block[b] = per_block.get(b, 0) + 1
        for c in mp:
            per_name[c] = per_name.get(c, 0) + 1
        rows.append((code, prose, "explain_rules" if i < N_S else "write_rules"))
    out_rows = []
    for code, prose, task in rows:
        user = (f"[EXPLAIN_RULES]\nTranslate these clingo-object rules into plain English:\n{code}" if task == "explain_rules"
                else f"[WRITE_RULES]\nWrite these rules in clingo-object notation:\n{prose}")
        out_rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                                      {"role": "assistant", "content": prose if task == "explain_rules" else code}],
                         "meta": {"task": task, "h14": "synonym_seed_block", "seed": 3512}})
    ho = syn_ho()
    # leakage guard: no held-out synonym in any training row
    train_text = "\n".join(json.dumps(r) for r in out_rows)
    leaks = [s for v in HELD.values() for s in v if re.search(rf"\b{s}\b", train_text)]
    assert not leaks, leaks
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT, ignore=shutil.ignore_patterns("out", "*.log", "*_answers.jsonl"))
    base = [json.loads(l) for l in open(SRC / "split/train.jsonl")]
    base_text = "\n".join(json.dumps(r) for r in base)
    base_leaks = sorted({s for v in HELD.values() for s in v if re.search(rf"\b{s}\b", base_text)})
    mixed = base + out_rows
    random.Random(352).shuffle(mixed)
    (OUT / "split/train.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in mixed), encoding="utf-8")
    (OUT / "eval" / "syn_ho.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ho), encoding="utf-8")
    (OUT / "syn_split.json").write_text(json.dumps({"train": TRAIN, "held_out": HELD}, indent=1))
    b = json.loads((OUT / "BUILD31.json").read_text())
    b["h14"] = {"rows_added_stage_a": len(out_rows), "per_block": per_block, "per_name": per_name, "stage_a_rows": len(mixed),
                "syn_ho_items": len(ho), "held_out_synonyms_seen_in_kit34_rows": base_leaks, "keyword_dropped": KEYWORD_DROPPED, "row_seed": 3512}
    (OUT / "BUILD31.json").write_text(json.dumps(b, indent=1, ensure_ascii=False))
    print(json.dumps(b["h14"]))
    for code, prose, task in rows[:2]:
        print(f"--- {task}\n{code}\n-> {prose}")
    print("--- SYN-HO example", json.dumps(ho[0]["meta"])[:400])

"""Z11-3 (docs/PREREG_Z11_3.md): a larger E1 edit test (forget by document) on new questions K answers correctly.

Usage (Z11_DATA set; answers come from `z11.py answer --arm K`):
  edit3.py order            → z11_3_order.json: every new question in seeded order, batches of 200 (z11_3_q_batch<b>.jsonl)
  edit3.py poolpack B       → blind blocks for batch B: one K before answer per question (the single-system pass), key apart
  edit3.py poolcount        → after a batch is graded: K-correct so far, whether the stop rule (>= 124) is met
  edit3.py split            → pool, seeded document split → z11_3_split.json, z11_3_q_after.jsonl, z11_3_q_F.jsonl
  edit3.py forget           → hardlink copy store_qa → store_e1 (disk guard), forget the F documents' sources there
  edit3.py compare          → text identity, restore → z11_3_compare.json
  edit3.py judgepack        → blind blocks: per question the before and E1 answers under seeded letters; key apart
  edit3.py score            → after every block is graded: forget, locality, restore, weights → z11_3_SCORE.json
  edit3.py cleanup          → delete store_e1 as soon as its answers exist
"""
import glob
import hashlib
import json
import math
import os
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import z11  # noqa: E402
from edit2 import clopper_pearson, sha, wrap  # noqa: E402  (the same interval, hash and text layout as Z11-2)

D = z11.DATA
FORGET_MIN, LOCALITY_MIN = 0.8, 0.9
BATCH, POOL_STOP, SIDE_MIN, POOL_BLOCK, FINAL_BLOCK = 200, 124, 30, 40, 20


def order():
    out = D / "z11_3_order.json"
    if out.exists():
        raise SystemExit("z11_3_order.json exists — the order is never redrawn")
    qs = z11.jl(D / "z11_3_questions.jsonl")
    ids = sorted((q["id"] for q in qs), key=lambda i: hashlib.sha256(f"z11-3:order:{i}".encode()).hexdigest())
    by = {q["id"]: q for q in qs}
    batches = [ids[i:i + BATCH] for i in range(0, len(ids), BATCH)]
    for b, part in enumerate(batches):
        z11.write_jl(D / f"z11_3_q_batch{b}.jsonl", [{"id": i, "question": by[i]["question"]} for i in part])
    json.dump({"questions": len(ids), "batches": [len(p) for p in batches], "questions_sha256": sha(D / "z11_3_questions.jsonl"),
               "refs_sha256": sha(D / "z11_3_refs.jsonl"), "order": ids}, open(out, "w"), indent=1)
    print(json.dumps({"questions": len(ids), "batches": [len(p) for p in batches]}))


def before_files():
    return sorted(glob.glob(str(D / "z11_3_answers_before*.jsonl")))


def before_answers():
    """The before answers, possibly from several answer processes (one file each); an id twice is an error."""
    out = {}
    for f in before_files():
        for r in z11.jl(f):
            if r["id"] in out:
                raise SystemExit(f"before answer {r['id']} twice")
            out[r["id"]] = r
    return out


def poolpack(b):
    qs = {q["id"]: q for q in z11.jl(D / "z11_3_questions.jsonl")}
    refs = {r["id"]: r["reference"] for r in z11.jl(D / "z11_3_refs.jsonl")}
    batch = [q["id"] for q in z11.jl(D / f"z11_3_q_batch{b}.jsonl")]
    ans = before_answers()
    missing = [i for i in batch if i not in ans]
    if missing:
        raise SystemExit(f"batch {b}: {len(missing)} before answers missing")
    key_file = D / "judge_z11_3_pool_KEY.jsonl"
    if key_file.exists() and set(batch) & {k["id"] for k in z11.jl(key_file)}:
        raise SystemExit(f"batch {b} is already packed")
    out_dir = D / "judge_z11_3_pool"
    out_dir.mkdir(exist_ok=True)
    key, blocks = [], {}
    for j, i in enumerate(batch):
        n = b * BATCH + j
        a = ans[i]
        item = {"n": n, "question": qs[i]["question"], "reference_and_document": refs[i],
                "answers": {"A": a["text"] + (" [BUDGET REACHED: answer incomplete]" if a["finish"] == "budget" else "")}}
        blocks.setdefault(n // POOL_BLOCK, []).append(item)
        key.append({"n": n, "id": i, "letters": {"A": "K_before"}})
    for blk, items in blocks.items():
        z11.write_jl(out_dir / f"block{blk}.jsonl", items)
    with open(D / "judge_z11_3_pool_KEY.jsonl", "a", encoding="utf-8") as fh:
        for k in key:
            fh.write(json.dumps(k) + "\n")
    print(json.dumps({"batch": b, "blocks": sorted(blocks), "questions": len(key)}))


def pool_grades():
    out = {}
    key = {k["n"]: k["id"] for k in z11.jl(D / "judge_z11_3_pool_KEY.jsonl")}
    for f in sorted(glob.glob(str(D / "judge_z11_3_pool/grades*.jsonl"))):
        for g in z11.jl(f):
            out[key[g["n"]]] = g["grades"]["A"]
    return out, key


def poolcount():
    g, key = pool_grades()
    c = Counter(g.values())
    print(json.dumps({"graded": len(g), "packed": len(key), "counts": dict(c), "stop_rule_met": c["correct"] >= POOL_STOP}))


def split():
    out_path = D / "z11_3_split.json"
    if out_path.exists():
        raise SystemExit("z11_3_split.json exists — the split is never redrawn")
    g, key = pool_grades()
    if len(g) != len(key):
        raise SystemExit(f"{len(g)} of {len(key)} packed questions graded — no split yet")
    qs = {q["id"]: q for q in z11.jl(D / "z11_3_questions.jsonl")}
    items = [{"id": i, "doc": qs[i]["doc"], "question": qs[i]["question"]} for i in sorted(g) if g[i] == "correct"]
    docs = sorted({x["doc"] for x in items})
    shuffled = docs[:]
    random.Random("z11-3:split").shuffle(shuffled)
    f_docs = sorted(shuffled[:math.ceil(len(docs) / 2)])
    for x in items:
        x["side"] = "F" if x["doc"] in set(f_docs) else "Kp"
    counts = dict(Counter(x["side"] for x in items))
    rows = z11.train_rows()
    rep = {"pool": len(items), "documents": len(docs), "F_documents": f_docs, "side_counts": counts,
           "runs_edit": min(counts.get("F", 0), counts.get("Kp", 0)) >= SIDE_MIN,
           "forget_sources": [r["source"] for r in rows if r["doc"] in set(f_docs)], "items": items,
           "pool_grades": dict(Counter(g.values())),
           "inputs": {"pool_key": sha(D / "judge_z11_3_pool_KEY.jsonl"),
                      "grades": {Path(f).name: sha(f) for f in sorted(glob.glob(str(D / "judge_z11_3_pool/grades*.jsonl")))},
                      "before_answers": {Path(f).name: sha(f) for f in before_files()}},
           "store_manifest_sha256": sha(D / "store_qa/manifest.json"),
           "store_revision": json.load(open(D / "store_qa/manifest.json"))["revision"]}
    json.dump(rep, open(out_path, "w"), indent=1, ensure_ascii=False)
    z11.write_jl(D / "z11_3_q_after.jsonl", [{"id": x["id"], "question": x["question"]} for x in items])
    z11.write_jl(D / "z11_3_q_F.jsonl", [{"id": x["id"], "question": x["question"]} for x in items if x["side"] == "F"])
    print(json.dumps({k: rep[k] for k in ("pool", "documents", "side_counts", "runs_edit", "store_revision")}
                     | {"forget_sources": len(rep["forget_sources"]), "split_sha256": sha(out_path)}))


def forget():
    from vi_mcp.knn_lm import Datastore
    rep = json.load(open(D / "z11_3_split.json"))
    if not rep["runs_edit"]:
        raise SystemExit("fewer than 30 questions on a side — no edit run (PREREG_Z11_3)")
    free = shutil.disk_usage(D).free
    if free < 3 * 2**30:
        raise SystemExit(f"disk guard: {free / 2**30:.2f} GiB free < 3 GiB — abort before the copy")
    manifest_before = sha(D / "store_qa/manifest.json")
    target = D / "store_z3e1"
    target.mkdir(mode=0o700)
    for p in (D / "store_qa").iterdir():  # hardlinks: the datastore never modifies a file in place (see edit2.forget)
        if p.is_file() and p.suffix != ".f32" and p.name != ".writer.lock":
            os.link(p, target / p.name)
    st = Datastore(target)
    before = st.view()["revision"]
    reason = "Z11-3 E1"
    for s in rep["forget_sources"]:
        st.forget(s, reason)
    view = st.view()
    out = {"revision_before": before, "revision_after": view["revision"], "forgotten_sources": len(rep["forget_sources"]),
           "live_sources_after": len(view["documents"]),
           "live_entries_after": sum(d["entries"] for d in view["documents"].values()),
           "tombstones_with_reason": sum(1 for t in view["tombstones"] if t["reason"] == reason),
           "store_qa_manifest_unchanged": sha(D / "store_qa/manifest.json") == manifest_before}
    json.dump(out, open(D / "z11_3_forget.json", "w"), indent=1)
    print(json.dumps(out))


def sides():
    rep = json.load(open(D / "z11_3_split.json"))
    return ([x["id"] for x in rep["items"] if x["side"] == "F"], [x["id"] for x in rep["items"] if x["side"] == "Kp"], rep)


def compare():
    F, Kp, rep = sides()
    before = before_answers()
    after = {r["id"]: r for r in z11.jl(D / "z11_3_answers_E1.jsonl")}
    rest = {r["id"]: r for r in z11.jl(D / "z11_3_answers_restore.jsonl")}
    out = {"restore_identical": sum(rest[i]["text"] == before[i]["text"] for i in F), "F": len(F),
           "restore_store_revision": next(iter(rest.values()))["store_revision"],
           "store_qa_manifest_unchanged": sha(D / "store_qa/manifest.json") == rep["store_manifest_sha256"],
           "E1": {"store_revision": next(iter(after.values()))["store_revision"],
                  "F_text_identical": sum(after[i]["text"] == before[i]["text"] for i in F),
                  "Kp": len(Kp), "Kp_text_identical": sum(after[i]["text"] == before[i]["text"] for i in Kp)}}
    out["restore_pass"] = out["restore_identical"] == out["F"]
    json.dump(out, open(D / "z11_3_compare.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def judgepack():
    F, Kp, rep = sides()
    q = {x["id"]: x for x in rep["items"]}
    refs = {r["id"]: r["reference"] for r in z11.jl(D / "z11_3_refs.jsonl")}
    answers = {"before": before_answers(), "E1": {r["id"]: r for r in z11.jl(D / "z11_3_answers_E1.jsonl")}}
    ids = sorted(F + Kp, key=lambda i: hashlib.sha256(f"z11-3:judge-order:{i}".encode()).hexdigest())
    out_dir = D / "judge_z11_3"
    out_dir.mkdir(exist_ok=True)
    key, blocks = [], {}
    for n, i in enumerate(ids):
        order_ = ["before", "E1"]
        random.Random("z11-3:judge:" + i).shuffle(order_)
        item = {"n": n, "question": q[i]["question"], "reference_and_document": refs[i],
                "answers": {"AB"[j]: answers[a][i]["text"] + (" [BUDGET REACHED: answer incomplete]"
                                                              if answers[a][i]["finish"] == "budget" else "")
                            for j, a in enumerate(order_)}}
        blocks.setdefault(n // FINAL_BLOCK, []).append(item)
        key.append({"n": n, "id": i, "side": q[i]["side"], "letters": {"AB"[j]: a for j, a in enumerate(order_)}})
    for b, items in blocks.items():
        z11.write_jl(out_dir / f"block{b}.jsonl", items)
        with open(out_dir / f"block{b}.txt", "w", encoding="utf-8") as fh:
            for it in items:
                fh.write(f"===== n={it['n']} =====\nQUESTION: {wrap(it['question'])}\nREFERENCE_AND_DOCUMENT:\n"
                         f"{wrap(it['reference_and_document'])}\n")
                for letter, text in it["answers"].items():
                    fh.write(f"--- ANSWER {letter} ---\n{wrap(text)}\n")
                fh.write("\n")
    z11.write_jl(D / "judge_z11_3_KEY.jsonl", key)
    print(json.dumps({"blocks": len(blocks), "questions": len(key), "key_sha256": sha(D / "judge_z11_3_KEY.jsonl")}))


def score():
    key = z11.jl(D / "judge_z11_3_KEY.jsonl")
    grades = {}
    for f in sorted((D / "judge_z11_3").glob("grades*.jsonl")):
        for g in z11.jl(f):
            grades[g["n"]] = g
    if len(grades) != len(key):
        raise SystemExit(f"{len(grades)} of {len(key)} questions graded — the key stays closed")
    F, Kp, rep = sides()
    cmp = json.load(open(D / "z11_3_compare.json"))
    weights = json.load(open(D / "z11_3_weights.json"))
    before_text = {i: r["text"] for i, r in before_answers().items()}
    after_text = {r["id"]: r["text"] for r in z11.jl(D / "z11_3_answers_E1.jsonl")}
    pool_g, _ = pool_grades()
    g = {k["id"]: {arm: grades[k["n"]]["grades"][letter] for letter, arm in k["letters"].items()} for k in key}
    wrong = sum(g[i]["E1"] == "wrong" for i in F)
    kept = sum(after_text[i] == before_text[i] or g[i]["E1"] == "correct" for i in Kp)
    # Named in the prereg, decides nothing: kept also when the after grade is not below the before grade of this pass.
    rank = {"wrong": 0, "partial": 1, "correct": 2}
    kept_lenient = sum(after_text[i] == before_text[i] or rank[g[i]["E1"]] >= rank[g[i]["before"]] for i in Kp)
    out = {"pool_pass_grades": {"F": dict(Counter(pool_g[i] for i in F)), "Kp": dict(Counter(pool_g[i] for i in Kp))},
           "before_grades_this_pass": dict(Counter(g[i]["before"] for i in g)),
           "restore": {"identical": cmp["restore_identical"], "F": cmp["F"], "pass": cmp["restore_pass"]},
           "weights": {"before": weights["before"], "after": weights["after"], "pass": weights["before"] == weights["after"]},
           "store_qa_manifest_unchanged": cmp["store_qa_manifest_unchanged"],
           "F": len(F), "F_grades": dict(Counter(g[i]["E1"] for i in F)), "forget_wrong_share": wrong / len(F),
           "forget_ci95": clopper_pearson(wrong, len(F)), "forget_pass": wrong / len(F) >= FORGET_MIN,
           "Kp": len(Kp), "Kp_kept": kept, "locality_share": kept / len(Kp), "locality_ci95": clopper_pearson(kept, len(Kp)),
           "locality_pass": kept / len(Kp) >= LOCALITY_MIN, "Kp_kept_lenient": kept_lenient,
           "Kp_text_identical": sum(after_text[i] == before_text[i] for i in Kp),
           "Kp_grades": dict(Counter(g[i]["E1"] for i in Kp)),
           "F_not_wrong": sorted(i for i in F if g[i]["E1"] != "wrong"),
           "Kp_not_kept": sorted(i for i in Kp if not (after_text[i] == before_text[i] or g[i]["E1"] == "correct"))}
    # Reported, deciding nothing (PREREG_Z11_3): the stricter lower-bound reading, the forget share among changed F answers,
    # and where the F answers that are not wrong now draw from.
    out["forget_lower_bound_clears"] = out["forget_ci95"][0] >= FORGET_MIN
    out["locality_lower_bound_clears"] = out["locality_ci95"][0] >= LOCALITY_MIN
    changed = [i for i in F if after_text[i] != before_text[i]]
    out["forget_wrong_share_changed_F"] = (sum(g[i]["E1"] == "wrong" for i in changed) / len(changed)) if changed else None
    after_rows = {r["id"]: r for r in z11.jl(D / "z11_3_answers_E1.jsonl")}
    out["F_not_wrong_nearest_documents"] = {i: after_rows[i]["nearest_documents"] for i in out["F_not_wrong"]}
    out["documents_per_side"] = {s: len({x["doc"] for x in rep["items"] if x["side"] == s}) for s in ("F", "Kp")}
    out["H6"] = out["forget_pass"] and out["locality_pass"] and out["restore"]["pass"] and out["weights"]["pass"]
    json.dump(out, open(D / "z11_3_SCORE.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def cleanup():
    F, Kp, _ = sides()
    p, a = D / "store_z3e1", D / "z11_3_answers_E1.jsonl"
    done = {r["id"] for r in z11.jl(a)} if a.exists() else set()
    if p.exists():
        shutil.rmtree(p)
    print(json.dumps({"deleted": p.name, "answers_complete": set(F + Kp) <= done,
                      "answers_sha256": sha(a) if a.exists() else None, "free_bytes": shutil.disk_usage(D).free}))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "poolpack":
        poolpack(int(sys.argv[2]))
    else:
        {"order": order, "poolcount": poolcount, "split": split, "forget": forget, "compare": compare,
         "judgepack": judgepack, "score": score, "cleanup": cleanup}[cmd]()

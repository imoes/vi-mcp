"""Z11-2 (docs/PREREG_Z11_2.md): the edit test on questions K answered correctly, forget by document (E1) and by provenance (E2).

Usage (Z11_DATA set; answers are produced by `z11.py answer --arm K`):
  edit2.py pool        → z11_2_split.json (pool, document split, input hashes, store manifest hash), z11_2_questions.jsonl
  edit2.py eligible    → after the before answers: host check, E2 forget set, collisions → z11_2_eligible.json,
                         z11_2_q_after.jsonl (eligible F + Kp), z11_2_q_F.jsonl (eligible F)
  edit2.py forget E1|E2 → hardlink copy store_qa → store_e1|store_e2 (disk guard), forget the variant's sources there
  edit2.py compare     → text identity, restore → z11_2_compare.json
  edit2.py judgepack   → blind blocks: per question the before, E1 and E2 answers under seeded letters; key apart
  edit2.py score       → after every block is graded: forget and locality per variant, verdicts → z11_2_SCORE.json
  edit2.py weights     → the weights hash now
  edit2.py cleanup     → delete store_e1 and store_e2 (after scoring)
"""
import glob
import hashlib
import json
import math
import os
import random
import shutil
import sys
import textwrap
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import z11  # noqa: E402

D = z11.DATA
VARIANTS = ("E1", "E2")
FORGET_MIN, LOCALITY_MIN, POWER_MIN = 0.8, 0.9, 15


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grades_of(key_file, grade_dir, arm):
    key = {k["n"]: k for k in z11.jl(key_file)}
    out = {}
    for f in sorted(glob.glob(str(grade_dir / "grades*.jsonl"))):
        for g in z11.jl(f):
            k = key[g["n"]]
            for letter, a in k["letters"].items():
                if a == arm:
                    out[k["id"]] = g["grades"][letter]
    return out


SOURCES = {  # name: (key, grade dir, judged answers, questions, references)
    "primary": (D / "judge_probe_KEY.jsonl", D / "judge_probe", D / "answers_K.jsonl", None, D / "judged/references_probe.jsonl"),
    "secondary": (D / "secondary/judge_secondary_KEY.jsonl", D / "secondary/judge_secondary", D / "secondary/answers_K.jsonl",
                  D / "secondary_questions.jsonl", D / "secondary_refs.jsonl"),
}


def questions_of(name):
    q = SOURCES[name][3]
    return {x["id"]: x for x in (z11.probe_questions() if q is None else z11.jl(q))}


def pool():
    out_path = D / "z11_2_split.json"
    if out_path.exists():
        raise SystemExit("z11_2_split.json exists — the split is never redrawn")
    items, inputs = [], {}
    for name, (key, gdir, answers, _, refs) in SOURCES.items():
        g = grades_of(key, gdir, "K")
        qs = questions_of(name)
        judged = {r["id"]: r for r in z11.jl(answers)}
        for i in sorted(x for x, v in g.items() if v == "correct"):
            items.append({"id": i, "set": name, "doc": qs[i]["doc"], "question": qs[i]["question"], "judged_text": judged[i]["text"]})
        inputs[name] = {"key": sha(key), "grades": {Path(f).name: sha(f) for f in sorted(glob.glob(str(gdir / "grades*.jsonl")))},
                        "answers": sha(answers), "references": sha(refs)}
    if len({x["id"] for x in items}) != len(items):
        raise SystemExit("duplicate question id across sets")
    docs = sorted({x["doc"] for x in items})
    rng = random.Random("z11-2:split")
    shuffled = docs[:]
    rng.shuffle(shuffled)
    f_docs = sorted(shuffled[:math.ceil(len(docs) / 2)])
    for x in items:
        x["side"] = "F" if x["doc"] in set(f_docs) else "Kp"
    rep = {"pool": len(items), "documents": len(docs), "F_documents": f_docs,
           "side_counts": dict(Counter(x["side"] for x in items)), "items": items, "inputs": inputs,
           "store_manifest_sha256": sha(D / "store_qa/manifest.json"),
           "store_revision": json.load(open(D / "store_qa/manifest.json"))["revision"]}
    json.dump(rep, open(out_path, "w"), indent=1, ensure_ascii=False)
    z11.write_jl(D / "z11_2_questions.jsonl", [{"id": x["id"], "question": x["question"]} for x in items])
    print(json.dumps({k: rep[k] for k in ("pool", "documents", "side_counts", "store_revision")} | {"split_sha256": sha(out_path)}))


def eligible():
    split = json.load(open(D / "z11_2_split.json"))
    before = {r["id"]: r for r in z11.jl(D / "z11_2_answers_before.jsonl")}
    missing = [x["id"] for x in split["items"] if x["id"] not in before]
    if missing:
        raise SystemExit(f"{len(missing)} before answers missing")
    elig, excluded = [], []
    for x in split["items"]:
        (elig if before[x["id"]]["text"] == x["judged_text"] else excluded).append(x)
    F = [x for x in elig if x["side"] == "F"]
    Kp = [x for x in elig if x["side"] == "Kp"]
    f_docs = sorted({x["doc"] for x in split["items"] if x["side"] == "F"})
    prov = sorted({d for x in F for d, _ in before[x["id"]]["nearest_documents"]})
    e2_docs = sorted(set(f_docs) | set(prov))
    collide = [x["id"] for x in Kp if x["doc"] in set(e2_docs)]
    rows = z11.train_rows()
    src = {v: [r["source"] for r in rows if r["doc"] in set(docs)] for v, docs in (("E1", f_docs), ("E2", e2_docs))}
    rep = {"eligible": len(elig), "excluded_host_difference": [{"id": x["id"], "side": x["side"]} for x in excluded],
           "F": [x["id"] for x in F], "Kp": [x["id"] for x in Kp],
           "forget_documents": {"E1": f_docs, "E2": e2_docs}, "forget_sources": src,
           "Kp_excluded_from_E2": collide,
           "counts": {"E1": {"F": len(F), "Kp": len(Kp)}, "E2": {"F": len(F), "Kp": len(Kp) - len(collide)}}}
    json.dump(rep, open(D / "z11_2_eligible.json", "w"), indent=1)
    by = {x["id"]: x for x in split["items"]}
    z11.write_jl(D / "z11_2_q_after.jsonl", [{"id": i, "question": by[i]["question"]} for i in rep["F"] + rep["Kp"]])
    z11.write_jl(D / "z11_2_q_F.jsonl", [{"id": i, "question": by[i]["question"]} for i in rep["F"]])
    print(json.dumps({"eligible": len(elig), "excluded_host_difference": len(excluded), "counts": rep["counts"],
                      "forget_documents": {v: len(d) for v, d in rep["forget_documents"].items()},
                      "forget_sources": {v: len(s) for v, s in src.items()}, "Kp_excluded_from_E2": len(collide)}))


def forget(variant):
    from vi_mcp.knn_lm import Datastore
    rep = json.load(open(D / "z11_2_eligible.json"))
    free = shutil.disk_usage(D).free
    if free < 3 * 2**30:
        raise SystemExit(f"disk guard: {free / 2**30:.2f} GiB free < 3 GiB — abort before the copy")
    manifest_before = sha(D / "store_qa/manifest.json")
    target = D / f"store_{variant.lower()}"
    target.mkdir(mode=0o700)
    # Hardlinks are safe: the datastore never modifies a file in place (forget unlinks shards, the manifest is replaced via a
    # temp file + os.replace), so store_qa keeps its content. The key cache (*.f32) is not linked; it is rebuilt per copy.
    for p in (D / "store_qa").iterdir():
        if p.is_file() and p.suffix != ".f32" and p.name != ".writer.lock":
            os.link(p, target / p.name)
    st = Datastore(target)
    before = st.view()["revision"]
    reason = f"Z11-2 {variant}"
    for s in rep["forget_sources"][variant]:
        st.forget(s, reason)
    view = st.view()
    out = {"variant": variant, "revision_before": before, "revision_after": view["revision"],
           "forgotten_sources": len(rep["forget_sources"][variant]), "live_sources_after": len(view["documents"]),
           "live_entries_after": sum(d["entries"] for d in view["documents"].values()),
           "tombstones_with_reason": sum(1 for t in view["tombstones"] if t["reason"] == reason),
           "store_qa_manifest_unchanged": sha(D / "store_qa/manifest.json") == manifest_before}
    json.dump(out, open(D / f"z11_2_forget_{variant}.json", "w"), indent=1)
    print(json.dumps(out))


def compare():
    rep = json.load(open(D / "z11_2_eligible.json"))
    before = {r["id"]: r for r in z11.jl(D / "z11_2_answers_before.jsonl")}
    rest = {r["id"]: r for r in z11.jl(D / "z11_2_answers_restore.jsonl")}
    split = json.load(open(D / "z11_2_split.json"))
    out = {"restore_identical": sum(rest[i]["text"] == before[i]["text"] for i in rep["F"]), "F": len(rep["F"]),
           "restore_store_revision": next(iter(rest.values()))["store_revision"],
           "store_qa_manifest_unchanged": sha(D / "store_qa/manifest.json") == split["store_manifest_sha256"]}
    out["restore_pass"] = out["restore_identical"] == out["F"]
    for v in VARIANTS:
        after = {r["id"]: r for r in z11.jl(D / f"z11_2_answers_{v}.jsonl")}
        kp = [i for i in rep["Kp"] if v == "E1" or i not in set(rep["Kp_excluded_from_E2"])]
        out[v] = {"store_revision": next(iter(after.values()))["store_revision"],
                  "F_text_identical": sum(after[i]["text"] == before[i]["text"] for i in rep["F"]),
                  "Kp": len(kp), "Kp_text_identical": sum(after[i]["text"] == before[i]["text"] for i in kp),
                  "Kp_changed": sorted(i for i in kp if after[i]["text"] != before[i]["text"])}
    json.dump(out, open(D / "z11_2_compare.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def wrap(text):
    return "\n".join(textwrap.fill(line, 180, break_long_words=True, replace_whitespace=False) if line else ""
                     for line in text.split("\n"))


def judgepack():
    rep = json.load(open(D / "z11_2_eligible.json"))
    split = {x["id"]: x for x in json.load(open(D / "z11_2_split.json"))["items"]}
    refs = {}
    for name, (*_, ref_file) in SOURCES.items():
        refs.update({r["id"]: r["reference"] for r in z11.jl(ref_file)})
    answers = {"before": {r["id"]: r for r in z11.jl(D / "z11_2_answers_before.jsonl")}}
    for v in VARIANTS:
        answers[v] = {r["id"]: r for r in z11.jl(D / f"z11_2_answers_{v}.jsonl")}
    ids = sorted(rep["F"] + rep["Kp"], key=lambda i: hashlib.sha256(f"z11-2:order:{i}".encode()).hexdigest())
    out_dir = D / "judge_z11_2"
    out_dir.mkdir(exist_ok=True)
    key, blocks = [], {}
    letters = "ABC"
    for n, i in enumerate(ids):
        order = ["before", *VARIANTS]
        random.Random("z11-2:judge:" + i).shuffle(order)
        item = {"n": n, "question": split[i]["question"], "reference_and_document": refs[i],
                "answers": {letters[j]: answers[a][i]["text"] + (" [BUDGET REACHED: answer incomplete]"
                                                                if answers[a][i]["finish"] == "budget" else "")
                            for j, a in enumerate(order)}}
        blocks.setdefault(n // 20, []).append(item)
        key.append({"n": n, "id": i, "side": split[i]["side"], "letters": {letters[j]: a for j, a in enumerate(order)}})
    for b, items in blocks.items():
        z11.write_jl(out_dir / f"block{b}.jsonl", items)
        with open(out_dir / f"block{b}.txt", "w", encoding="utf-8") as fh:
            for it in items:
                fh.write(f"===== n={it['n']} =====\nQUESTION: {wrap(it['question'])}\nREFERENCE_AND_DOCUMENT:\n"
                         f"{wrap(it['reference_and_document'])}\n")
                for letter, text in it["answers"].items():
                    fh.write(f"--- ANSWER {letter} ---\n{wrap(text)}\n")
                fh.write("\n")
    z11.write_jl(D / "judge_z11_2_KEY.jsonl", key)
    print(json.dumps({"blocks": len(blocks), "questions": len(key), "key_sha256": sha(D / "judge_z11_2_KEY.jsonl")}))


def clopper_pearson(k, n, alpha=0.05):
    def cdf(x, p):
        return sum(math.comb(n, i) * p**i * (1 - p)**(n - i) for i in range(x + 1))

    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2
    if n == 0:
        return [0.0, 1.0]
    lower = 0.0 if k == 0 else solve(lambda p: 1 - cdf(k - 1, p) < alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: cdf(k, p) > alpha / 2)
    return [round(lower, 4), round(upper, 4)]


def score():
    key = z11.jl(D / "judge_z11_2_KEY.jsonl")
    grades = {}
    for f in sorted((D / "judge_z11_2").glob("grades*.jsonl")):
        for g in z11.jl(f):
            grades[g["n"]] = g
    if len(grades) != len(key):
        raise SystemExit(f"{len(grades)} of {len(key)} questions graded — the key stays closed")
    rep = json.load(open(D / "z11_2_eligible.json"))
    cmp = json.load(open(D / "z11_2_compare.json"))
    weights = json.load(open(D / "z11_2_weights.json"))
    before_text = {r["id"]: r["text"] for r in z11.jl(D / "z11_2_answers_before.jsonl")}
    g = {}
    for k in key:
        g[k["id"]] = {arm: grades[k["n"]]["grades"][letter] for letter, arm in k["letters"].items()}
    out = {"before_grades": dict(Counter(g[i]["before"] for i in g)),
           "restore": {"identical": cmp["restore_identical"], "F": cmp["F"], "pass": cmp["restore_pass"]},
           "weights": {"before": weights["before"], "after": weights["after"], "pass": weights["before"] == weights["after"]},
           "store_qa_manifest_unchanged": cmp["store_qa_manifest_unchanged"]}
    for v in VARIANTS:
        after_text = {r["id"]: r["text"] for r in z11.jl(D / f"z11_2_answers_{v}.jsonl")}
        F = rep["F"]
        kp = [i for i in rep["Kp"] if v == "E1" or i not in set(rep["Kp_excluded_from_E2"])]
        wrong = sum(g[i][v] == "wrong" for i in F)
        not_correct = sum(g[i][v] != "correct" for i in F)
        kept = sum(after_text[i] == before_text[i] or g[i][v] == "correct" for i in kp)
        identical = sum(after_text[i] == before_text[i] for i in kp)
        forget_pass = bool(F) and wrong / len(F) >= FORGET_MIN
        locality_pass = bool(kp) and kept / len(kp) >= LOCALITY_MIN
        out[v] = {"F": len(F), "F_grades": dict(Counter(g[i][v] for i in F)),
                  "forget_wrong_share": wrong / len(F) if F else None, "forget_ci95": clopper_pearson(wrong, len(F)),
                  "forget_not_correct_share": not_correct / len(F) if F else None, "forget_pass": forget_pass,
                  "Kp": len(kp), "Kp_kept": kept, "locality_share": kept / len(kp) if kp else None,
                  "locality_ci95": clopper_pearson(kept, len(kp)), "Kp_text_identical": identical,
                  "Kp_grades": dict(Counter(g[i][v] for i in kp)), "locality_pass": locality_pass,
                  "F_not_wrong": sorted(i for i in F if g[i][v] != "wrong"),
                  "underpowered": len(F) < POWER_MIN or len(kp) < POWER_MIN,
                  "passes": forget_pass and locality_pass and out["restore"]["pass"] and out["weights"]["pass"]}
    out["H4_E1"] = out["E1"]["passes"]
    out["H5_E2"] = out["E2"]["passes"]
    json.dump(out, open(D / "z11_2_SCORE.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def weights():
    core = z11.load_core()
    print(json.dumps({"weights_sha256": core.identity["weights_sha256"]}))


def cleanup():
    for v in VARIANTS:
        p = D / f"store_{v.lower()}"
        if p.exists():
            shutil.rmtree(p)
            print(f"deleted {p.name}")
    print(json.dumps({"free_gib": round(shutil.disk_usage(D).free / 2**30, 2)}))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "forget":
        forget(sys.argv[2])
    else:
        {"pool": pool, "eligible": eligible, "compare": compare, "judgepack": judgepack, "score": score,
         "weights": weights, "cleanup": cleanup}[cmd]()

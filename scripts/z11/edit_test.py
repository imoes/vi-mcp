"""Z11-1 edit test (PREREG_Z11 "Edit test"): forget, locality, restore, weights hash, blind second pass.

F = the probe questions on which arm K was graded correct or partial in the primary blind pass. Every datastore source of F's
documents is forgotten (one `Datastore.forget` per source, reason "Z11 edit test", one batch); K then answers all 60 questions
again. The snapshot taken before answers the F questions again (restore). Answers are produced by `z11.py answer`.

Usage (Z11_DATA set):
  edit_test.py plan            → edit_F.json (F ids, documents, sources) and the weights hash before
  edit_test.py forget          → snapshot store_qa → store_snap, forget F's sources in store_qa → edit_forget.json
  edit_test.py compare         → locality and restore checks → edit_compare.json
  edit_test.py judgepack       → blind pass 2: F's edited answers + as many unedited K answers (seeded) → judge_edit/
  edit_test.py score           → after grades exist: share of F's edited answers graded wrong → edit_SCORE.json
  edit_test.py weights         → the weights hash now (compare with plan)
"""
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import z11  # noqa: E402
from vi_mcp.knn_lm import Datastore  # noqa: E402

D = z11.DATA
REASON = "Z11 edit test"


def primary_grades(arm):
    key = {k["n"]: k for k in z11.jl(D / "judge_probe_KEY.jsonl")}
    out = {}
    for f in sorted((D / "judge_probe").glob("grades*.jsonl")):
        for g in z11.jl(f):
            k = key[g["n"]]
            for letter, a in k["letters"].items():
                if a == arm:
                    out[k["id"]] = g["grades"][letter]
    return out


def weights_hash():
    core = z11.load_core()
    return core.identity["weights_sha256"]


def plan():
    grades = primary_grades("K")
    qs = {q["id"]: q for q in z11.probe_questions()}
    f_ids = sorted(i for i, g in grades.items() if g in ("correct", "partial"))
    docs = sorted({qs[i]["doc"] for i in f_ids})
    sources = [r["source"] for r in z11.train_rows() if r["doc"] in set(docs)]
    rep = {"F": f_ids, "F_grades": {i: grades[i] for i in f_ids}, "documents": docs, "sources": sources,
           "weights_sha256_before": weights_hash()}
    z11.write_jl(D / "edit_F_questions.jsonl", [{"id": i, "question": qs[i]["question"]} for i in f_ids])
    json.dump(rep, open(D / "edit_F.json", "w"), indent=1)
    print(json.dumps({"F": len(f_ids), "documents": len(docs), "sources": len(sources),
                      "weights_sha256_before": rep["weights_sha256_before"]}))


def forget():
    rep = json.load(open(D / "edit_F.json"))
    st = Datastore(D / "store_qa")
    before = st.view()["revision"]
    snap = st.snapshot(D / "store_snap")
    revs = [st.forget(s, REASON) for s in rep["sources"]]
    view = st.view()
    out = {"revision_before": before, "snapshot_revision": snap.view()["revision"], "revision_after": view["revision"],
           "forgotten_sources": len(revs), "live_sources_after": len(view["documents"]),
           "live_entries_after": sum(d["entries"] for d in view["documents"].values()),
           "tombstones_with_reason": sum(1 for t in view["tombstones"] if t["reason"] == REASON)}
    json.dump(out, open(D / "edit_forget.json", "w"), indent=1)
    print(json.dumps(out))


def compare():
    rep = json.load(open(D / "edit_F.json"))
    F = set(rep["F"])
    old = {r["id"]: r for r in z11.jl(D / "answers_K.jsonl")}
    new = {r["id"]: r for r in z11.jl(D / "answers_K_edit.jsonl")}
    rest = {r["id"]: r for r in z11.jl(D / "answers_K_restore.jsonl")}
    outside = [i for i in old if i not in F]
    same_out = [i for i in outside if new[i]["text"] == old[i]["text"]]
    same_F = [i for i in F if new[i]["text"] == old[i]["text"]]
    restored = [i for i in F if rest[i]["text"] == old[i]["text"]]
    out = {"outside_F": len(outside), "outside_F_identical": len(same_out),
           "locality_share": len(same_out) / len(outside), "locality_pass": len(same_out) / len(outside) >= 0.9,
           "outside_F_changed": sorted(set(outside) - set(same_out)),
           "F": len(F), "F_text_unchanged_after_forget": len(same_F),
           "restore_identical": len(restored), "restore_pass": len(restored) == len(F),
           "edited_store_revision": next(iter(new.values()))["store_revision"],
           "restore_store_revision": next(iter(rest.values()))["store_revision"]}
    json.dump(out, open(D / "edit_compare.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def judgepack():
    rep = json.load(open(D / "edit_F.json"))
    F = rep["F"]
    refs = {r["id"]: r for r in z11.jl(D / "judged/references_probe.jsonl")}
    qs = {q["id"]: q for q in z11.probe_questions()}
    new = {r["id"]: r for r in z11.jl(D / "answers_K_edit.jsonl")}
    old = {r["id"]: r for r in z11.jl(D / "answers_K.jsonl")}
    others = sorted(i for i in old if i not in set(F))
    rng = random.Random("z11:edit-control")
    control = rng.sample(others, min(len(F), len(others)))
    items = [("edited", i, new[i]) for i in F] + [("unedited", i, old[i]) for i in control]
    items.sort(key=lambda x: hashlib.sha256(f"z11:edit:{x[0]}:{x[1]}".encode()).hexdigest())
    out_dir = D / "judge_edit"
    out_dir.mkdir(exist_ok=True)
    block, key = [], []
    for n, (kind, i, r) in enumerate(items):
        text = r["text"] + (" [BUDGET REACHED: answer incomplete]" if r["finish"] == "budget" else "")
        block.append({"n": n, "question": qs[i]["question"], "reference_and_document": refs[i]["reference"], "answers": {"A": text}})
        key.append({"n": n, "id": i, "kind": kind})
    z11.write_jl(out_dir / "block0.jsonl", block)
    z11.write_jl(D / "judge_edit_KEY.jsonl", key)
    print(json.dumps({"items": len(items), "edited": len(F), "unedited_control": len(control)}))


def score():
    key = {k["n"]: k for k in z11.jl(D / "judge_edit_KEY.jsonl")}
    grades = {g["n"]: g["grades"]["A"] for g in z11.jl(D / "judge_edit/grades0.jsonl")}
    if set(grades) != set(key):
        raise SystemExit(f"{len(grades)} of {len(key)} graded — the key stays closed")
    from collections import Counter
    by = {kind: Counter(grades[n] for n, k in key.items() if k["kind"] == kind) for kind in ("edited", "unedited")}
    edited = sum(by["edited"].values())
    out = {"edited": dict(by["edited"]), "unedited_control": dict(by["unedited"]),
           "edited_wrong_share": by["edited"]["wrong"] / edited, "forget_pass": by["edited"]["wrong"] / edited >= 0.8}
    json.dump(out, open(D / "edit_SCORE.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "weights":
        print(json.dumps({"weights_sha256": weights_hash()}))
    else:
        {"plan": plan, "forget": forget, "compare": compare, "judgepack": judgepack, "score": score}[cmd]()

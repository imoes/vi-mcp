"""Z11-4 (docs/PREREG_Z11_4.md): can the store's provenance be read?

H7 (primary): from a per-token readout of a correct K answer, which document did the answer's knowledge come from?
H8 (secondary): an edit preview: masking a forget's sources in the neighbour search on the teacher-forced before answer predicts
whether the after answer stays text-identical and where it first diverges.

Usage (Z11_DATA set; one process, MemoryMax 6G, 4 threads):
  read4.py readout pilot|z11_2|z11_3  → z11_4_readout_<set>.jsonl: per item and token, the store readout and the edit preview.
                                        Contains no outcome: no grade, no after answer, no own document.
  read4.py rules                      → z11_4_rules.json: the mechanical readers M0, M1, M1s per item (no truth used)
  read4.py cards                      → judge_z11_4/card_block<b>.txt for blind readers; the key (labels, ids) in a separate file
  read4.py pilot_check                → the pilot's preview against its real after answers (mechanics check before the freeze)
  read4.py score                      → after every reader block is answered: H7 and H8 → z11_4_SCORE.json

The readout replays the before answer through the frozen model step by step, as generation did (KV cache), and every step uses
the generation path's own functions: Memory's exact distance expression and top-k, `Memory.distribution` and `interpolate`, with k,
temperature and weight from frozen_params.json. At each step the mixed argmax is taken while it stays consistent with the stored
text; that recovers the generated token ids. "reproduced" says the argmax never left the stored text and the token count matches.
"""
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import z11  # noqa: E402
from edit2 import clopper_pearson, sha  # noqa: E402

D = z11.DATA
CARD_ROWS_MIN_CREDIT = 0.01
BLOCK_CHARS = 110_000
H7_MIN = 0.8
H8_IDENTITY_MIN, H8_DIVERGENCE_MIN = 0.95, 0.9


def doc_of(source):
    return source.split("#")[0]


def sets():
    """Items, before answers and edits per set. Ids and questions only; no grade and no after answer."""
    out = {}
    s2 = json.load(open(D / "z11_2_split.json"))
    el = json.load(open(D / "z11_2_eligible.json"))
    b2 = {r["id"]: r for r in z11.jl(D / "z11_2_answers_before.jsonl")}
    out["z11_2"] = {"items": [{"id": x["id"], "question": x["question"]} for x in s2["items"]], "before": b2,
                    "edits": {"z11_2_E1": el["forget_sources"]["E1"], "z11_2_E2": el["forget_sources"]["E2"]}}
    s3 = json.load(open(D / "z11_3_split.json"))
    b3 = {}
    for f in sorted(D.glob("z11_3_answers_before_b*.jsonl")):
        for r in z11.jl(f):
            b3[r["id"]] = r
    out["z11_3"] = {"items": [{"id": x["id"], "question": x["question"]} for x in s3["items"]], "before": b3,
                    "edits": {"z11_3_E1": s3["forget_sources"]}}
    # pilot (mechanics only, before the freeze): two Z11-1 probe questions outside both sets, under the Z11-1 edit
    used = {x["id"] for x in s2["items"]}
    cmp1 = json.load(open(D / "edit_compare.json"))
    F1 = set(json.load(open(D / "edit_F.json"))["F"])
    b1 = {r["id"]: r for r in z11.jl(D / "answers_K.jsonl")}
    changed = sorted(i for i in cmp1["outside_F_changed"] if i not in used)
    same = sorted(i for i in b1 if i not in F1 and i not in used and i not in set(cmp1["outside_F_changed"]))
    qs = {q["id"]: q["question"] for q in z11.probe_questions()}
    pick = changed[:1] + same[:1]
    out["pilot"] = {"items": [{"id": i, "question": qs[i]} for i in pick], "before": b1,
                    "edits": {"z11_1_edit": json.load(open(D / "edit_F.json"))["sources"]}}
    return out


class Reader:
    def __init__(self):
        import torch
        self.torch = torch
        self.core = z11.load_core()
        self.params = json.load(open(D / "frozen_params.json"))
        self.mem = z11.Memory(D / "store_qa", identity=self.core.identity)
        self.vocab = self.core.identity["vocab_size"]
        self.eos = self.core.tokenizer.convert_tokens_to_ids(z11.EOS_TEXT)
        self.state = {}
        self.core.model.model.norm.register_forward_hook(lambda m, i, o: self.state.__setitem__("last", o))
        self.doc_index = [doc_of(s) for s in self.mem.sources]

    def masks(self, edits):
        """Per edit: the entries of its forgotten sources (as Memory.topk(exclude=...) masks them)."""
        out = {}
        for e, src in edits.items():
            idx = [self.mem.source_index[s] for s in src if s in self.mem.source_index]
            out[e] = self.torch.from_numpy(np.isin(self.mem.owner, idx))
        return out

    def search(self, state, k, masks):
        """Memory.topk's exact distance expression, computed once; each edit masks its sources to +inf before top-k."""
        torch, m = self.torch, self.mem
        q = torch.as_tensor(state[None])
        d = m.norms[None, :] - 2.0 * (q @ m.keys.T) + (q.double() ** 2).sum(1).float()[:, None]
        out = {}
        for e, mask in [(None, None)] + list(masks.items()):
            dd = d if mask is None else d.masked_fill(mask[None, :], float("inf"))
            vals, ind = torch.topk(dd, min(k, dd.shape[1]), dim=1, largest=False, sorted=True)
            out[e] = (vals.double().clamp_min(0).numpy()[0], ind.numpy()[0])
        return out

    def consistent(self, ids, text):
        """Do the generated ids so far decode to a prefix of the stored answer (which generation stripped)?"""
        dec = self.core.tokenizer.decode(ids, skip_special_tokens=True).rstrip("�").lstrip()
        return text.startswith(dec) or (dec.startswith(text) and not dec[len(text):].strip())

    def item(self, q, before, edits):
        """Incremental, as generation: at each step the mixed argmax is taken while it is consistent with the stored text, which
        recovers the generated token ids (re-encoding the text can split it differently). If the argmax leaves the text, that
        is a mismatch: the position is recorded and the rest of the text is forced in its own encoding."""
        torch, p = self.torch, self.params
        k, temp, wgt = p["k"], p["temperature"], p["weight"]
        text, finish, n_gen = before["text"], before["finish"], before["tokens"]
        prompt = z11.prompt_text(self.core, q["question"])
        rec = {"id": q["id"], "finish": finish, "nearest_documents": before["nearest_documents"]}
        masks = self.masks(edits)
        rows, out, cand = [], [], set()
        first_mismatch, tail = None, None
        pred = {e: None for e in edits}
        step, past = self.core.encode(prompt), None
        with torch.inference_mode():
            for t in range(z11.GEN_BUDGET + 1):
                o = self.core.model(input_ids=torch.tensor([step]), past_key_values=past, use_cache=True, return_dict=True,
                                    logits_to_keep=1)
                past = o.past_key_values
                logits = o.logits[0, -1].float().numpy()[:self.vocab]
                state = self.state["last"][0, -1].float().numpy()
                found = self.search(state, k, masks)
                dist, ind = found[None]
                pk = self.mem.distribution(dist, ind, k, temp, self.vocab)
                mixed, base = z11.interpolate(logits, pk, wgt)
                top = int(mixed.argmax())
                done = self.consistent(out, text) and self.core.tokenizer.decode(out, skip_special_tokens=True).strip() == text
                if tail is None:
                    if done and len(out) == n_gen:
                        if finish != "stop":
                            break
                        y = self.eos
                        if top != self.eos:
                            first_mismatch = t
                    elif top != self.eos and len(out) < n_gen and self.consistent(out + [top], text):
                        y = top
                    else:
                        first_mismatch = t
                        dec = self.core.tokenizer.decode(out, skip_special_tokens=True).lstrip()
                        tail = self.core.encode(text[len(dec):]) if text.startswith(dec) else []
                if tail is not None:
                    if tail:
                        y = tail.pop(0)
                    elif finish == "stop" and (not out or out[-1] != self.eos) and not (rows and rows[-1]["eos"]):
                        y = self.eos
                    else:
                        break
                d = dist[:k]
                w = np.exp(-(d - d[0]) / temp)
                w /= w.sum()
                credit = defaultdict(float)
                for wn, n in zip(w, ind[:k]):
                    doc = self.doc_index[int(self.mem.owner[int(n)])]
                    cand.add(doc)
                    if int(self.mem.tokens[int(n)]) == y:
                        credit[doc] += wgt * float(wn) / float(mixed[y])
                rows.append({"i": t, "tok": self.core.tokenizer.decode([y]), "eos": y == self.eos,
                             "pb": round(float(base[y]), 5), "pk": round(float(pk[y]), 5), "pm": round(float(mixed[y]), 5),
                             "S": int(base.argmax()) != y,
                             "credit": sorted(([dd, round(c, 4)] for dd, c in credit.items()), key=lambda x: -x[1])})
                for e in edits:
                    if pred[e] is None:
                        de, ie = found[e]
                        te = int(z11.interpolate(logits, self.mem.distribution(de, ie, k, temp, self.vocab), wgt)[0].argmax())
                        if te != y:
                            dec = self.core.tokenizer.decode(out, skip_special_tokens=True).lstrip()
                            piece = self.core.tokenizer.decode([y], skip_special_tokens=True).rstrip("\ufffd")
                            pred[e] = {"div": t, "char": len(dec), "width": max(1, len(piece)),
                                       "tok_before": self.core.tokenizer.decode([y]), "tok_after": self.core.tokenizer.decode([te])}
                if y == self.eos:
                    break
                out.append(y)
                step = [y]
        rec.update({"tokens": len(rows), "generated_tokens": n_gen, "reproduced": first_mismatch is None and len(out) == n_gen,
                    "first_mismatch": first_mismatch, "candidates": sorted(cand), "rows": rows,
                    "preview": {e: ({"identical": True} if v is None else {"identical": False, **v}) for e, v in pred.items()}})
        return rec


def readout(name):
    s = sets()[name]
    out = D / f"z11_4_readout_{name}.jsonl"
    done = {r["id"] for r in z11.jl(out)} if out.exists() else set()
    r = Reader()
    with open(out, "a", encoding="utf-8") as f:
        for q in s["items"]:
            if q["id"] in done:
                continue
            rec = r.item(q, s["before"][q["id"]], s["edits"])
            rec["set"] = name
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(q["id"], rec.get("tokens"), rec.get("reproduced"), {e: v.get("div") for e, v in rec.get("preview", {}).items()},
                  flush=True)


def readouts():
    rows = []
    for name in ("z11_2", "z11_3"):
        rows += z11.jl(D / f"z11_4_readout_{name}.jsonl")
    return rows


def rules():
    """Mechanical readers; no truth is read here."""
    out = {}
    for r in readouts():
        tot, tot_s = Counter(), Counter()
        for row in r.get("rows", []):
            for doc, c in row["credit"]:
                tot[doc] += c
                if row["S"]:
                    tot_s[doc] += c
        rank = lambda c: [d for d, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))][:3]
        out[r["id"]] = {"M0": [r["nearest_documents"][0][0]] if r["nearest_documents"] else [],
                        "M1": rank(tot), "M1s": rank(tot_s) or rank(tot),
                        "candidates": len(r.get("candidates", [])), "S_tokens": sum(x["S"] for x in r.get("rows", []))}
    json.dump(out, open(D / "z11_4_rules.json", "w"), indent=1)
    print(json.dumps({"items": len(out), "sha256": sha(D / "z11_4_rules.json")}))


INSTRUCTION = """Each card below shows one answer that a small language model generated while mixing in a token store. The store
holds entries written from training documents; every entry belongs to one document. Documents appear under labels that are
local to the card (D01, D02, ...): the same label on two cards is not the same document.

One row per generated token: position, the token (escaped), a mark S if the store decided this token (the model alone would
have chosen another token) or '.', then the documents whose store entries supplied probability for exactly this token, with
their share of the token's final probability (0-1; shares below 0.01 are not shown).

Task: for each card, name the three documents most likely to be the source of the knowledge in the answer, best first.
Write one JSON line per card to the output file named in your instructions: {"card": "<card id>", "top3": ["Dxx", "Dyy", "Dzz"]}
(fewer than three only if the card shows fewer documents)."""


def cards():
    rs = readouts()
    out_dir = D / "judge_z11_4"
    out_dir.mkdir(exist_ok=True)
    key, blocks, cur, size = [], [], [], 0
    order = sorted(rs, key=lambda r: hashlib.sha256(f"z11-4:order:{r['id']}".encode()).hexdigest())
    for r in order:
        if "rows" not in r:
            continue
        cid = hashlib.sha256(f"z11-4:card:{r['id']}".encode()).hexdigest()[:10]
        docs = sorted(r["candidates"], key=lambda d: hashlib.sha256(f"z11-4:label:{r['id']}:{d}".encode()).hexdigest())
        lab = {d: f"D{n + 1:02d}" for n, d in enumerate(docs)}
        lines = [f"=== card {cid} · {r['tokens']} tokens · {len(docs)} documents in the neighbour lists ==="]
        for row in r["rows"]:
            cr = ", ".join(f"{lab[d]} {c:.2f}" for d, c in row["credit"] if c >= CARD_ROWS_MIN_CREDIT) or "-"
            lines.append(f"{row['i']}\t{json.dumps(row['tok'], ensure_ascii=False)}\t{'S' if row['S'] else '.'}\t{cr}")
        text = "\n".join(lines) + "\n\n"
        if cur and size + len(text) > BLOCK_CHARS:
            blocks.append(cur)
            cur, size = [], 0
        cur.append(text)
        size += len(text)
        key.append({"card": cid, "id": r["id"], "labels": {v: d for d, v in lab.items()}, "block": len(blocks)})
    if cur:
        blocks.append(cur)
    for b, texts in enumerate(blocks):
        (out_dir / f"card_block{b}.txt").write_text(INSTRUCTION + "\n\n" + "".join(texts), encoding="utf-8")
    z11.write_jl(D / "judge_z11_4_KEY.jsonl", key)
    print(json.dumps({"cards": len(key), "blocks": len(blocks), "key_sha256": sha(D / "judge_z11_4_KEY.jsonl")}))


def char_div(before, after):
    """(identical, length of the common prefix of the two stored answer texts)."""
    if before["text"] == after["text"] and before["finish"] == after["finish"]:
        return True, None
    x, z = before["text"], after["text"]
    m = min(len(x), len(z))
    return False, next((i for i in range(m) if x[i] != z[i]), m)


def evaluable(r, pv):
    """A preview is evaluable when the readout reproduced the generation up to the predicted divergence (or everywhere)."""
    fm = r.get("first_mismatch")
    return fm is None if pv["identical"] else (fm is None or pv["div"] < fm)


def preview_rows(name, rows, after_by_edit):
    s = sets()[name]
    q = {x["id"]: x["question"] for x in s["items"]}
    res = []
    for r in rows:
        for e, pv in r.get("preview", {}).items():
            after = after_by_edit[e].get(r["id"])
            if after is None:
                continue
            ident, cp = char_div(s["before"][r["id"]], after)
            exact = (not pv["identical"]) and (not ident) and pv["char"] <= cp < pv["char"] + pv["width"]
            res.append({"id": r["id"], "edit": e, "evaluable": evaluable(r, pv), "pred_identical": pv["identical"],
                        "actual_identical": ident, "pred_div": pv.get("div"), "pred_char": pv.get("char"), "actual_char": cp,
                        "divergence_exact": exact})
    return res


def pilot_check():
    rows = z11.jl(D / "z11_4_readout_pilot.jsonl")
    res = preview_rows("pilot", rows, {"z11_1_edit": {r["id"]: r for r in z11.jl(D / "answers_K_edit.jsonl")}})
    out = {"rows": res, "reproduced": [r.get("reproduced") for r in rows], "first_mismatch": [r.get("first_mismatch") for r in rows],
           "tokens": [r.get("tokens") for r in rows]}
    json.dump(out, open(D / "z11_4_pilot_check.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def share(hits, n):
    return {"k": hits, "n": n, "share": hits / n if n else None, "ci95": list(clopper_pearson(hits, n)) if n else None}


def sign_test(a, b):
    """Exact two-sided sign test on discordant pairs (McNemar): a = only the first right, b = only the second right."""
    n = a + b
    if not n:
        return {"first_only": a, "second_only": b, "p": 1.0}
    tail = sum(math.comb(n, i) for i in range(0, min(a, b) + 1)) / 2 ** n
    return {"first_only": a, "second_only": b, "p": min(1.0, 2 * tail)}


def score():
    rs = {r["id"]: r for r in readouts()}
    rules_ = json.load(open(D / "z11_4_rules.json"))
    alt = json.load(open(D / "z11_4_alt_sources.json"))["rows"]
    own = {x["id"]: x["doc"] for f in ("z11_2_split.json", "z11_3_split.json") for x in json.load(open(D / f))["items"]}
    key = {k["card"]: k for k in z11.jl(D / "judge_z11_4_KEY.jsonl")}
    reader = {}
    for f in sorted((D / "judge_z11_4").glob("grades*.jsonl")):
        for g in z11.jl(f):
            k = key[g["card"]]
            reader[k["id"]] = [k["labels"].get(lbl) for lbl in g["top3"]]
    ids = sorted(own)
    pick = {"M0": {i: rules_[i]["M0"] if i in rules_ else rs.get(i, {}).get("nearest_documents", [[None]])[0][:1] for i in ids},
            "M1": {i: rules_.get(i, {}).get("M1", []) for i in ids},
            "M1s": {i: rules_.get(i, {}).get("M1s", []) for i in ids},
            "reader": {i: reader.get(i, []) for i in ids}}
    strict = {m: {i: bool(p[i]) and p[i][0] == own[i] for i in ids} for m, p in pick.items()}
    lenient = {m: {i: bool(p[i]) and p[i][0] in {own[i], *alt[i]["alt_documents"]} for i in ids} for m, p in pick.items()}
    top3 = {m: {i: own[i] in p[i][:3] for i in ids} for m, p in pick.items()}
    n = len(ids)
    h7 = {m: {"strict_top1": share(sum(strict[m].values()), n), "lenient_top1": share(sum(lenient[m].values()), n),
              "strict_top3": share(sum(top3[m].values()), n),
              "by_set": {s: share(sum(strict[m][i] for i in ids if i.startswith("probe3:") == (s == "z11_3")),
                                  sum(1 for i in ids if i.startswith("probe3:") == (s == "z11_3"))) for s in ("z11_2", "z11_3")}}
          for m in pick}
    cand = [rs[i]["candidates"] for i in ids if i in rs and "candidates" in rs[i]]
    h7["chance"] = {"mean_1_over_candidates": float(np.mean([1 / len(c) for c in cand])) if cand else None,
                    "candidates_median": float(np.median([len(c) for c in cand])) if cand else None, "global": 1 / 500}
    disc = lambda a, b: sign_test(sum(strict[a][i] and not strict[b][i] for i in ids), sum(strict[b][i] and not strict[a][i] for i in ids))
    h7["M1_vs_M0"] = disc("M1", "M0")
    h7["reader_vs_M1"] = disc("reader", "M1")
    h7["reader_answered"] = sum(1 for i in ids if reader.get(i))
    h7["rows_missing"] = sorted(i for i in ids if "rows" not in rs.get(i, {}))
    rule_ok, read_ok = h7["M1"]["strict_top1"]["share"] >= H7_MIN, h7["reader"]["strict_top1"]["share"] >= H7_MIN
    h7["decision"] = {(True, True): "provenance readable by rule and by the AI reader",
                      (True, False): "provenance readable by rule; the AI reader does not reach it from the cards",
                      (False, True): "the AI reader reads provenance better than the rule",
                      (False, False): "provenance as read here does not name the source at the threshold"}[(rule_ok, read_ok)]
    h7["H7_rule"], h7["H7_reader"] = rule_ok, read_ok
    # H8: preview vs real after answers
    after = {"z11_2_E1": {r["id"]: r for r in z11.jl(D / "z11_2_answers_E1.jsonl")},
             "z11_2_E2": {r["id"]: r for r in z11.jl(D / "z11_2_answers_E2.jsonl")},
             "z11_3_E1": {r["id"]: r for r in z11.jl(D / "z11_3_answers_E1.jsonl")}}
    pv = []
    for name in ("z11_2", "z11_3"):
        pv += preview_rows(name, [r for r in rs.values() if r["set"] == name and "rows" in r], after)
    rep = [p for p in pv if p["evaluable"]]
    agree = sum(p["pred_identical"] == p["actual_identical"] for p in rep)
    both = [p for p in rep if not p["pred_identical"] and not p["actual_identical"]]
    div_ok = sum(p["divergence_exact"] for p in both)
    h8 = {"pairs": len(pv), "pairs_evaluable": len(rep), "pairs_not_evaluable": len(pv) - len(rep),
          "identity_agreement_all_pairs": share(sum(p["pred_identical"] == p["actual_identical"] for p in pv), len(pv)),
          "identity_agreement": share(agree, len(rep)), "divergence_exact": share(div_ok, len(both)),
          "by_edit": {e: {"identity_agreement": share(sum(p["pred_identical"] == p["actual_identical"] for p in rep if p["edit"] == e),
                                                      sum(1 for p in rep if p["edit"] == e))}
                      for e in sorted({p["edit"] for p in pv})},
          "confusion": dict(Counter(f"pred_{'same' if p['pred_identical'] else 'changed'}|actual_{'same' if p['actual_identical'] else 'changed'}"
                                    for p in rep))}
    h8["H8"] = (h8["identity_agreement"]["share"] or 0) >= H8_IDENTITY_MIN and (h8["divergence_exact"]["share"] or 0) >= H8_DIVERGENCE_MIN
    # kept prediction on Z11-3 Kp (per-item kept known only there)
    s3 = json.load(open(D / "z11_3_split.json"))
    sc3 = json.load(open(D / "z11_3_SCORE.json"))
    fdocs = set(s3["F_documents"])
    kp = [x["id"] for x in s3["items"] if x["side"] == "Kp"]
    kept = {i: i not in set(sc3["Kp_not_kept"]) for i in kp}
    pvi = {p["id"]: p for p in pv if p["edit"] == "z11_3_E1"}
    nd = lambda i: any(d in fdocs for d, _ in rs[i]["nearest_documents"])
    preds = {"majority_kept": {i: True for i in kp}, "nearest_document_rule": {i: not nd(i) for i in kp},
             "preview_rule": {i: pvi[i]["pred_identical"] for i in kp if i in pvi}}
    h8["kept_prediction_z11_3_Kp"] = {m: share(sum(p[i] == kept[i] for i in p), len(p)) for m, p in preds.items()}
    # descriptive: the token at the real first divergence
    at = []
    for p in both:
        if p["divergence_exact"]:
            row = rs[p["id"]]["rows"][p["pred_div"]]
            fset = set(sets()[rs[p["id"]]["set"]]["edits"][p["edit"]])
            fd = {doc_of(x) for x in fset}
            at.append({"id": p["id"], "edit": p["edit"], "pos": p["pred_div"], "tok": row["tok"], "S": row["S"],
                       "pm": row["pm"], "pb": row["pb"], "pk": row["pk"],
                       "forgotten_credit": round(sum(c for d, c in row["credit"] if d in fd), 4)})
    h8["at_divergence"] = {"n": len(at), "S": sum(a["S"] for a in at),
                           "median_forgotten_credit": float(np.median([a["forgotten_credit"] for a in at])) if at else None,
                           "rows": at}
    out = {"H7": h7, "H8": h8, "preview_rows": pv}
    json.dump(out, open(D / "z11_4_SCORE.json", "w"), indent=1)
    print(json.dumps({"H7": {m: h7[m]["strict_top1"] if isinstance(h7[m], dict) and "strict_top1" in h7[m] else h7[m]
                             for m in h7}, "H8": {k: v for k, v in h8.items() if k != "at_divergence"}}, indent=1, default=str))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "readout":
        readout(sys.argv[2])
    elif cmd == "rules":
        rules()
    elif cmd == "cards":
        cards()
    elif cmd == "pilot_check":
        pilot_check()
    elif cmd == "score":
        score()
    else:
        raise SystemExit(__doc__)

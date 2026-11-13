"""Learning rules from rated conclusions — with clingo itself (concept C3, 13.11.2026; ILASP is free for non-commercial use only).

The examples are conclusions someone checked against reality: head("<object id>") was right (positive) or wrong (negative). The
hypothesis space is small on purpose (a mode bias, as in learning from answer sets, Law, Russo, Broda arXiv 2005.00904): a rule
    head(O) <= (O in objects(FILTER)) & (O.k1 == "v1") [& (O.k2 == "v2")]
with the literals taken from the fields and hashtags the positive objects carry. Which candidate covers which object is computed from the
object data (what grounding would do); clingo's optimisation then picks the smallest set of rules that covers the most positives and the
fewest negatives:
    {use(R)} :- rule(R).   derived(O) :- use(R), covers(R, O).
    :~ pos(O), not derived(O). [2@2, O]   :~ neg(O), derived(O). [2@2, O]   :~ use(R), len(R, L). [L@1, R]
A learned rule is returned as soft(…) notation with its prior = its precision on the training examples, and its coverage on held-out
examples — it is a proposal; the VI server holds it for a person to release. Pure (no memory, no network).
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from .expr import term

MAX_LITERALS = 12  # candidate literals (most frequent among the positives)
MAX_BODY = 2


def _literals(obj: dict) -> set[tuple[str, str]]:
    out = {("kind", obj["kind"])} if obj.get("kind") else set()
    if obj.get("mode"):
        out.add(("mode", obj["mode"]))
    for k, vals in (obj.get("tags") or {}).items():
        if k in ("instanz", "art", "serial", "tag"):
            continue  # who wrote it, or ids — never a reason
        out.update((k, v) for v in vals)
    return out


def learn(head: str, filter_text: str, data: dict, positives: list[str], negatives: list[str],
          held_pos: list[str] = (), held_neg: list[str] = ()) -> dict:
    """Rules for head(O) over the objects in `data` (logic.object_data / Memory.objects of filter_text)."""
    import clingo
    objs = {o["id"]: o for o in data["objects"]}
    pos = [p for p in positives if p in objs]
    neg = [n for n in negatives if n in objs]
    if not pos:
        return {"rules": [], "reason": "no positive example among the objects of the filter"}
    lits_of = {oid: _literals(o) for oid, o in objs.items()}
    freq = Counter(lit for p in pos for lit in lits_of[p])
    cands = [lit for lit, _n in freq.most_common(MAX_LITERALS)]
    rules = [body for k in range(1, MAX_BODY + 1) for body in combinations(cands, k)]
    covers = {i: {oid for oid in pos + neg + list(held_pos) + list(held_neg) if oid in objs and set(b) <= lits_of[oid]}
              for i, b in enumerate(rules)}
    prog = ["{use(R)} :- rule(R).", "derived(O) :- use(R), covers(R,O).",
            ":~ pos(O), not derived(O). [2@2,O]", ":~ neg(O), derived(O). [2@2,O]", ":~ use(R), len(R,L). [L@1,R]", "#show use/1."]
    train = set(pos) | set(neg)
    for i, b in enumerate(rules):
        prog.append(f"rule({i}). len({i},{len(b)}).")
        prog += [f"covers({i},{term(o)})." for o in covers[i] if o in train]
    prog += [f"pos({term(p)})." for p in pos] + [f"neg({term(n)})." for n in neg]
    ctl = clingo.Control(["--opt-mode=opt"])
    ctl.add("base", [], "\n".join(prog))
    ctl.ground([("base", [])])
    best: list[int] = []

    def on_model(m):
        best[:] = [s.arguments[0].number for s in m.symbols(shown=True)]
    ctl.solve(on_model=on_model)
    out = []
    for i in sorted(best):
        b = rules[i]
        tp, fp = len(covers[i] & set(pos)), len(covers[i] & set(neg))
        precision = tp / max(1, tp + fp)
        body = " & ".join(f"(O.{k} == {term(v)})" for k, v in b)
        prior = min(0.95, max(0.55, round(precision, 2)))
        text = f"soft({head}(O) <= (O in objects({term(filter_text)})) & {body}, {prior})"
        held = {"positives": len(covers[i] & set(held_pos)), "of_positives": len(held_pos),
                "negatives": len(covers[i] & set(held_neg)), "of_negatives": len(held_neg)}
        out.append({"rule": text, "train": {"positives": tp, "of_positives": len(pos), "negatives": fp, "of_negatives": len(neg)},
                    "held_out": held})
    covered = set().union(*(covers[i] for i in best)) if best else set()
    return {"rules": out, "candidates": len(rules),
            "train_covered": {"positives": len(covered & set(pos)), "of": len(pos), "negatives": len(covered & set(neg)), "of_neg": len(neg)},
            "held_covered": {"positives": len(covered & set(held_pos)), "of": len(held_pos),
                             "negatives": len(covered & set(held_neg)), "of_neg": len(held_neg)}}

"""v2 = official_score.py (sha 7f9170e9…) + --object-anchor (see below); nothing else changed.
Q1 pipeline answers scored three ways (added 21.11.2026 ~09:45 UTC after reading the official 2Wiki evaluator v1.1):
(a) ours  — q1_oracle.record: exactly one predicted value, q1_oracle.norm equal to the gold string;
(b) official, gold only — 2wikimultihop_evaluate_v1.1.py answer EM/F1 (SQuAD normalize_answer: lower, strip punctuation, drop
    a/an/the, collapse spaces; F1 0 for yes/no/noanswer unless equal) against the gold string;
(c) official with aliases — max EM and max F1 over {gold} ∪ aliases ∪ demonyms of answer_id (id_aliases.json), as the evaluator does.
A prediction with no single value (empty or several) is scored as the empty string in (b)/(c), wrong in (a).
Exploratory (named, not a registered metric): --tiebreak shortest — when several values are predicted and the shortest is contained
in every other (normalised), predict the shortest.
usage: official_score.py DEV.json READS.jsonl KIN DENOTE GENDER TEMPLATES_TRAIN DEV_IDS.json ID_ALIASES.json [--tiebreak shortest]"""
import collections
import json
import re
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys_argv = list(sys.argv)
sys.argv = [sys.argv[0]]
import q1_oracle as Q  # noqa: E402
import goal_templates as GT  # noqa: E402

TIE = "--tiebreak" in sys_argv
ANCHOR = "--title-anchor" in sys_argv
OBJ_ANCHOR = "--object-anchor" in sys_argv or "--object-backlink" in sys_argv
BACKLINK = "--object-backlink" in sys_argv
SUBSET = "--object-subset" in sys_argv
KINFILTER = "--kin-filter" in sys_argv
GROUNDED = "--grounded" in sys_argv
# --grounded (development lever 21.11.2026 ~22:36 UTC, development 400 only): a read fact of an entity relation (Q.ENTITY_RELS) is
# kept only if every name token of its object occurs in the paragraph the fact was read from (the reader may not invent a person).
# --kin-filter (development lever 21.11.2026 ~22:35 UTC, development 400 only): drop a read kin fact that contradicts what the pipeline
# already knows: mother(s, o) with o male or father(s, o) with o female (GENDER of the question: pronouns of the person's paragraph +
# name meanings), and father/mother/spouse/child/sibling(s, o) with o == s after normalisation (kin relations are irreflexive).
OBJ_ANCHOR = OBJ_ANCHOR or SUBSET
# --object-anchor (v2, development lever 21.11.2026 ~18:40 UTC, developed on the 400 DEVELOPMENT questions only): the object o of an
# entity relation (q1_oracle.ENTITY_RELS) that equals no context title is rewritten to the context title T that shares the most name
# tokens with it (same name_tokens / marks rule as the title anchor); no rewrite when two titles tie or none matches. A chain breaks
# when the reader writes "Alfonso VI" and the next paragraph is titled "Alfonso VI of Leon and Castile".
# --title-anchor (development lever, 21.11.2026 ~10:10 UTC, tuned on the 400 development questions only): a fact read from the
# paragraph titled T whose subject s differs from T is rewritten to subject T when s and T share a name token outside any "of …"
# phrase (tokens >= 3 letters, not of/the/and/von/de), and their number/roman tokens agree — the paragraph names its own entity by a
# longer form ("Stephen Ira Cohen" in "Steve Cohen"), while other people in it rarely share its personal name.
NAME_STOP = {"of", "the", "and", "von", "de", "van", "der", "sir", "king", "queen", "prince", "princess", "duke", "count", "countess",
             "lord", "lady", "saint", "st", "pope", "emperor", "empress", "duchess", "earl", "baron"}


def name_tokens(s):
    t = Q.norm(s).split()
    out, inof = set(), False
    for w in t:
        if w == "of":
            inof = True; continue
        if not inof and len(w) >= 3 and w not in NAME_STOP and not any(ch.isdigit() for ch in w) and w not in Q.ROMAN:
            out.add(w)
    return out


def marks(s):
    return {w for w in Q.norm(s).split() if any(ch.isdigit() for ch in w) or w in Q.ROMAN}


def anchor(fev_reads):
    out = []
    for rd in fev_reads:
        T = rd["title"]
        for s, p, o in rd["triples"]:
            if s != T and Q.norm(s) != Q.norm(T) and (name_tokens(s) & name_tokens(T)) and marks(s) == marks(T):
                s = T
            out.append([s, p, o])
    return out


def object_anchor(fev, titles):
    """--object-backlink (variant, same date, development only): a candidate title T is kept only if a fact read about T (subject T
    after the title anchor) names the subject s back (shared name token and equal marks) — a paragraph about the father names the child,
    a paragraph about the grandfather usually does not."""
    tnorm = {Q.norm(t) for t in titles}
    about = {}
    for s0, p0, o0 in fev:
        about.setdefault(Q.norm(s0), []).append(o0)
    out = []
    for s, p, o in fev:
        if p in Q.ENTITY_RELS and Q.norm(o) not in tnorm:
            no = name_tokens(o)
            ok = lambda T: (not BACKLINK) or any((name_tokens(x) & name_tokens(s)) and marks(x) == marks(s) for x in about.get(Q.norm(T), []))  # noqa: E731
            if SUBSET:  # --object-subset (third variant, development only): every name token of o occurs in T, equal marks, unique T
                cands = [(1, T) for T in titles if no and no <= name_tokens(T) and marks(o) == marks(T)]
                if len(cands) == 1:
                    o = cands[0][1]
                out.append([s, p, o]); continue
            cands = sorted(((len(no & name_tokens(T)), T) for T in titles if no & name_tokens(T) and marks(o) == marks(T) and ok(T)), reverse=True)
            if cands and (len(cands) == 1 or cands[0][0] > cands[1][0]):
                o = cands[0][1]
        out.append([s, p, o])
    return out


def normalize_answer(s):
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def f1(pred, gold):
    p, g = normalize_answer(pred), normalize_answer(gold)
    if p in ("yes", "no", "noanswer") and p != g:
        return 0.0
    if g in ("yes", "no", "noanswer") and p != g:
        return 0.0
    pt, gt = p.split(), g.split()
    common = collections.Counter(pt) & collections.Counter(gt)
    ns = sum(common.values())
    if ns == 0:
        return 0.0
    pr, rc = ns / len(pt), ns / len(gt)
    return 2 * pr * rc / (pr + rc)


def main():
    per_path = sys_argv[sys_argv.index("--per") + 1] if "--per" in sys_argv else None  # per-question results for the McNemar test
    a = [x for x in sys_argv[1:] if not x.startswith("--") and x != "shortest" and x != per_path]
    per_rows = []
    dev = {x["_id"]: x for x in json.load(open(a[0]))}
    reads = [json.loads(l) for l in open(a[1])]
    kin = Q.load_kin(a[2]); den = Q.load_denote(a[3], "typed"); Q.load_gender(a[4])
    matcher = GT.build(json.load(open(a[5])))
    ans_id = {x["_id"]: x["answer_id"] for x in json.load(open(a[6]))}
    aliases = {}
    for l in open(a[7]):
        r = json.loads(l); aliases[r["Q_id"]] = set(r["aliases"] + r["demonyms"])
    tot = collections.defaultdict(collections.Counter); flips = collections.defaultdict(list)
    for r in reads:
        x = dev[r["id"]]; typ = x["type"]
        if GROUNDED:
            ptext = {t: Q.norm(" ".join(sents)) for t, sents in x["context"]}
            kept_reads = []
            for rd in r["reads"]:
                para = " " + ptext.get(rd["title"], "") + " "
                tr = [t for t in rd["triples"] if t[1] not in Q.ENTITY_RELS or not Q.norm(t[2]).split()
                      or all(" " + w + " " in para for w in Q.norm(t[2]).split())]
                tot[typ]["grounded_dropped"] += len(rd["triples"]) - len(tr)
                kept_reads.append(dict(rd, triples=tr))
            r = dict(r, reads=kept_reads)
        fev = anchor(r["reads"]) if ANCHOR else [t for rd in r["reads"] for t in rd["triples"]]
        if OBJ_ANCHOR:
            fev = object_anchor(fev, [t for t, _ in x["context"]])
        if KINFILTER:
            gen = {Q.norm(k): v for k, v in Q.GENDER.get(x["question"], {}).items()}
            keep = []
            for s_, p_, o_ in fev:
                if p_ in Q.BASE and Q.norm(o_) == Q.norm(s_):
                    tot[typ]["kin_filter_self"] += 1; continue
                if (p_ == "mother" and gen.get(Q.norm(o_)) == "male") or (p_ == "father" and gen.get(Q.norm(o_)) == "female"):
                    tot[typ]["kin_filter_gender"] += 1; continue
                keep.append([s_, p_, o_])
            fev = keep
        mg = matcher(x["question"])
        goal = GT.skeleton(mg[0], GT.resolve(mg[1], fev)) if mg else None
        res = collections.defaultdict(collections.Counter); w = collections.defaultdict(list)
        pred = Q.answer(x, fev, goal, kin, den, "typed", res, w) if goal is not None else None
        pred = pred or []
        if TIE and len(pred) > 1:
            s = min(pred, key=lambda v: len(Q.norm(v)))
            if all(Q.norm(s) in Q.norm(v) for v in pred):
                pred = [s]
        p = pred[0] if len(pred) == 1 else ""
        gold = x["answer"]; golds = {gold} | (aliases.get(ans_id.get(r["id"]), set()))
        ours = len(pred) == 1 and Q.norm(pred[0]) == Q.norm(gold)
        em_g = float(normalize_answer(p) == normalize_answer(gold)); f1_g = f1(p, gold)
        em_a = max(float(normalize_answer(p) == normalize_answer(g)) for g in golds); f1_a = max(f1(p, g) for g in golds)
        for k in (typ, "ALL"):
            c = tot[k]; c["n"] += 1; c["ours"] += ours; c["em_gold"] += em_g; c["em_alias"] += em_a
            c["f1_gold_x1000"] += int(1000 * f1_g); c["f1_alias_x1000"] += int(1000 * f1_a)
        per_rows.append({"id": r["id"], "type": typ, "pred": p, "ours": bool(ours), "em_alias": em_a, "f1_alias": round(f1_a, 4)})
        if em_a and not ours and len(flips[typ]) < 6:
            flips[typ].append({"q": x["question"], "gold": gold, "pred": p})
        if ours and not em_a and len(flips["lost:" + typ]) < 6:
            flips["lost:" + typ].append({"q": x["question"], "gold": gold, "pred": p})
    out = {k: {"n": c["n"], "ours_em": round(c["ours"] / c["n"], 4), "official_em_gold": round(c["em_gold"] / c["n"], 4),
               "official_em_alias": round(c["em_alias"] / c["n"], 4), "official_f1_gold": round(c["f1_gold_x1000"] / 1000 / c["n"], 4),
               "official_f1_alias": round(c["f1_alias_x1000"] / 1000 / c["n"], 4)} for k, c in sorted(tot.items())}
    if per_path:
        with open(per_path, "w") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in per_rows)
    print(json.dumps({"tiebreak": TIE, "title_anchor": ANCHOR, "object_anchor": OBJ_ANCHOR, "scores": out, "examples": flips}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

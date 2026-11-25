"""Pipeline steps between the readers and the solver (22.11.2026, development on fresh2 — fresh2 is spent for PREREG_R3r, so it
serves as development data here; a confirmation needs a set nobody has looked at).
  pref : union of a PRIMARY reader (the fine-tuned R3r) and a SECONDARY one (base 2-shot) in which a secondary triple is dropped when
         the primary read already gives the same relation for a subject sharing a token — the union's extra recall is kept where the
         primary is silent, its extra conflicts (fresh3: 18.9 % vs 11.3 %) are not added where the primary has a value.
  snap : every object that occurs in its paragraph neither as normalised tokens nor as a character substring (dates glued to a
         footnote digit, "19028") and is not "unknown" is replaced — name relations only (countries, occupations, dates, awards, genres are normalised on purpose) — by the paragraph span of the same token
         length (±1) with the highest difflib ratio, if that ratio is >= 0.8 — a 0.6B copy error ("Brautat Collett Paus" for
         "Brita Collett Paus") becomes the written form again; an object with no close span is kept unchanged.
usage: reader_merge.py pref PRIMARY SECONDARY OUT
       reader_merge.py snap DEV.json READS OUT"""
import difflib
import json
import re
import sys


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


def pref(primary, secondary, out):
    A, B = load(primary), load(secondary)
    assert set(A) == set(B)
    dropped = kept = 0
    with open(out, "w") as f:
        for i, a in A.items():
            have = [(set(norm(s)), p) for rd in a["reads"] for s, p, o in rd["triples"]]
            reads = list(a["reads"])
            for rd in B[i]["reads"]:
                tr = []
                for s, p, o in rd["triples"]:
                    if any(p == p2 and set(norm(s)) & s2 for s2, p2 in have):
                        dropped += 1
                    else:
                        tr.append([s, p, o]); kept += 1
                reads.append(dict(rd, triples=tr))
            f.write(json.dumps(dict(a, reads=reads), ensure_ascii=False) + "\n")
    print(json.dumps({"mode": "pref", "secondary_dropped": dropped, "secondary_kept": kept}))


NO_SNAP = ("country", "occupation", "date", "publication", "inception", "award", "genre")  # normalised on purpose (demonyms, dates)


def snap(dev_path, reads_path, out):
    dev = {q["_id"]: q for q in json.load(open(dev_path))}
    R = load(reads_path)
    changed = total = 0
    examples = []
    with open(out, "w") as f:
        for i, r in R.items():
            ctx = {" ".join(norm(t)): " ".join(x) for t, x in dev[i]["context"]}
            new_reads = []
            for rd in r["reads"]:
                para = ctx.get(" ".join(norm(rd["title"])), "")
                words = para.split()
                ptoks = " " + " ".join(norm(para)) + " "
                tr = []
                for s, p, o in rd["triples"]:
                    total += 1
                    t = norm(o)
                    if (any(w in p for w in NO_SNAP) or not t or (" " + " ".join(t) + " ") in ptoks or not words or o.lower() in para.lower()
                            or o.lower() in ("unknown", "none")):
                        tr.append([s, p, o]); continue
                    best, br = None, 0.0
                    for n in {max(1, len(o.split()) - 1), len(o.split()), len(o.split()) + 1}:
                        for k in range(0, max(0, len(words) - n) + 1):
                            span = re.sub(r"^[^\w]+|[^\w]+$", "", " ".join(words[k:k + n]))
                            rr = difflib.SequenceMatcher(None, o.lower(), span.lower()).ratio()
                            if rr > br:
                                best, br = span, rr
                    if best and br >= 0.8 and best != o:
                        changed += 1
                        if len(examples) < 25:
                            examples.append([o, best, round(br, 3)])
                        tr.append([s, p, best])
                    else:
                        tr.append([s, p, o])
                new_reads.append(dict(rd, triples=tr))
            f.write(json.dumps(dict(r, reads=new_reads), ensure_ascii=False) + "\n")
    print(json.dumps({"mode": "snap", "triples": total, "changed": changed, "examples": examples}, ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1] == "pref":
        pref(*sys.argv[2:5])
    else:
        snap(*sys.argv[2:5])

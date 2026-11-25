"""Kit R3r (21.11.2026) = build_r1.py (demonym version of 21.11 00:33) with three changes: READ rows only (no write rows), every
paragraph (no --max-rows sample), and KIN-CONTRAST rows: a paragraph whose stated facts hold at least two of father, mother,
spouse, child, sibling is written twice more (readers confuse kin roles: dev conflicts up to 33/52 for mother). Rule tasks are
not part of this kit (father as a rule target may cost father reading — kit R2: 83 -> 53/97).
Original docstring follows.
Kit R1 (20.11.2026): read (paragraph → facts) and write (facts → text) for Qwen3-0.6B, with COMPLETE and TEXT-FAITHFUL targets.
Targets: every Wikidata claim of the paragraph's entity (34 relations of 2WikiMultiHopQA) whose value is STATED in the paragraph
(copy rule: one surface form of the value — label, alias or a date rendering — occurs in the normalised paragraph text). The object
is written as it appears in the text. Lesson of GraphNarrative / the 2Wiki coverage count: incomplete or unstated targets teach
omission or invention.
Rows (prompts byte-identical to d0_docs.py, so the trained model is measured zero-shot against the D0 baseline):
  read : user = read_prompt(paragraph, entity)      assistant = the stated facts, one per line, relation("Subject", "Object").
  write: user = write_prompt(facts)                 assistant = one templated sentence per fact (faithful by construction)
Held out: every entity of the D0 items (d0_2shot.jsonl) and every dev paragraph.
usage: build_r1.py WIKI_DIR KIT_OUT [--max-rows N]   (WIKI_DIR holds data/train.json, qids.jsonl, claims.jsonl, labels.jsonl, props.json, d0_2shot.jsonl)"""
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from d0_docs import PRED, SYSTEM, norm  # noqa: E402
import unicodedata  # noqa: E402


def tnorm(s):
    """normalise paragraph text WITHOUT dropping parentheses (d0_docs.norm drops "(film)" from titles — but Wikipedia puts the
    life dates in parentheses: "Bob Friend, MBE( 20 January 1938 – 8 October 2008)")."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
TEMPLATE = {"date_of_birth": "{s} was born on {o}.", "date_of_death": "{s} died on {o}.", "place_of_birth": "{s} was born in {o}.",
            "place_of_death": "{s} died in {o}.", "father": "The father of {s} is {o}.", "mother": "The mother of {s} is {o}.",
            "spouse": "{s} was married to {o}.", "child": "{o} is a child of {s}.", "sibling": "{o} is a sibling of {s}.",
            "director": "{s} was directed by {o}.", "publication_date": "{s} was published on {o}.",
            "country_of_citizenship": "{s} was a citizen of {o}.", "country_of_origin": "{s} comes from {o}.", "country": "{s} is in {o}.",
            "educated_at": "{s} was educated at {o}.", "occupation": "{s} worked as {o}.", "place_of_burial": "{s} is buried in {o}.",
            "employer": "{s} worked for {o}.", "award_received": "{s} received the {o}.", "cause_of_death": "{s} died of {o}.",
            "founded_by": "{s} was founded by {o}.", "inception": "{s} was founded in {o}.", "performer": "{s} was performed by {o}.",
            "composer": "{s} was composed by {o}.", "producer": "{s} was produced by {o}.", "publisher": "{s} was published by {o}.",
            "creator": "{s} was created by {o}.", "has_part": "{s} has the part {o}.", "editor": "{s} was edited by {o}.",
            "presenter": "{s} is presented by {o}.", "manufacturer": "{s} is made by {o}.", "student_of": "{s} studied under {o}.",
            "doctoral_advisor": "The doctoral advisor of {s} is {o}.", "record_label": "{s} was released on {o}."}


def date_forms(t):
    """'+1869-05-03T00:00:00Z/11' → surface forms by precision (11 day, 10 month, 9 year)."""
    m = re.match(r"([+-])(\d+)-(\d\d)-(\d\d)T.*?/(\d+)", t)
    if not m or m.group(1) == "-":
        return []
    y, mo, d, prec = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    forms = [str(y)]
    if prec >= 10 and mo:
        forms = [f"{MONTHS[mo - 1]} {y}"] + forms
    if prec >= 11 and mo and d:
        forms = [f"{MONTHS[mo - 1]} {d}, {y}", f"{d} {MONTHS[mo - 1]} {y}"] + forms
    return forms


def entity(title):
    return re.sub(r"\s*\(.*?\)\s*$", "", title).strip()


def main():
    wiki, out = Path(sys.argv[1]), Path(sys.argv[2])
    max_rows = int(sys.argv[sys.argv.index("--max-rows") + 1]) if "--max-rows" in sys.argv else 0
    rnd = random.Random(20)
    pid2pred = {v["pid"]: PRED[k] for k, v in json.load(open(wiki / "props.json")).items()}
    qid = {r["title"]: r["qid"] for r in map(json.loads, open(wiki / "qids.jsonl")) if r["qid"]}
    claims = {r["qid"]: r["claims"] for r in map(json.loads, open(wiki / "claims.jsonl"))}
    labels = {r["qid"]: [x for x in [r["label"], *r["aliases"]] if x] for r in map(json.loads, open(wiki / "labels.jsonl"))}
    # demonyms (Wikidata P1549) count as surface forms of a country value: Wikipedia writes "an American actor", the label is
    # "United States of America" — without them 84 % of citizenship facts were missing from the R1 targets (20.11.2026)
    demonyms = {}
    if (wiki / "demonyms.jsonl").exists():
        demonyms = {r["qid"]: r["demonyms"] for r in map(json.loads, open(wiki / "demonyms.jsonl"))}
    COUNTRY_PIDS = {"P27", "P495", "P17"}
    held = {json.loads(l)["title"] for l in open(wiki / "d0_2shot.jsonl")}
    held |= {t for x in json.load(open(wiki / "data/dev.json")) for t, _ in x["context"]}
    para = {}
    for x in json.load(open(wiki / "data/train.json")):
        for t, s in x["context"]:
            para.setdefault(t, " ".join(s))
    rows, stats = [], {"paragraphs": 0, "with_facts": 0, "facts": 0, "held_out_skipped": 0, "no_claims": 0}
    rels = ", ".join(PRED.values())
    for title, q in qid.items():
        if title not in para:
            continue
        if title in held or entity(title) in {entity(h) for h in ()}:
            stats["held_out_skipped"] += 1
            continue
        stats["paragraphs"] += 1
        text, nt = para[title], tnorm(para[title])
        c = claims.get(q)
        if not c:
            stats["no_claims"] += 1
            continue
        subj = entity(title)
        facts = []
        for pid, vals in c.items():
            pred = pid2pred.get(pid)
            if not pred:
                continue
            for v in vals:
                forms = labels.get(v, []) if v.startswith("Q") else date_forms(v) if "T" in v else [v]
                if pid in COUNTRY_PIDS:
                    forms = forms + demonyms.get(v, [])
                hit = next((f for f in forms if tnorm(f) and re.search(r"(?<![a-z0-9])" + re.escape(tnorm(f)) + r"(?![a-z0-9])", nt)), None)
                if hit:
                    facts.append((pred, hit))
        facts = list(dict.fromkeys(facts))
        if not facts:
            continue
        stats["with_facts"] += 1; stats["facts"] += len(facts)
        fact_lines = "\n".join(f'{p}("{subj}", "{o}").' for p, o in facts)
        read_user = (f"Text:\n{text}\n\nWrite every fact the text states about \"{title}\" as lines "
                     f"relation(\"Subject\", \"Object\"). using only these relations: {rels}. Nothing else.")
        write_user = f"Facts:\n{fact_lines}\n\nWrite a short English paragraph that states exactly these facts and nothing else."
        dem_words = {d.lower() for ds in demonyms.values() for d in ds}
        DEM_TEMPLATE = {"country_of_citizenship": "{s} was {o}.", "country_of_origin": "{s} is {o}.", "country": "{s} is {o}."}
        write_txt = " ".join((DEM_TEMPLATE[p] if p in DEM_TEMPLATE and o.lower() in dem_words else TEMPLATE[p]).format(s=subj, o=o)
                             for p, o in facts)
        KIN = {"father", "mother", "spouse", "child", "sibling"}
        reps = 3 if len({p for p, _o in facts} & KIN) >= 2 else 1
        stats["kin_contrast"] = stats.get("kin_contrast", 0) + (reps == 3)
        for kind, u, a in (("read", read_user, fact_lines),) * reps:
            rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": u}, {"role": "assistant", "content": a}],
                         "meta": {"task": f"r3r_{kind}", "title": title, "n_facts": len(facts)}})
    rnd.shuffle(rows)
    if max_rows:
        rows = rows[:max_rows]
    (out / "split").mkdir(parents=True, exist_ok=True)
    with open(out / "split/train.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "run.json").write_text(json.dumps({"base_model": "Qwen/Qwen3-0.6B", "kit": "R3r read only, demonyms, kin-contrast x3, Wikidata targets stated in the text",
                                              "stats": stats, "rows": len(rows)}, indent=1))
    print(json.dumps({**stats, "rows": len(rows), "facts_per_paragraph": round(stats["facts"] / max(1, stats["with_facts"]), 2)}))


if __name__ == "__main__":
    main()

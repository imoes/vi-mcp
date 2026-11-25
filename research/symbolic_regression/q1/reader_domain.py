"""Domain filter between the readers and the solver (22.11.2026, development on fresh2; a separate file because reader_merge.py is
frozen by PREREG_R3m). Found on fresh2: the base reader writes person relations for works ("Gentlemen Prefer Blondes (1953 film)",
date of birth, "1953"), and in a "director born later" comparison that value can beat the real director's 1952. The filter:
  1. drops placeholder objects (unknown, not specified, none, n/a, empty);
  2. a subject counts as a WORK when, over all reads, it has MORE work-relation triples than person-relation triples (a tie keeps
     everything); "country of origin" is no work signal because the base reader writes it for people too (dev: 5,847 of the
     dropped triples under the first version, which used "any work relation" and fell from 75.25 to 23.5 %).
     Person relations for a WORK subject are dropped.
Both rules are type constraints on the relation's domain (Wikidata: P569 date of birth has subject type human), not learned.
usage: reader_domain.py READS OUT"""
import json
import re
import sys

WORK = {"director", "publication date", "producer", "composer", "performer", "screenwriter", "cast member", "country of origin",
        "production company", "distributor", "editor", "cinematographer", "inception", "original language of film or tv show"}
PERSON = {"date of birth", "date of death", "place of birth", "place of death", "father", "mother", "spouse", "child", "sibling",
          "country of citizenship", "educated at", "place of burial", "occupation", "employer", "cause of death", "stepparent"}
PLACEHOLDER = {"", "unknown", "not specified", "none", "n a", "na", "not mentioned", "not stated", "not given", "null"}


def key(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s*\(.*?\)\s*$", "", s.lower())).split())


def main():
    src, out = sys.argv[1:3]
    n = dropped_ph = dropped_dom = 0
    with open(out, "w") as f:
        for line in open(src):
            r = json.loads(line)
            votes = {}
            for rd in r["reads"]:
                for s, p, o in rd["triples"]:
                    if p in WORK and p != "country of origin":
                        votes[key(s)] = votes.get(key(s), 0) + 1
                    elif p in PERSON:
                        votes[key(s)] = votes.get(key(s), 0) - 1
            works = {k for k, v in votes.items() if v > 0}
            new = []
            for rd in r["reads"]:
                tr = []
                for s, p, o in rd["triples"]:
                    n += 1
                    if key(o) in PLACEHOLDER:
                        dropped_ph += 1; continue
                    if p in PERSON and key(s) in works:
                        dropped_dom += 1; continue
                    tr.append([s, p, o])
                new.append(dict(rd, triples=tr))
            f.write(json.dumps(dict(r, reads=new), ensure_ascii=False) + "\n")
    print(json.dumps({"triples": n, "dropped_placeholder": dropped_ph, "dropped_person_rel_on_work": dropped_dom}))


if __name__ == "__main__":
    main()

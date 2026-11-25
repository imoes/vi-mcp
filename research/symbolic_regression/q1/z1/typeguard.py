"""Z1 lever candidate (25.11.2026, development only — fresh3 and fresh4 are spent sets): a relation TYPE GUARD between each reader
and the primary-first merge. A read triple is dropped when its object cannot be a value of its relation's type; nothing is rewritten
and nothing is added. Because reader_merge.py pref drops a secondary (base) triple only where the primary (R3r) has a triple of the
same relation for a token-sharing subject, a dropped wrong primary value lets the base reader's value through.

Types (2Wiki relations as read):
  date    date of birth, date of death, publication date, inception — must contain a digit
  place   place of birth/death/burial, country of citizenship, country of origin, country — must not look like a date or a number
  agent   father, mother, spouse, child, sibling, director, performer, composer, producer, founded by, student of, doctoral advisor,
          creator, editor — must not look like a date or a number, and must not be the subject itself
  any relation: a placeholder value ("unknown", "not specified", …) is dropped.
usage: typeguard.py IN.jsonl OUT.jsonl   (prints the dropped counts per reason and relation)"""
import collections
import json
import re
import sys

DATE = {"date of birth", "date of death", "publication date", "inception"}
PLACE = {"place of birth", "place of death", "place of burial", "country of citizenship", "country of origin", "country"}
AGENT = {"father", "mother", "spouse", "child", "sibling", "director", "performer", "composer", "producer", "founded by", "student of",
         "doctoral advisor", "creator", "editor"}
PLACEHOLDER = re.compile(r"^\s*(unknown|not (specified|mentioned|stated|given|known|available)|none|n/?a|null|-+|\?+|unspecified)\s*\.?$", re.I)
MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?"
DATELIKE = re.compile(rf"^\s*(\d{{1,4}}([./-]\d{{1,2}}([./-]\d{{1,4}})?)?|\d{{1,2}}\s+{MONTH}(\s+\d{{1,4}})?|{MONTH}\s+\d{{1,2}}(,?\s+\d{{1,4}})?|{MONTH}\s+\d{{3,4}}|(c\.|circa|ca\.)?\s*\d{{3,4}}s?(\s*(bc|ad|bce|ce))?)\s*$", re.I)


def reason(s, p, o):
    if PLACEHOLDER.match(o):
        return "placeholder"
    if p in DATE and not re.search(r"\d", o):
        return "date_without_digit"
    if p in PLACE and (DATELIKE.match(o) or re.fullmatch(r"\s*\d+\s*", o)):
        return "place_is_date_or_number"
    if p in AGENT:
        if DATELIKE.match(o) or re.fullmatch(r"\s*\d+\s*", o):
            return "agent_is_date_or_number"
        if o.strip().lower() == s.strip().lower():
            return "agent_is_subject"
    return None


def guard(inp, out):
    dropped = collections.Counter(); kept = 0
    with open(out, "w") as f:
        for line in open(inp):
            r = json.loads(line)
            for rd in r["reads"]:
                keep = []
                for s, p, o in rd["triples"]:
                    why = reason(s, p, o)
                    if why:
                        dropped[(why, p)] += 1
                    else:
                        keep.append([s, p, o]); kept += 1
                rd["triples"] = keep
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"kept": kept, "dropped": sum(dropped.values()),
                      "by": {f"{w} | {p}": n for (w, p), n in dropped.most_common()}}, ensure_ascii=False))


if __name__ == "__main__":
    guard(*sys.argv[1:3])

"""A rule -> prose renderer in the conventions the kit's gold texts and the trained model use (clingo_prose._lit_prose, DUTY_WORDS):
  head when b1 and b2, and X is not the same as Y, and it cannot be derived that n1.
  If b1 and b2, one must|must not|may act A for B.
  It is a violation if b1 and it cannot be derived that n1.
Self-test (python rule_prose.py): rendering the kollektiv 1.2.0 seed blocks reproduces run 33c's correct whole-seed prose sentence by
sentence (up to commas)."""
import re
import sys

sys.path.insert(0, "~/Dev/code/vi-mcp-router")
from clingo_object.clingo_prose import DUTY_WORDS, _lit_prose, _w  # noqa: E402

_ATOM = re.compile(r"^(~?)([a-z]\w*)(?:\((.*)\))?$")


def split_top(s, sep=" & "):
    out, depth, cur, i = [], 0, "", 0
    while i < len(s):
        if s.startswith(sep, i) and depth == 0:
            out.append(cur); cur = ""; i += len(sep); continue
        c = s[i]; depth += c == "("; depth -= c == ")"; cur += c; i += 1
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def args_of(s):
    return [a.strip() for a in split_top(s, ",")] if s else []


def lit(text):
    """(kind, prose): kind pos | neg | cmp"""
    t = text.strip()
    if t.startswith("(") and " != " in t:
        a, b = t[1:-1].split(" != ")
        return "cmp", f"{a.strip()} is not the same as {b.strip()}"
    m = _ATOM.match(t)
    neg, name, args = m.group(1), m.group(2), args_of(m.group(3))
    return ("neg" if neg else "pos"), _lit_prose(name, args)


def body_prose(body, comma_rest=True):
    lits = [lit(x) for x in split_top(body)]
    pos = [p for k, p in lits if k == "pos"]
    rest = [(k, p) for k, p in lits if k != "pos"]
    s = " and ".join(pos)
    for k, p in rest:
        s += (", and " if comma_rest else " and ") + (p if k == "cmp" else "it cannot be derived that " + p)
    return s


def rule(code):
    code = code.strip()
    if code.startswith("never("):
        return f"It is a violation if {body_prose(code[6:-1], comma_rest=False)}."
    head, _, body = code.partition(" <= ")
    m = re.match(r"^(obligatory|forbidden|may)\((\w+)\((.*)\)\)$", head)
    if m:
        d, act, args = m.group(1), m.group(2), args_of(m.group(3))
        return f"If {body_prose(body)}, {DUTY_WORDS[d]} {_w(act)} {' for '.join(args)}."
    h = lit(head)[1]
    return f"{h[0].upper() + h[1:]} when {body_prose(body)}."


def program(code):
    return " ".join(rule(r) for r in code.split("\n") if r.strip())


if __name__ == "__main__":
    import importlib.util, json
    S = "<scratchpad>"
    spec = importlib.util.spec_from_file_location("k120", S + "/src066/clingo_object/philosophy_kollektiv.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    seed = [l for l in mod.PACKAGE["seed"].split("\n") if l.strip() and not l.startswith("#")]
    mine = [rule(r) for r in seed]
    a33 = {f'{json.loads(l).get("set")}/{json.loads(l)["id"]}': json.loads(l)["tuned"] for l in open(S + "/ft/kit33cs/eval/answers.jsonl")}
    model = re.split(r"(?<=\.)\s+(?=[A-Z])", a33["explain_seed/explain_seed:all"].strip())
    norm = lambda x: re.sub(r"[,\s]+", " ", x).strip().lower()
    same = sum(norm(a) == norm(b) for a, b in zip(mine, model))
    print(f"seed rules {len(seed)}, model sentences {len(model)}, identical up to commas {same}")
    for a, b in zip(mine, model):
        if norm(a) != norm(b):
            print("  mine :", a); print("  model:", b)

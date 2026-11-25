"""G8b-1 step 1: grade every blind task by its MEASURED structural distance to the library, before any search runs.
A rule's shape = its canonical form with predicate names replaced by arity placeholders numbered by first appearance (consistent within
the rule) and constants replaced by C — what stays is the wiring. Grades:
  iso          every reference rule's shape occurs in ONE library block
  composition  every shape occurs in the library, but only across two or more blocks
  one_edit     all shapes but one occur, and the missing one is one literal away (add or drop) from a library shape
  none         otherwise (negative control: no library analogue)
usage: grade.py  -> grades.json"""
import ast, json, os, sys
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
sys.path.insert(0, os.environ.get("VI_MCP_REPO") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
import gp  # noqa: E402
from clingo_object import philosophy as ph  # noqa: E402
import blind_tasks as BT  # noqa: E402


def parse(text):
    """notation rule -> gp rule tuple, or None for facts / never(...)"""
    node = ast.parse(text.strip(), mode="eval").body
    if not (isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.LtE)):
        return None

    def atom(n):
        if isinstance(n, ast.Call):
            return (n.func.id, tuple(ast.unparse(a) for a in n.args))
        return (n.id, ())
    head = atom(node.left)
    if head[0] == "never":
        return None
    lits = []

    def walk(n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitAnd):
            walk(n.left); walk(n.right)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Invert):
            lits.append(("-", atom(n.operand)))
        elif isinstance(n, ast.Compare):
            lits.append(("!=", ast.unparse(n.left), ast.unparse(n.comparators[0])))
        else:
            lits.append(("+", atom(n)))
    walk(node.comparators[0])
    return (head, tuple(lits))


def shape(rule):
    r = gp.canon_rule(rule)
    m = {}

    def pn(p, n):
        m.setdefault(p, f"P{n}_{len(m)}")
        return m[p]

    def args(a):
        return tuple(x if gp.is_var(x) else "C" for x in a)
    h, b = r
    out = [(pn(h[0], len(h[1])), args(h[1]))]
    for l in b:
        out.append(("!=",) if l[0] == "!=" else (l[0], pn(l[1][0], len(l[1][1])), args(l[1][1])))
    return (out[0], tuple(sorted(map(str, out[1:]))))


def library_shapes():
    shapes = defaultdict(set)  # shape -> blocks
    for name in ("kollektiv", "messung", "code"):
        pkg = ph.load(name)
        for b, rs in ph.blocks(pkg["seed"])[0]:
            for x in rs:
                r = parse(x) if x.strip() else None
                if r and gp.safe(r):
                    shapes[shape(r)].add(f"{name}:{b}")
    return shapes


def one_literal_away(s, lib):
    head, body = s
    for t in lib:
        if t[0][0][:2] != head[0][:2]:
            continue
        a, b = list(body), list(t[1])
        if len(a) == len(b) + 1 and all(x in a for x in b):
            return True
        if len(b) == len(a) + 1 and all(x in b for x in a):
            return True
    return False


if __name__ == "__main__":
    lib = library_shapes()
    grades = {}
    for name, t in BT.TASKS.items():
        rules = [r for r in (parse(x) for x in t["REFERENCE"].splitlines() if x.strip()) if r]
        hits = [lib.get(shape(r), set()) for r in rules]
        common = set.intersection(*hits) if all(hits) else set()
        if all(hits) and common:
            g = "iso"
        elif all(hits):
            g = "composition"
        elif sum(1 for h in hits if not h) == 1 and one_literal_away(shape(rules[[i for i, h in enumerate(hits) if not h][0]]), lib):
            g = "one_edit"
        else:
            g = "none"
        grades[name] = {"grade": g, "kind": BT.KINDS[name], "rules": len(rules), "rules_with_library_shape": sum(1 for h in hits if h),
                        "blocks": sorted(set().union(*hits)) if any(hits) else []}
    json.dump(grades, open(os.path.join(D, "grades.json"), "w"), indent=1)
    from collections import Counter
    print(Counter(v["grade"] for v in grades.values()))
    for k, v in grades.items():
        print(f"{k:22s} {v['kind']} {v['grade']:12s} {v['rules_with_library_shape']}/{v['rules']} {','.join(v['blocks'][:4])}")

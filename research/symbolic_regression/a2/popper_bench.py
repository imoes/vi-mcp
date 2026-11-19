"""A2: our symbolic-regression search (gp2, unchanged operators and selection) on Popper's own example tasks, scored the way Popper
scores: only the listed examples count — tp = predicted & pos, fp = predicted & neg; atoms that are neither pos nor neg are don't-care.
"Solved" = complete and consistent on all examples (Popper's "Precision:1.00 Recall:1.00"), the same criterion Popper prints.

Background knowledge: bk.pl facts are given to clingo as they are (flat Prolog facts are ASP facts); tasks whose bk.pl has rules,
lists, quoted atoms or upper-case constants are skipped with the reason. The bias gives head/body predicates and arities; types come
from bias.pl type/2 where present, otherwise from shared constants (gp2.Task._types logic). Popper's language limits (max_vars,
max_body, max_clauses) are NOT given to gp2 — it has its own size pressure.
Lexicase cases: the examples split into K stratified chunks; each candidate program is solved ONCE on the whole background and its
answer is intersected with each chunk's listed examples.
usage: popper_bench.py EXAMPLES_DIR TASK SEED OUTDIR [--seconds S] [--evals N]
       popper_bench.py --list EXAMPLES_DIR      (which tasks are usable, which are skipped and why)"""
import argparse, json, os, random, re, sys, time
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(D, "..", "g8b"))
sys.path.insert(0, os.path.join(D, "..", "g8"))
import clingo  # noqa: E402
import gp2 as gp  # noqa: E402

FACT = re.compile(r"^([a-z]\w*)(?:\((.*)\))?\.\s*$")
ATOM = re.compile(r"^(pos|neg)\(([a-z]\w*)\((.*)\)\)\.\s*$")
K_CASES = 20
SOLVE_TIMEOUT = 20.0


def split_args(s):
    return [a.strip() for a in s.split(",")] if s else []


def bad_const(a):
    return not re.fullmatch(r"[a-z][A-Za-z0-9_]*|-?\d+", a)


def load(ex_dir, name):
    """-> task dict, or raise ValueError(reason)"""
    d = os.path.join(ex_dir, name)
    facts, preds_seen = [], defaultdict(set)
    for ln in open(os.path.join(d, "bk.pl"), errors="replace"):
        s = ln.strip()
        if not s or s.startswith("%") or s.startswith(":-"):
            continue
        m = FACT.match(s)
        if not m or ":-" in s:
            raise ValueError("bk.pl has rules or non-flat terms")
        args = split_args(m.group(2))
        if any(bad_const(a) for a in args):
            raise ValueError("bk.pl has lists, quoted atoms or upper-case constants")
        facts.append(s)
        preds_seen[m.group(1)].add(len(args))
    head, body, types = None, {}, {}
    bias = open(os.path.join(d, "bias.pl"), errors="replace").read()
    # IGGP idiom: body_pred(P,1) :- constant(P,_).  type(P,(T,)) :- constant(P,T).  — expanded over the constant/2 facts
    const_rule = re.search(r"body_pred\(P,\s*1\)\s*:-\s*constant\(P", bias)
    bias = re.sub(r"(body_pred|type)\(P,[^)]*\)+\s*:-\s*constant\([^)]*\)\s*\.", "", bias)
    for ln in bias.splitlines():
        s = ln.split("%", 1)[0].strip()
        if const_rule and (m := re.match(r"constant\((\w+),\s*(\w+)\)\s*\.", s)):
            body[m.group(1)] = 1
            types[m.group(1)] = [m.group(2)]
        elif m := re.match(r"head_pred\((\w+),\s*(\d+)\)", s):
            if head:
                raise ValueError("more than one head predicate")
            head = (m.group(1), int(m.group(2)))
        elif m := re.match(r"body_pred\((\w+),\s*(\d+)\)", s):
            body[m.group(1)] = int(m.group(2))
        elif m := re.match(r"type\((\w+),\s*\(([^)]*)\)\)", s):
            types[m.group(1)] = [x.strip() for x in m.group(2).split(",") if x.strip()]
    if not head:
        raise ValueError("no head_pred")
    missing = [p for p in body if p not in preds_seen]
    if missing:
        raise ValueError(f"body predicates defined by rules or absent in bk: {missing[:3]}")
    pos, neg = set(), set()
    for ln in open(os.path.join(d, "exs.pl"), errors="replace"):
        s = ln.strip()
        if not s or s.startswith("%") or s.startswith(":-"):
            continue
        m = ATOM.match(s.replace(" ", ""))
        if not m or m.group(2) != head[0]:
            raise ValueError("example not a flat atom of the head predicate")
        args = split_args(m.group(3))
        if any(bad_const(a) for a in args):
            raise ValueError("example has non-flat constants")
        (pos if m.group(1) == "pos" else neg).add(f"{head[0]}({','.join(args)})")
    if pos & neg:
        raise ValueError("an atom is both pos and neg (noisy task)")
    return {"name": name, "facts": "\n".join(facts), "head": head, "body": body, "types": types, "pos": pos, "neg": neg,
            "n_facts": len(facts)}


class BenchTask:
    """the interface gp2.Search reads; worlds are case keys, E.answers is replaced by solve-once-and-intersect"""
    def __init__(self, t, seed):
        self.name, self.ref = t["name"], None
        self.inputs, self.answers = dict(t["body"]), {t["head"][0]: t["head"][1]}
        rnd = random.Random(f"{t['name']}:cases:{seed}")
        pos, neg = sorted(t["pos"]), sorted(t["neg"])
        rnd.shuffle(pos); rnd.shuffle(neg)
        k = max(1, min(K_CASES, len(pos) + len(neg)))
        cases = [set() for _ in range(k)]
        for i, a in enumerate(pos + neg):  # stratified: positives first, round robin
            cases[i % k].add(a)
        cases = [c for c in cases if c]
        self.train = [f"CASE:{i}" for i in range(len(cases))]
        self.gold = [frozenset(c & t["pos"]) for c in cases]
        self.listed = {f"CASE:{i}": c for i, c in enumerate(cases)}
        self.listed["CASE:all"] = t["pos"] | t["neg"]
        self.verify, self.verify_gold = ["CASE:all"], [frozenset(t["pos"])]
        self.stress, self.stress_gold = [], []
        consts = defaultdict(set)
        for ln in t["facts"].splitlines():
            m = FACT.match(ln)
            for i, a in enumerate(split_args(m.group(2))):
                consts[(m.group(1), i)].add(a)
        for a in t["pos"]:
            p, rest = a.split("(", 1)
            for i, x in enumerate(split_args(rest.rstrip(")"))):
                consts[(p, i)].add(x)
        self.type_of = {}
        for p, ty in t["types"].items():  # declared types first
            for i, x in enumerate(ty):
                self.type_of[(p, i)] = ("declared", x)
        parent = {k2: k2 for k2 in consts}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        ks = [k2 for k2 in consts if k2 not in self.type_of]
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                if consts[a] & consts[b]:
                    parent[find(a)] = find(b)
        for k2 in ks:
            self.type_of[k2] = find(k2)
        for p, n in {**self.inputs, **self.answers}.items():
            for i in range(n):
                self.type_of.setdefault((p, i), ("untyped", p, i))
        members = defaultdict(list)
        for k2, ty in self.type_of.items():
            members[ty].append(k2)
        self.consts = {k2: sorted(v) for k2, v in consts.items() if len(members[self.type_of[k2]]) == 1 and len(v) <= 6}


class Solver:
    def __init__(self, t, deadline):
        self.facts, self.head, self.deadline = t["facts"], t["head"], deadline
        self.cache, self.solves, self.failed = {}, 0, 0

    def full(self, prog):
        if prog in self.cache:
            return self.cache[prog]
        if time.time() > self.deadline:
            raise TimeoutError("wall-clock budget")
        self.solves += 1
        res = None
        try:
            asp, _st, _f = gp.E.n.translate_full(prog)
            rules = "\n".join(x for x in asp.splitlines() if not x.startswith("vi__fired("))
            ctl = clingo.Control(["--enum-mode=cautious", "--models=0", "--warn=none"])
            ctl.add("base", [], rules + "\n" + self.facts + f"\n#show {self.head[0]}/{self.head[1]}.")
            ctl.ground([("base", [])])
            last = []
            with ctl.solve(yield_=True, async_=True) as h:
                t0 = time.time()
                while True:
                    h.resume()
                    if not h.wait(max(0.01, SOLVE_TIMEOUT - (time.time() - t0))):
                        h.cancel(); last = None; break
                    m = h.model()
                    if m is None:
                        break
                    last = [str(s).replace(" ", "") for s in m.symbols(shown=True)]
                if last is not None and not h.get().satisfiable:
                    last = None
            res = frozenset(last) if last is not None else None
        except TimeoutError:
            raise
        except Exception:  # noqa: BLE001 — an untranslatable or unsolvable individual is unfit, as in g8_eval
            res = None
        if res is None:
            self.failed += 1
        self.cache[prog] = res
        return res


def run(ex_dir, name, seed, out, seconds, evals):
    t = load(ex_dir, name)
    task = BenchTask(t, seed)
    sv = Solver(t, time.time() + seconds)

    def answers(prog, w, preds):
        got = sv.full(prog)
        return None if got is None else frozenset(got & task.listed[w])
    gp.E.answers = answers
    t0 = time.time()
    first = {}

    def on_first(rec):
        first.update(rec, seconds=round(time.time() - t0, 2))
    s = gp.Search(task, seed, evals, after_solve=gp.AFTER_SOLVE, on_first=on_first)  # G8b-0's rule: 25 more generations for a shorter one
    stopped = "budget"
    try:
        s.run()
    except TimeoutError:
        stopped = "wall-clock"
    best = None
    for size_, (f, prog) in sorted(s.archive.items()):
        if best is None or f > best[0]:
            best = (f, size_, gp.render(prog))
    stats = {}
    if best and sv.cache.get(best[2]) is not None:
        got = sv.cache[best[2]]
        tp, fp = len(got & t["pos"]), len(got & t["neg"])
        fn, tn = len(t["pos"]) - tp, len(t["neg"]) - fp
        stats = {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                 "balanced_accuracy": round(0.5 * (tp / max(1, tp + fn) + (tn / (tn + fp) if tn + fp else 1.0)), 4)}
    sols = sorted(s.solutions.values(), key=lambda r: r["size"])
    res = {"task": name, "seed": seed, "solved": bool(sols), "first_solution": first or None,
           "smallest_solution": sols[0] if sols else None,
           "best_training": {"mean_case_f1": round(best[0], 4), "size": best[1], "program": best[2], **stats} if best else None,
           "evals": s.evals, "solves": sv.solves, "failed_solves": sv.failed, "stopped": stopped,
           "seconds": round(time.time() - t0, 1), "limit_seconds": seconds, "pos": len(t["pos"]), "neg": len(t["neg"]),
           "bk_facts": t["n_facts"], "cases": len(task.train)}
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(os.path.join(out, f"{name}__s{seed}.json"), "w"), indent=1)
    b = res["best_training"] or {}
    print(json.dumps({k: res[k] for k in ("task", "seed", "solved", "evals", "seconds", "stopped")}
                     | {"best": {k: b.get(k) for k in ("size", "balanced_accuracy", "program")}}))


if __name__ == "__main__":
    if sys.argv[1] == "--list":
        ex = sys.argv[2]
        for name in sorted(os.listdir(ex)):
            if not os.path.isfile(os.path.join(ex, name, "bk.pl")):
                continue
            try:
                t = load(ex, name)
                print(f"OK    {name}  facts={t['n_facts']} pos={len(t['pos'])} neg={len(t['neg'])} head={t['head']}")
            except ValueError as e:
                print(f"SKIP  {name}  {e}")
        sys.exit()
    ap = argparse.ArgumentParser()
    ap.add_argument("ex"); ap.add_argument("task"); ap.add_argument("seed", type=int); ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=600); ap.add_argument("--evals", type=int, default=10**9)
    o = ap.parse_args()
    run(o.ex, o.task, o.seed, o.out, o.seconds, o.evals)

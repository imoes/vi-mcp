"""G8b — symbolic regression over logic rules (genetic programming), built after the review of G8 (Claude Fable, 19.11.2026).

What it is: candidate rule sets are trees (head <= literals); mutation changes predicates, variables, constants, literals and negation;
crossover exchanges BODY parts of two rules with variable unification; new helper predicates are invented (also recursive ones);
selection is lexicase over the worlds, with an archive of the best fit per size (accuracy vs shortness, the Pareto front); every
candidate is reduced to a canonical form and evaluated once (cache). The solver over worlds is the fitness.

"Solved" means equivalent to the task's reference on EVERY world of an exhaustively enumerated small domain (tasks.verify_worlds),
plus a stress check on larger random worlds; a candidate exact on the training worlds but wrong on the domain adds its first
counterexample to the training worlds (counterexample-guided). The product is a graph: mechanism objects and edges (graph.jsonl).

usage: gp.py TASK SEED OUTDIR [--budget N] [--library none]"""
import argparse, hashlib, json, random, sys, time
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/g8")
import g8_eval as E  # noqa: E402
import tasks as T  # noqa: E402

POP, TRAIN_N, STRESS_N, MAX_RULES, MAX_BODY, HELPERS = 100, 30, 200, 6, 4, 3
MAX_GENS = 300
AFTER_SOLVE = 25


# ── representation ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
# atom = (pred, (args...)); literal = ("+", atom) | ("-", atom) | ("!=", a, b); rule = (head atom, (literals...)); program = tuple of rules
def is_var(a):
    return a[:1].isupper()


def render_atom(a):
    return f"{a[0]}({', '.join(a[1])})" if a[1] else a[0]


def render(prog):
    out = []
    for h, body in prog:
        lits = [f"({l[1]} != {l[2]})" if l[0] == "!=" else ("~" if l[0] == "-" else "") + render_atom(l[1]) for l in body]
        out.append(f"{render_atom(h)} <= {' & '.join(lits)}" if lits else render_atom(h))
    return "\n".join(out)


def rule_vars(rule):
    h, body = rule
    vs = [a for a in h[1] if is_var(a)]
    for l in body:
        vs += [a for a in ((l[1], l[2]) if l[0] == "!=" else l[1][1]) if is_var(a)]
    return list(dict.fromkeys(vs))


def safe(rule):
    """every variable of the head, of a negated literal and of != occurs in a positive literal"""
    h, body = rule
    bound = {a for l in body if l[0] == "+" for a in l[1][1] if is_var(a)}
    need = [a for a in h[1] if is_var(a)]
    for l in body:
        if l[0] == "-":
            need += [a for a in l[1][1] if is_var(a)]
        elif l[0] == "!=":
            need += [a for a in (l[1], l[2]) if is_var(a)]
    return bool(body) and all(a in bound for a in need)


def canon_rule(rule):
    """rename variables in order of first appearance after sorting literals by a variable-blind key — a canonical form"""
    h, body = rule

    def blind(l):
        return (l[0], l[1][0] if l[0] != "!=" else "", tuple("V" if is_var(a) else a for a in (l[1][1] if l[0] != "!=" else (l[1], l[2]))))
    body = sorted(set(body), key=lambda l: (blind(l), str(l)))
    m = {}

    def r(a):
        if not is_var(a):
            return a
        m.setdefault(a, f"V{len(m)}")
        return m[a]
    h2 = (h[0], tuple(r(a) for a in h[1]))
    b2 = []
    for l in body:
        if l[0] == "!=":
            x, y = sorted((r(l[1]), r(l[2])))
            b2.append(("!=", x, y))
        else:
            b2.append((l[0], (l[1][0], tuple(r(a) for a in l[1][1]))))
    return (h2, tuple(b2))


def canon(prog):
    rules = sorted({canon_rule(r) for r in prog if safe(r)}, key=str)
    used = {l[1][0] for _h, b in rules for l in b if l[0] != "!="}
    heads = {h[0] for h, _b in rules}
    # drop helper rules nothing reads (dead code) — repeat until stable
    while True:
        dead = {p for p in heads if p.startswith("inv") and p not in used}
        if not dead:
            break
        rules = [r for r in rules if r[0][0] not in dead]
        used = {l[1][0] for _h, b in rules for l in b if l[0] != "!="}
        heads = {h[0] for h, _b in rules}
    return tuple(rules)


def size(prog):
    return sum(1 + len(b) for _h, b in prog)


def key(prog):
    return hashlib.sha256(render(prog).encode()).hexdigest()[:16]


# ── the task as data: vocabulary, types inferred from the worlds ───────────────────────────────────────────────────────────────
class Task:
    def __init__(self, name, seed):
        t = T.TASKS[name]
        self.name, self.inputs, self.answers = name, dict(t["inputs"]), dict(t["answers"])
        self.ref = t["REFERENCE"]
        rnd = __import__("random").Random(f"{name}:{seed}")
        self.train = [T.world_text(name, rnd) for _ in range(TRAIN_N)]
        self.gold = [E.answers(self.ref, w, self.answers) for w in self.train]
        self.verify = T.verify_worlds(name)
        self.verify_gold = [E.answers(self.ref, w, self.answers) for w in self.verify]
        srnd = __import__("random").Random(f"{name}:stress:{seed}")
        self.stress = [T.world_text(name, srnd, big=True) for _ in range(STRESS_N)]
        self.stress_gold = [E.answers(self.ref, w, self.answers) for w in self.stress]
        self._types()

    def _types(self):
        """argument positions that share constants in the data share a type (union-find); constants per position"""
        consts = defaultdict(set)
        for w, g in zip(self.train, self.gold):
            for line in w.splitlines():
                p, args = line.split("(", 1)
                for i, a in enumerate(args.rstrip(")").split(", ")):
                    consts[(p, i)].add(a)
            for atom in g:
                p, args = atom.split("(", 1)
                for i, a in enumerate(args.rstrip(")").split(",")):
                    consts[(p, i)].add(a)
        parent = {k: k for k in consts}

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]; k = parent[k]
            return k
        ks = list(consts)
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                if consts[a] & consts[b]:
                    parent[find(a)] = find(b)
        self.type_of = {k: find(k) for k in ks}
        for p, n in {**self.inputs, **self.answers}.items():
            for i in range(n):
                self.type_of.setdefault((p, i), ("untyped", p, i))
        # value positions (ok/fail, up/down, red/blue) are offered as constants: a position whose type no other position shares;
        # entities (people, packages, hosts) share their type across predicates and are never constants of a rule
        members = defaultdict(list)
        for k2, ty in self.type_of.items():
            members[ty].append(k2)
        self.consts = {k: sorted(v) for k, v in consts.items() if len(members[self.type_of[k]]) == 1 and len(v) <= 6}


# ── generating literals with typed variables ───────────────────────────────────────────────────────────────────────────────────
class Gen:
    def __init__(self, task, rnd):
        self.t, self.rnd = task, rnd

    def arity(self, p, helpers):
        return self.t.inputs.get(p) or self.t.answers.get(p) or helpers.get(p)

    def ptype(self, p, i, helpers):
        if p in helpers:
            return helpers[p + "#types"][i] if p + "#types" in helpers else ("h", p, i)
        return self.t.type_of.get((p, i), ("untyped", p, i))

    def var_types(self, rule, helpers):
        vt = {}
        h, body = rule
        for i, a in enumerate(h[1]):
            if is_var(a):
                vt.setdefault(a, self.ptype(h[0], i, helpers))
        for l in body:
            if l[0] != "!=":
                for i, a in enumerate(l[1][1]):
                    if is_var(a):
                        vt.setdefault(a, self.ptype(l[1][0], i, helpers))
        return vt

    def fresh(self, rule):
        used = set(rule_vars(rule))
        k = 0
        while f"N{k}" in used:
            k += 1
        return f"N{k}"

    def atom(self, rule, helpers, preds, connect=True):
        """an atom whose arguments prefer variables of the same type already in the rule, never one variable twice"""
        p = self.rnd.choice(preds)
        n = self.arity(p, helpers)
        vt = self.var_types(rule, helpers)
        args = []
        for i in range(n):
            ty = self.ptype(p, i, helpers)
            same = [v for v, t in vt.items() if t == ty and v not in args]
            cs = self.t.consts.get((p, i))
            r = self.rnd.random()
            if cs and r < 0.35:
                args.append(self.rnd.choice(cs))
            elif same and (connect or r < 0.7):
                args.append(self.rnd.choice(same))
            else:
                v = self.fresh((rule[0], rule[1] + (("+", ("_", tuple(args))),)))
                args.append(v); vt[v] = ty
        return (p, tuple(args))

    def body_preds(self, helpers):
        return list(self.t.inputs) + [p for p in helpers if not p.endswith("#types")]

    def new_rule(self, helpers, head_pred=None):
        hp = head_pred or self.rnd.choice(list(self.t.answers) + [p for p in helpers if not p.endswith("#types")])
        n = self.arity(hp, helpers)
        rule = ((hp, ()), ())
        body = []
        for _ in range(self.rnd.randint(1, 3)):
            a = self.atom((rule[0], tuple(body)), helpers, self.body_preds(helpers))
            body.append(("+", a))
        vt = self.var_types((rule[0], tuple(body)), helpers)
        hargs = []
        for i in range(n):
            ty = self.ptype(hp, i, helpers)
            cs = self.t.consts.get((hp, i))
            cand = [v for v, t in vt.items() if t == ty and v not in hargs] or [v for v in vt if v not in hargs]
            if cs and (self.rnd.random() < 0.5 or not cand):
                hargs.append(self.rnd.choice(cs))
            elif cand:
                hargs.append(self.rnd.choice(cand))
            else:
                return None
        return ((hp, tuple(hargs)), tuple(body))


def helpers_of(prog):
    h = {}
    for (p, args), _b in prog:
        if p.startswith("inv"):
            h[p] = len(args)
    return h


# ── operators ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def mutate(prog, gen, rnd):
    prog = list(prog)
    helpers = helpers_of(prog)
    ops = ["add_rule", "add_lit", "add_neg", "add_neq", "del_lit", "del_rule", "flip", "const", "var", "pred", "invent", "recurse"]
    op = rnd.choice(ops) if prog else "add_rule"
    i = rnd.randrange(len(prog)) if prog else 0
    if op == "add_rule" and len(prog) < MAX_RULES:
        r = gen.new_rule(helpers)
        if r:
            prog.append(r)
    elif op in ("add_lit", "add_neg") and prog and len(prog[i][1]) < MAX_BODY:
        h, b = prog[i]
        a = gen.atom(prog[i], helpers, gen.body_preds(helpers), connect=True)
        prog[i] = (h, b + (("-" if op == "add_neg" else "+", a),))
    elif op == "add_neq" and prog:
        vt = gen.var_types(prog[i], helpers)
        pairs = [(x, y) for x in vt for y in vt if x < y and vt[x] == vt[y]]
        if pairs:
            x, y = rnd.choice(pairs); prog[i] = (prog[i][0], prog[i][1] + (("!=", x, y),))
    elif op == "del_lit" and prog and len(prog[i][1]) > 1:
        b = list(prog[i][1]); b.pop(rnd.randrange(len(b))); prog[i] = (prog[i][0], tuple(b))
    elif op == "del_rule" and len(prog) > 1:
        prog.pop(i)
    elif op == "flip" and prog:
        b = list(prog[i][1]); js = [j for j, l in enumerate(b) if l[0] in "+-"]
        if js:
            j = rnd.choice(js); b[j] = ("-" if b[j][0] == "+" else "+", b[j][1]); prog[i] = (prog[i][0], tuple(b))
    elif op == "const" and prog:
        h, b = prog[i]
        atoms = [("h", -1, h)] + [("b", j, l[1]) for j, l in enumerate(b) if l[0] != "!="]
        w, j, a = rnd.choice(atoms)
        pos = [k for k in range(len(a[1])) if gen.t.consts.get((a[0], k))]
        if pos:
            k = rnd.choice(pos); a2 = (a[0], a[1][:k] + (rnd.choice(gen.t.consts[(a[0], k)]),) + a[1][k + 1:])
            prog[i] = (a2, b) if w == "h" else (h, b[:j] + ((b[j][0], a2),) + b[j + 1:])
    elif op == "var" and prog:
        h, b = prog[i]
        vt = gen.var_types(prog[i], helpers)
        js = [j for j, l in enumerate(b) if l[0] != "!=" and l[1][1]]
        if js:
            j = rnd.choice(js); a = b[j][1]; k = rnd.randrange(len(a[1]))
            ty = gen.ptype(a[0], k, helpers)
            cand = [v for v, t in vt.items() if t == ty and v not in a[1]] + [gen.fresh(prog[i])]
            a2 = (a[0], a[1][:k] + (rnd.choice(cand),) + a[1][k + 1:])
            prog[i] = (h, b[:j] + ((b[j][0], a2),) + b[j + 1:])
    elif op == "pred" and prog:
        h, b = prog[i]
        js = [j for j, l in enumerate(b) if l[0] != "!="]
        if js:
            j = rnd.choice(js); a = b[j][1]
            same = [p for p in gen.body_preds(helpers) if gen.arity(p, helpers) == len(a[1]) and p != a[0]]
            if same:
                prog[i] = (h, b[:j] + ((b[j][0], (rnd.choice(same), a[1])),) + b[j + 1:])
    elif op == "invent" and prog and len(helpers) < HELPERS and len(prog) < MAX_RULES:
        # abstraction: a part of a rule's positive body becomes a new helper predicate over the variables it shares with the rest
        h, b = prog[i]
        pos = [l for l in b if l[0] == "+"]
        if len(pos) >= 2:
            part = rnd.sample(pos, rnd.randint(1, len(pos) - 1))
            rest = [l for l in b if l not in part]
            pv = [a for l in part for a in l[1][1] if is_var(a)]
            ov = set(a for a in h[1] if is_var(a)) | {a for l in rest for a in ((l[1], l[2]) if l[0] == "!=" else l[1][1]) if is_var(a)}
            shared = list(dict.fromkeys(v for v in pv if v in ov))[:2]
            if shared:
                name = f"inv{len(helpers) + 1}"
                hel = (name, tuple(shared))
                prog[i] = (h, tuple(rest) + (("+", hel),))
                prog.append((hel, tuple(part)))
    elif op == "recurse" and helpers:
        # transitive closure of a helper over an input relation: h(X, Z) <= h(X, Y) & r(Y, Z)
        h2 = [p for p, n in helpers.items() if n == 2]
        rels = [p for p, n in gen.t.inputs.items() if n == 2]
        if h2 and rels and len(prog) < MAX_RULES:
            p, r = rnd.choice(h2), rnd.choice(rels)
            prog.append(((p, ("X", "Z")), (("+", (p, ("X", "Y"))), ("+", (r, ("Y", "Z"))))))
    return tuple(prog), op


def crossover(a, b, gen, rnd):
    """body-level crossover: a rule of a gets part of its body replaced by literals of a rule of b, b's variables unified with a's
    variables of the same type; helper rules travel with the literals that use them"""
    if not a or not b:
        return a or b
    i, j = rnd.randrange(len(a)), rnd.randrange(len(b))
    ra, rb = a[i], b[j]
    ha, hb = helpers_of(a), helpers_of(b)
    vta, vtb = gen.var_types(ra, ha), gen.var_types(rb, hb)
    m = {}
    for v, t in vtb.items():
        same = [x for x, tx in vta.items() if tx == t and x not in m.values()]
        m[v] = rnd.choice(same) if same and rnd.random() < 0.8 else f"{v}b"
    take = [l for l in rb[1] if rnd.random() < 0.5] or [rnd.choice(rb[1])]
    keep = [l for l in ra[1] if rnd.random() < 0.5]

    def ren(l):
        if l[0] == "!=":
            return ("!=", m.get(l[1], l[1]), m.get(l[2], l[2]))
        return (l[0], (l[1][0], tuple(m.get(x, x) for x in l[1][1])))
    new = (ra[0], tuple(keep + [ren(l) for l in take])[:MAX_BODY])
    out = list(a[:i]) + [new] + list(a[i + 1:])
    need = {l[1][0] for l in new[1] if l[0] != "!=" and l[1][0].startswith("inv")}
    out += [r for r in b if r[0][0] in need and r[0][0] not in ha]
    return tuple(out[:MAX_RULES])


# ── evaluation, lexicase, the search ───────────────────────────────────────────────────────────────────────────────────────────
class Search:
    def __init__(self, task, seed, budget, start=None):
        self.t, self.rnd, self.budget = task, random.Random(f"gp:{task.name}:{seed}"), budget
        self.gen = Gen(task, self.rnd)
        self.cache, self.evals, self.verified = {}, 0, {}
        self.archive = {}  # size -> (mean F1, program): best fit per size (accuracy vs shortness)
        self.solutions, self.cex_added, self.lineage = {}, 0, {}
        self.start = start or []

    def cases(self, prog):
        k = render(prog)
        if k not in self.cache:
            self.evals += 1
            vec = []
            for w, g in zip(self.t.train, self.t.gold):
                got = E.answers(k, w, self.t.answers)
                if got is None:
                    vec = [0.0] * len(self.t.train); break
                tp = len(got & g)
                vec.append(1.0 if got == g else (0.0 if tp == 0 else 2 * tp / (len(got) + len(g))) * 0.99)
            self.cache[k] = vec
        return self.cache[k]

    def verify(self, prog):
        k = render(prog)
        if k in self.verified:  # each program is checked against the domain once (it was repeated every generation)
            return self.verified[k]
        self.verified[k] = self._verify(k)
        return self.verified[k]

    def _verify(self, k):
        for w, g in zip(self.t.verify, self.t.verify_gold):
            if E.answers(k, w, self.t.answers) != g:
                return w
        for w, g in zip(self.t.stress, self.t.stress_gold):
            if E.answers(k, w, self.t.answers) != g:
                return w  # a stress world is a counterexample too (it holds distinctions the small domain lacks)
        return None

    def note(self, prog, vec):
        s = size(prog); f = sum(vec) / len(vec)
        if s not in self.archive or f > self.archive[s][0]:
            self.archive[s] = (f, prog)
        if all(x == 1.0 for x in vec):
            res = self.verify(prog)
            if res is None:
                self.solutions.setdefault(render(prog), {"size": s, "evals": self.evals, "program": render(prog)})
            else:
                # counterexample-guided: the first failing domain world joins the training worlds; the cache is cleared
                self.t.train.append(res); self.t.gold.append(E.answers(self.t.ref, res, self.t.answers))
                self.cache.clear(); self.cex_added += 1

    def lexicase(self, pop, vecs):
        cand = list(range(len(pop)))
        order = list(range(len(vecs[0])))
        self.rnd.shuffle(order)
        for c in order:
            best = max(vecs[k][c] for k in cand)
            cand = [k for k in cand if vecs[k][c] == best]
            if len(cand) == 1:
                break
        # ties: the shorter program (parsimony)
        m = min(size(pop[k]) for k in cand)
        return pop[self.rnd.choice([k for k in cand if size(pop[k]) == m])]

    def run(self):
        pop = []
        for s in self.start:
            pop.append(canon(s))
        while len(pop) < POP:
            r = self.gen.new_rule({})
            if r:
                pop.append(canon((r,)))
        t0 = time.time()
        gens, first = 0, None
        while self.evals < self.budget:
            pop = [p for p in pop if p] or [canon((self.gen.new_rule({}) or ((list(self.t.answers)[0], ()), ()),))]
            vecs = []
            for p in pop:
                v = self.cases(p)
                if len(v) != len(self.t.train):  # training worlds grew (a counterexample): re-evaluate
                    self.cache.pop(render(p), None); v = self.cases(p)
                vecs.append(v); self.note(p, v)
            if self.solutions:
                first = first if first is not None else gens
                if gens - first >= AFTER_SOLVE:
                    break  # AFTER_SOLVE generations spent looking for a shorter exact program
            nxt = sorted(pop, key=lambda p: (-sum(self.cases(p)), size(p)))[:5]  # elitism
            seen = {render(p) for p in nxt}
            tries = 0
            while len(nxt) < POP:
                tries += 1
                a = self.lexicase(pop, vecs)
                if self.rnd.random() < 0.3:
                    b = self.lexicase(pop, vecs)
                    child = crossover(a, b, self.gen, self.rnd)
                else:
                    child = a
                for _ in range(self.rnd.randint(1, 2)):
                    child, _op = mutate(child, self.gen, self.rnd)
                child = canon(child)
                if not child or render(child) in seen:
                    if tries > 4 * POP:  # the population collapsed onto duplicates: immigrants (fresh random rules) keep it diverse
                        r = self.gen.new_rule({})
                        child = canon((r,)) if r else None
                    if not child or render(child) in seen:
                        continue
                seen.add(render(child)); nxt.append(child)
            pop = nxt; gens += 1
            if gens % 10 == 0:
                best = max(self.archive.values(), key=lambda x: x[0])[0] if self.archive else 0
                print(f"gen {gens} evals {self.evals} best {best:.3f} solutions {len(self.solutions)} cex {self.cex_added} "
                      f"{time.time() - t0:.0f}s", file=sys.stderr, flush=True)
            if self.evals >= self.budget or gens >= MAX_GENS:
                break
        best = min(self.solutions.values(), key=lambda x: x["size"]) if self.solutions else None
        return {"solved": best is not None, "best": best, "n_solutions": len(self.solutions), "evals": self.evals,
                "generations": gens, "cex_added": self.cex_added, "seconds": round(time.time() - t0, 1),
                "archive": {s: {"fit": round(f, 4), "program": render(p)} for s, (f, p) in sorted(self.archive.items())[:12]},
                "solutions": sorted(self.solutions.values(), key=lambda x: x["size"])[:10]}


def graph(task, seed, res):
    """the product: mechanism objects and their edges, each edge with its evidence"""
    nodes, edges = [], []
    sols = res["solutions"]
    for s in sols:
        mid = "mechanism:" + hashlib.sha256(s["program"].encode()).hexdigest()[:16]
        nodes.append({"id": mid, "kind": "mechanism", "program": s["program"], "size": s["size"],
                      "proof": {"domain_worlds": len(task.verify), "stress_worlds": STRESS_N, "equivalent_to_reference": True},
                      "found_at_eval": s["evals"], "built_for": f"task:{task.name}"})
        edges.append({"a": mid, "b": f"task:{task.name}", "kind": "solves", "evidence": f"exact on {len(task.verify)} domain worlds"})
    for x in range(len(sols)):
        for y in range(x + 1, len(sols)):
            ma, mb = nodes[x]["id"], nodes[y]["id"]
            edges.append({"a": ma, "b": mb, "kind": "equivalent_to", "evidence": "same answers on every domain and stress world"})
            if sols[x]["size"] < sols[y]["size"]:
                edges.append({"a": ma, "b": mb, "kind": "simpler_than", "evidence": f"size {sols[x]['size']} < {sols[y]['size']}"})
    return nodes, edges


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task"); ap.add_argument("seed", type=int); ap.add_argument("out")
    ap.add_argument("--budget", type=int, default=20000)
    o = ap.parse_args()
    task = Task(o.task, o.seed)
    res = Search(task, o.seed, o.budget).run()
    res.update({"task": o.task, "seed": o.seed, "budget": o.budget, "verify_worlds": len(task.verify)})
    nodes, edges = graph(task, o.seed, res)
    json.dump(res, open(f"{o.out}/{o.task}_{o.seed}.json", "w"), indent=1)
    with open(f"{o.out}/{o.task}_{o.seed}.graph.jsonl", "w") as f:
        for x in nodes + edges:
            f.write(json.dumps(x) + "\n")
    print(json.dumps({k: res[k] for k in ("task", "seed", "solved", "evals", "generations", "cex_added", "seconds")}),
          (res["best"] or {}).get("program", "").replace("\n", " | "))

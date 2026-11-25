"""G8d step 0 — gp2 with an edit log (logging only). Every child attempt: generation, evaluation counter, parent, crossover partner,
the mutate() calls as (operator, rule index), the canonical child, immigrant flag, accepted flag. mutate() and run() are copies of gp2
with identical RNG calls; the test is a bit-identical replay of stored G8b-1 runs (replay_check.py).
usage: gp2_log.py TASK ARM SEED OUTDIR [--budget N]"""
import argparse, json, random, sys, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "g8b"))
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "..", "blind_tasks"))
import gp2 as gp  # noqa: E402
import arms2  # noqa: E402
gp.T = __import__("blind_tasks")
arms2.gp.T = gp.T


def mutate(prog, gen, rnd):  # copy of gp2.mutate: identical RNG calls, returns the rule index too
    prog = list(prog)
    helpers = gp.helpers_of(prog)
    ops = ["add_rule", "add_lit", "add_neg", "add_neq", "del_lit", "del_rule", "flip", "const", "var", "pred", "invent", "recurse"]
    op = rnd.choice(ops) if prog else "add_rule"
    i = rnd.randrange(len(prog)) if prog else 0
    if op == "add_rule" and len(prog) < gp.MAX_RULES:
        r = gen.new_rule(helpers)
        if r:
            prog.append(r)
    elif op in ("add_lit", "add_neg") and prog and len(prog[i][1]) < gp.MAX_BODY:
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
    elif op == "invent" and prog and len(helpers) < gp.HELPERS and len(prog) < gp.MAX_RULES:
        # abstraction: a part of a rule's positive body becomes a new helper predicate over the variables it shares with the rest
        h, b = prog[i]
        pos = [l for l in b if l[0] == "+"]
        if len(pos) >= 2:
            part = rnd.sample(pos, rnd.randint(1, len(pos) - 1))
            rest = [l for l in b if l not in part]
            pv = [a for l in part for a in l[1][1] if gp.is_var(a)]
            ov = set(a for a in h[1] if gp.is_var(a)) | {a for l in rest for a in ((l[1], l[2]) if l[0] == "!=" else l[1][1]) if gp.is_var(a)}
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
        if h2 and rels and len(prog) < gp.MAX_RULES:
            p, r = rnd.choice(h2), rnd.choice(rels)
            prog.append(((p, ("X", "Z")), (("+", (p, ("X", "Y"))), ("+", (r, ("Y", "Z"))))))
    return tuple(prog), op, i



class LoggedSearch(gp.Search):
    log: list

    def run(self):
        self.log = []
        pop = []
        for s in self.start:
            pop.append(gp.canon(s))
        have = {gp.render(p) for p in pop}
        tries = 0
        while len(pop) < gp.POP and tries < 50 * gp.POP:  # gp2: deduplicated refill
            tries += 1
            r = self.gen.new_rule({})
            c = gp.canon((r,)) if r else ()
            if c and gp.render(c) not in have:
                have.add(gp.render(c)); pop.append(c); self.origin.setdefault(gp.render(c), "refill")
        t0 = time.time()
        gens, first = 0, None
        while self.evals < self.budget:
            pop = [p for p in pop if p] or [gp.canon((self.gen.new_rule({}) or ((list(self.t.answers)[0], ()), ()),))]
            vecs = []
            for p in pop:
                v = self.cases(p)
                if len(v) != len(self.t.train):  # training worlds grew (a counterexample): re-evaluate
                    self.cache.pop(gp.render(p), None); v = self.cases(p)
                vecs.append(v); self.note(p, v)
            if self.solutions:
                first = first if first is not None else gens
                if gens - first >= self.after_solve:
                    break  # AFTER_SOLVE generations spent looking for a shorter exact program
            nxt = sorted(pop, key=lambda p: (-sum(self.cases(p)), gp.size(p)))[:5]  # elitism
            seen = {gp.render(p) for p in nxt}
            tries = 0
            while len(nxt) < gp.POP:
                tries += 1
                parent = None; ops = []; xo = None
                a = self.lexicase(pop, vecs)
                if self.rnd.random() < 0.3:
                    b = self.lexicase(pop, vecs)
                    child = gp.crossover(a, b, self.gen, self.rnd); xo = gp.render(b)
                    parent = a
                else:
                    child = a
                    parent = a
                for _ in range(self.rnd.randint(1, 2)):
                    child, _op, _i = mutate(child, self.gen, self.rnd); ops.append([_op, _i])
                child = gp.canon(child)
                rec = {'g': gens, 'e': self.evals, 'p': gp.render(a), 'x': xo, 'ops': ops, 'c': gp.render(child) if child else None, 'imm': False, 'acc': False}
                if not child or gp.render(child) in seen:
                    if tries > 4 * gp.POP:  # the population collapsed onto duplicates: immigrants (fresh random rules) keep it diverse
                        r = self.gen.new_rule({})
                        child = gp.canon((r,)) if r else None
                        parent = None; rec['imm'] = True  # review 2, fix 5: an immigrant has no parent (was labelled with a library origin)
                    if not child or gp.render(child) in seen:
                        self.log.append(rec)
                        continue
                seen.add(gp.render(child)); nxt.append(child); rec['acc'] = True
                self.log.append(rec)
                self.origin.setdefault(gp.render(child), self.origin.get(gp.render(parent), "?") if parent is not None else "immigrant")
            pop = nxt; gens += 1
            if gens % 10 == 0:
                best = max(self.archive.values(), key=lambda x: x[0])[0] if self.archive else 0
                print(f"gen {gens} evals {self.evals} best {best:.3f} solutions {len(self.solutions)} cex {self.cex_added} "
                      f"{time.time() - t0:.0f}s", file=sys.stderr, flush=True)
            if self.evals >= self.budget or gens >= gp.MAX_GENS:
                break
        best = min(self.solutions.values(), key=lambda x: x["size"]) if self.solutions else None
        return {"solved": best is not None, "best": best, "n_solutions": len(self.solutions), "evals": self.evals,
                "generations": gens, "cex_added": self.cex_added, "seconds": round(time.time() - t0, 1),
                "archive": {s: {"fit": round(f, 4), "program": gp.render(p)} for s, (f, p) in sorted(self.archive.items())[:12]},
                "solutions": sorted(self.solutions.values(), key=lambda x: x["size"])[:10]}




if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task"); ap.add_argument("arm"); ap.add_argument("seed", type=int); ap.add_argument("out")
    ap.add_argument("--budget", type=int, default=15000)
    o = ap.parse_args()
    task = gp.Task(o.task, o.seed)
    stem = f"{o.out}/{o.task}_{o.arm}_{o.seed}"
    search = LoggedSearch(task, o.seed, o.budget, after_solve=0, on_first=lambda rec: None)
    search.log = []
    rnd = random.Random(f"start:{o.task}:{o.arm}:{o.seed}")
    t0 = time.time()
    arms2.REWIRE_KEPT.update(rules=0, unchanged=0)
    pop, stats = arms2.start(task, search, o.arm, rnd, arms2.library())
    first_in_start = bool(search.solutions)
    search.budget = stats["start_evals"] + o.budget
    search.start = pop
    res = search.run() if not first_in_start else {"solved": True, "evals": search.evals, "solutions": list(search.solutions.values())}
    firsts = sorted(search.solutions.values(), key=lambda x: x["evals"])
    res.update({"task": o.task, "arm": o.arm, "seed": o.seed, "budget": o.budget, "start": stats, "first_in_start": first_in_start,
                "first_solution": firsts[0] if firsts else None,
                "search_cost": (firsts[0]["evals"] - stats["start_evals"]) if firsts and not first_in_start else None,
                "seconds_total": round(time.time() - t0, 1)})
    json.dump(res, open(stem + ".json", "w"), indent=1, default=str)
    with open(stem + ".edits.jsonl", "w") as f:
        for rec in search.log:
            f.write(json.dumps(rec) + "\n")
    json.dump({"train": task.train, "gold": [sorted(map(list, g)) if g else [] for g in task.gold], "cex_added": search.cex_added,
               "start_programs": [gp.render(p) for p in pop]}, open(stem + ".worlds.json", "w"), default=str)
    print(json.dumps({k: res[k] for k in ("task", "arm", "seed", "solved", "first_in_start", "search_cost", "seconds_total")}), len(search.log))

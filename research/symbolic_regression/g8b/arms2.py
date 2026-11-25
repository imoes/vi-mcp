"""G8b-1 start sources, version 2 (after Fable's review of the draft: S4, S5, S8, S9). The arms differ ONLY in where the start
candidates come from; every arm then runs the same gp2.Search.
  L   library mechanisms: a rule of a library block plus (p = 0.5) the block rules defining its body predicates, mapped onto the task:
      undefined body predicates -> task inputs (same arity preferred, else a fixed projection per (predicate, arity)); the seed rule's
      head -> a task answer; every other defined head -> an invented helper inv1..; library constants -> fresh variables.
  XR  library rewired: per rule the same predicates, signs, length and number of distinct variables, argument slots reassigned at
      random (rejection until the rule is safe) — the wiring INSIDE rules is destroyed, everything else kept; then mapped like L.
  XL  library relinked: rules intact, but every body reference to a helper defined in the block is replaced by the head of a rule of
      ANOTHER block with the same arity, and that rule travels along — the wiring BETWEEN rules is destroyed.
  Z   random rules over the task vocabulary.
Equal start: every arm draws until it holds K distinct non-empty canonical programs (at most MAX_DRAWS draws), evaluates them (counted
in the budget, reported as start_evals) and starts the search from the best POP. Re-seeded per (task, arm, seed).
Records: first solution at once (first.json), whether it was a start candidate, its lineage origin, start-phase statistics.
usage: arms2.py TASK ARM SEED OUTDIR [--budget N]"""
import argparse, json, os, random, sys, time

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
import gp2 as gp  # noqa: E402
import grade  # noqa: E402

K, MAX_DRAWS = 200, 20000


def library():
    """[(block id, [gp rules])]: safe rules of the three packages without nested terms (deontic heads like forbidden(confirm(I, S)))"""
    from clingo_object import philosophy as ph
    out = []
    for name in ("kollektiv", "messung", "code"):
        pkg = ph.load(name)
        for b, rs in ph.blocks(pkg["seed"])[0]:
            rules = []
            for x in rs:
                r = grade.parse(x) if x.strip() else None
                if not r or not gp.safe(r):
                    continue
                atoms = [r[0]] + [l[1] for l in r[1] if l[0] != "!="]
                if any("(" in a for at in atoms for a in at[1]):
                    continue  # nested term: not an atom the mapping can handle
                rules.append(r)
            if rules:
                out.append((f"{name}:{b}", rules))
    return out


REWIRE_KEPT = {"rules": 0, "unchanged": 0}


def _rewire(rule, rnd):
    """permute the rule's variable OCCURRENCES across its variable slots (the multiset of variables is kept, so the variable count is
    kept); reject unsafe candidates, a repeated variable inside one atom, X != X, or the original wiring (canonically equal)"""
    (hp, ha), body = rule
    slots = [("h", i) for i, a in enumerate(ha) if gp.is_var(a)]
    for j, l in enumerate(body):
        args = (l[1], l[2]) if l[0] == "!=" else l[1][1]
        slots += [(j, i) for i, a in enumerate(args) if gp.is_var(a)]

    def val(s):
        if s[0] == "h":
            return ha[s[1]]
        l = body[s[0]]
        return ((l[1], l[2]) if l[0] == "!=" else l[1][1])[s[1]]
    occ = [val(s) for s in slots]
    orig = gp.canon_rule(rule)
    for _ in range(200):
        perm = occ[:]; rnd.shuffle(perm)
        m = dict(zip(slots, perm))
        h2 = (hp, tuple(m.get(("h", i), a) for i, a in enumerate(ha)))
        b2 = []
        for j, l in enumerate(body):
            if l[0] == "!=":
                b2.append(("!=", m.get((j, 0), l[1]), m.get((j, 1), l[2])))
            else:
                b2.append((l[0], (l[1][0], tuple(m.get((j, i), a) for i, a in enumerate(l[1][1])))))
        cand = (h2, tuple(b2))
        atoms = [h2] + [l[1] for l in b2 if l[0] != "!="]
        if any(len([a for a in at[1] if gp.is_var(a)]) != len({a for a in at[1] if gp.is_var(a)}) for at in atoms):
            continue
        if any(l[0] == "!=" and l[1] == l[2] for l in b2):
            continue
        if gp.safe(cand) and gp.canon_rule(cand) != orig:
            return cand
    return None


def rewired(lib, rnd):
    out = []
    for b, rules in lib:
        new = []
        for r in rules:
            REWIRE_KEPT["rules"] += 1
            c = _rewire(r, rnd)
            if c is None:  # no admissible rewiring (e.g. a one-variable rule): kept unchanged, counted
                REWIRE_KEPT["unchanged"] += 1
                c = r
            new.append(c)
        out.append((b + "~rewired", new))
    return out


def relinked(lib, rnd):
    heads_by_arity = {}
    for b, rules in lib:
        for r in rules:
            heads_by_arity.setdefault(len(r[0][1]), []).append((b, r))
    out = []
    for b, rules in lib:
        defined = {r[0][0] for r in rules}
        new, extra = [], []
        for h, body in rules:
            nb = []
            for l in body:
                if l[0] != "!=" and l[1][0] in defined and l[1][0] != h[0]:
                    pool = [(ob, orr) for ob, orr in heads_by_arity.get(len(l[1][1]), []) if ob != b]
                    if pool:
                        ob, orr = rnd.choice(pool)
                        nb.append((l[0], (orr[0][0], l[1][1]))); extra.append(orr); continue
                nb.append(l)
            new.append((h, tuple(nb)))
        out.append((b + "~relinked", new + extra))
    return out


def mapped_chunk(block, task, rnd):
    _bid, rules = block
    seed = rnd.choice(rules)
    chunk = [seed]
    body_preds = {l[1][0] for l in seed[1] if l[0] != "!="}
    if rnd.random() < 0.5:
        chunk += [r for r in rules if r is not seed and r[0][0] in body_preds][:gp.MAX_RULES - 1]
    heads = list(dict.fromkeys(r[0][0] for r in chunk))
    pmap, arity_of = {}, {}
    ans = rnd.choice(list(task.answers))
    pmap[(seed[0][0], len(seed[0][1]))] = ans; arity_of[ans] = task.answers[ans]
    k = 0
    for r in chunk:  # helpers: every other defined head (by name AND arity) -> inv1, inv2, ...
        key = (r[0][0], len(r[0][1]))
        if key not in pmap:
            k += 1; pmap[key] = f"inv{k}"; arity_of[f"inv{k}"] = len(r[0][1])
    inputs = list(task.inputs)
    for r in chunk:
        for l in r[1]:
            if l[0] != "!=":
                key = (l[1][0], len(l[1][1]))
                if key not in pmap:
                    same = [q for q in inputs if task.inputs[q] == key[1]]
                    q = rnd.choice(same or inputs); pmap[key] = q; arity_of[q] = task.inputs[q]
    proj, fresh = {}, iter(range(10 ** 6))

    def tr(a):
        key = (a[0], len(a[1]))
        q = pmap.get(key)
        if q is None:
            return a
        n = arity_of[q]
        args = tuple(x if gp.is_var(x) else f"K{next(fresh)}" for x in a[1])  # library constants -> fresh variables
        if n == len(args):
            return (q, args)
        if key not in proj:  # one projection per (predicate, arity)
            proj[key] = rnd.sample(range(len(args)), min(len(args), n))
        idx = proj[key]
        return (q, tuple([args[i] for i in idx] + [f"F{next(fresh)}" for _ in range(n - len(idx))]))
    prog = tuple((tr(h), tuple(l if l[0] == "!=" else (l[0], tr(l[1])) for l in b)) for h, b in chunk)
    return gp.canon(prog)


def start(task, search, arm, rnd, lib):
    src = {"L": lib, "XR": rewired(lib, rnd), "XL": relinked(lib, rnd)}.get(arm)
    found, draws = {}, 0
    while len(found) < K and draws < MAX_DRAWS:
        draws += 1
        if arm == "Z":
            r = search.gen.new_rule({})
            prog, origin = (gp.canon((r,)) if r else ()), "random"
        else:
            block = rnd.choice(src)
            prog, origin = mapped_chunk(block, task, rnd), block[0]
        if prog and gp.render(prog) not in found:
            found[gp.render(prog)] = (prog, origin)
    for k, (prog, origin) in found.items():
        search.origin[k] = origin
        search.note(prog, search.cases(prog))
    # review 2, fix 4: a counterexample found in the start phase grows the training worlds — rank every start program on the FINAL
    # training worlds (the cache is cleared by a counterexample, so these re-evaluations are billed to the start phase, not to O2)
    cands = []
    for k, (prog, _origin) in found.items():
        v = search.cases(prog)
        cands.append((sum(v) / len(v), -gp.size(prog), prog))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    pop = [c[2] for c in cands[:gp.POP]]
    progs = [p for p, _o in found.values()]
    stats = {"draws": draws, "distinct": len(found), "start_evals": search.evals,
             "mean_rules": round(sum(len(p) for p in progs) / max(1, len(progs)), 2),
             "mean_size": round(sum(gp.size(p) for p in progs) / max(1, len(progs)), 2),
             "share_recursive": round(sum(any(l[0] != "!=" and l[1][0] == h[0] for h, b in p for l in b) for p in progs) / max(1, len(progs)), 3),
             "share_helper": round(sum(any(h[0].startswith("inv") for h, _b in p) for p in progs) / max(1, len(progs)), 3),
             "share_repeated_var": round(sum(any(len([a for a in at[1] if gp.is_var(a)]) != len({a for a in at[1] if gp.is_var(a)})
                                                  for h, b in p for at in [h] + [l[1] for l in b if l[0] != "!="]) for p in progs)
                                         / max(1, len(progs)), 3)}
    return pop, stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task"); ap.add_argument("arm"); ap.add_argument("seed", type=int); ap.add_argument("out")
    ap.add_argument("--budget", type=int, default=15000)
    o = ap.parse_args()
    gp.T = __import__("blind_tasks")
    task = gp.Task(o.task, o.seed)
    stem = f"{o.out}/{o.task}_{o.arm}_{o.seed}"

    def first(rec):
        json.dump(rec, open(stem + ".first.json", "w"), indent=1)  # written at once (a later kill cannot lose it)
    search = gp.Search(task, o.seed, o.budget, after_solve=0, on_first=first)
    rnd = random.Random(f"start:{o.task}:{o.arm}:{o.seed}")
    t0 = time.time()
    REWIRE_KEPT.update(rules=0, unchanged=0)
    pop, stats = start(task, search, o.arm, rnd, library())
    stats["rewire_unchanged"] = dict(REWIRE_KEPT) if o.arm == "XR" else None
    first_in_start = bool(search.solutions)
    json.dump({"start": stats, "first_in_start": first_in_start}, open(stem + ".start.json", "w"), indent=1)  # fix 4: at once
    search.budget = stats["start_evals"] + o.budget  # review 2, fix 3: the same SEARCH budget after the start phase in every arm
    search.start = pop
    res = search.run() if not first_in_start else {"solved": True, "evals": search.evals, "solutions": list(search.solutions.values())}
    firsts = sorted(search.solutions.values(), key=lambda x: x["evals"])
    res.update({"task": o.task, "arm": o.arm, "seed": o.seed, "budget": o.budget, "start": stats,
                "first_solution": firsts[0] if firsts else None, "first_in_start": first_in_start,
                "search_cost": (firsts[0]["evals"] - stats["start_evals"]) if firsts and not first_in_start else None,
                "none_evals": getattr(search, "none_evals", 0), "timeouts": getattr(search, "timeouts", 0),
                "seconds_total": round(time.time() - t0, 1)})
    json.dump(res, open(stem + ".json", "w"), indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("task", "arm", "seed", "solved", "first_in_start", "search_cost", "seconds_total")}),
          json.dumps(stats))

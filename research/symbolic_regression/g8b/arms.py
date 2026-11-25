"""G8b-1 start sources — the ONLY difference between the arms (every arm then runs the same gp.Search with the same operators):
  L  library mechanisms: a rule of a library block plus (p = 0.5) the block rules defining its body predicates, mapped onto the task
     vocabulary (body predicates the chunk does not define -> task inputs of the same arity, or a projection; the seed rule's head ->
     a task answer; other defined heads -> invented helpers inv1..inv3);
  X  the scrambled library: the same library rules, but every body literal is replaced by one drawn from the whole library's literal
     pool with the same arity and sign — rule lengths, arities, signs and != counts are kept, the wiring between rules is destroyed;
     then mapped exactly like L;
  Z  random rules over the task vocabulary (gp.Gen.new_rule).
Each arm draws INIT candidates from its source, evaluates them (counted in the budget) and starts from the best POP.
usage: arms.py TASK ARM SEED OUTDIR [--budget N]"""
import argparse, json, os, random, sys, time

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
import gp  # noqa: E402
import grade  # noqa: E402

INIT = 1000


def library():
    """[(block id, [gp rules])] of the three philosophy packages (safe rules only)."""
    from clingo_object import philosophy as ph
    out = []
    for name in ("kollektiv", "messung", "code"):
        pkg = ph.load(name)
        for b, rs in ph.blocks(pkg["seed"])[0]:
            rules = [r for r in (grade.parse(x) for x in rs if x.strip()) if r and gp.safe(r)]
            if rules:
                out.append((f"{name}:{b}", rules))
    return out


def scrambled(lib, rnd):
    """same rules, body literals redrawn from the library-wide pool of the same (sign, arity) — wiring destroyed"""
    pool = {}
    for _b, rules in lib:
        for _h, body in rules:
            for l in body:
                if l[0] != "!=":
                    pool.setdefault((l[0], len(l[1][1])), []).append(l)
    out = []
    for b, rules in lib:
        new = []
        for h, body in rules:
            nb = tuple(l if l[0] == "!=" else rnd.choice(pool[(l[0], len(l[1][1]))]) for l in body)
            new.append((h, nb))
        out.append((b + "~x", new))
    return out


def project(atom, target, arity, rnd, fresh):
    """atom of the library -> target predicate with `arity` arguments chosen from the atom's arguments (fresh variables if short)"""
    args = list(atom[1])
    pick = rnd.sample(args, min(len(args), arity)) + [f"F{next(fresh)}" for _ in range(max(0, arity - len(args)))]
    rnd.shuffle(pick)
    return (target, tuple(pick))


def mapped_chunk(block, task, rnd):
    _bid, rules = block
    seed = rnd.choice(rules)
    chunk = [seed]
    body_preds = {l[1][0] for l in seed[1] if l[0] != "!="}
    if rnd.random() < 0.5:
        chunk += [r for r in rules if r is not seed and r[0][0] in body_preds][:gp.MAX_RULES - 1]
    heads = {r[0][0] for r in chunk}
    counter = iter(range(10 ** 6))
    # predicate mapping, consistent over the chunk
    pmap, amap = {}, {}
    helpers = [p for p in dict.fromkeys(r[0][0] for r in chunk) if p != seed[0][0]][:gp.HELPERS]
    for i, p in enumerate(helpers, 1):
        pmap[p] = f"inv{i}"
    ans = rnd.choice(list(task.answers))
    pmap[seed[0][0]] = ans; amap[seed[0][0]] = task.answers[ans]
    inputs = list(task.inputs)
    for r in chunk:
        for l in r[1]:
            if l[0] != "!=" and l[1][0] not in heads and l[1][0] not in pmap:
                same = [q for q in inputs if task.inputs[q] == len(l[1][1])]
                q = rnd.choice(same or inputs)
                pmap[l[1][0]] = q; amap[l[1][0]] = task.inputs[q]
    for p in helpers:
        amap[p] = None  # helpers keep their arity (at most 2 used by gp's recurse; any arity is fine for evaluation)
    proj = {}

    def tr(a):
        p = a[0]
        if p not in pmap:
            return a
        if amap.get(p) is None or amap[p] == len(a[1]):
            return (pmap[p], a[1])
        key = p
        if key not in proj:  # one projection per predicate, consistent over the chunk
            proj[key] = rnd.sample(range(len(a[1])), min(len(a[1]), amap[p]))
        idx = proj[key]
        args = [a[1][i] for i in idx] + [f"F{next(counter)}" for _ in range(amap[p] - len(idx))]
        return (pmap[p], tuple(args))
    prog = tuple((tr(h), tuple(l if l[0] == "!=" else (l[0], tr(l[1])) for l in b)) for h, b in chunk)
    return gp.canon(prog)


def start(task, search, arm, rnd, lib):
    src = lib if arm == "L" else scrambled(lib, random.Random(f"x:{task.name}")) if arm == "X" else None
    cands = []
    for _ in range(INIT):
        if arm == "Z":
            r = search.gen.new_rule({})
            prog = gp.canon((r,)) if r else ()
            origin = "random"
        else:
            block = rnd.choice(src)
            prog = mapped_chunk(block, task, rnd)
            origin = block[0]
        if not prog:
            continue
        v = search.cases(prog)
        search.note(prog, v)
        cands.append((sum(v), -gp.size(prog), prog, origin))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    seen, pop, origins = set(), [], {}
    for _f, _s, prog, origin in cands:
        k = gp.render(prog)
        if k not in seen:
            seen.add(k); pop.append(prog); origins[k] = origin
        if len(pop) == gp.POP:
            break
    return pop, origins


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task"); ap.add_argument("arm"); ap.add_argument("seed", type=int); ap.add_argument("out")
    ap.add_argument("--budget", type=int, default=20000)
    o = ap.parse_args()
    gp.T = __import__("blind_tasks")  # the blind benchmark replaces the G8 tasks
    task = gp.Task(o.task, o.seed)
    search = gp.Search(task, o.seed, o.budget)
    rnd = random.Random(f"start:{o.task}:{o.arm}:{o.seed}")
    t0 = time.time()
    pop, origins = start(task, search, o.arm, rnd, library())
    search.start = pop
    res = search.run()
    sol_origin = None
    if res["best"]:
        sol_origin = origins.get(res["best"]["program"])
    res.update({"task": o.task, "arm": o.arm, "seed": o.seed, "budget": o.budget, "init": INIT, "start_origins_top5":
                sorted(set(origins.values()))[:5], "solution_was_start_candidate": sol_origin, "seconds_total": round(time.time() - t0, 1)})
    json.dump(res, open(f"{o.out}/{o.task}_{o.arm}_{o.seed}.json", "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("task", "arm", "seed", "solved", "evals", "generations", "seconds_total")}))

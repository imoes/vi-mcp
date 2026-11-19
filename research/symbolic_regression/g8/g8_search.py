"""G8 search (prereg_G8.md): a steady-state evolutionary search over clingo-object rule sets; the solver on the training worlds is
the fitness. Arms differ ONLY in the start population and, for S, in the operators:
  L — library blocks (kollektiv P1–P13, messung M1–M6, code P1–P7), each with a random structure-preserving predicate mapping onto
      the task vocabulary (exaptation);
  Z — random rules over the task vocabulary (control);
  T — only the library block nearest to the task description by text (bge-m3), with random mappings (the text baseline);
  S — library blocks, but the only operator is a re-mapping of one predicate (pure structural transfer, no other mutation).
usage: g8_search.py TASK ARM SEED OUT.json"""
import ast, json, random, re, sys, time

sys.path.insert(0, os.environ.get("VI_MCP_REPO") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from clingo_object import philosophy as ph  # noqa: E402
import g8_eval as E  # noqa: E402
import g8_tasks as T  # noqa: E402

POP, BUDGET, TRAIN_N, HELD_N, TOURN, SIZE_COST = 40, int(__import__("os").environ.get("G8_BUDGET", 10000)), 30, 50, 3, 0.001
INIT = 3000  # start-phase evaluations (part of BUDGET), every arm alike
VAR = re.compile(r"^[A-Z_][A-Za-z0-9_]*$")


# ── representation: rule = (head atom, [literals]); atom = (pred, [arg strings]); literal = ("pos"|"neg", atom) | ("cmp", op, a, b)
def _atom(node):
    if isinstance(node, ast.Call):
        return (node.func.id, [ast.unparse(a) for a in node.args])
    if isinstance(node, ast.Name):
        return (node.id, [])
    raise ValueError(ast.dump(node))


def _lits(node, out):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
        _lits(node.left, out); _lits(node.right, out)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
        out.append(("neg", _atom(node.operand)))
    elif isinstance(node, ast.Compare):
        op = {ast.NotEq: "!=", ast.Eq: "==", ast.Lt: "<", ast.Gt: ">"}[type(node.ops[0])]
        out.append(("cmp", op, ast.unparse(node.left), ast.unparse(node.comparators[0])))
    else:
        out.append(("pos", _atom(node)))


def parse_rule(text):
    """A rule 'head <= body' -> (head, lits); facts and never(...) constraints -> None (they decide no answer atom)."""
    node = ast.parse(text, mode="eval").body
    if not (isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.LtE)):
        return None
    head = _atom(node.left)
    if head[0] == "never":
        return None
    lits = []
    _lits(node.comparators[0], lits)
    return (head, lits)


def render_atom(a):
    return f"{a[0]}({', '.join(a[1])})" if a[1] else a[0]


def render(rules):
    out = []
    for head, lits in rules:
        body = []
        for l in lits:
            body.append(f"({l[2]} {l[1]} {l[3]})" if l[0] == "cmp" else ("~" if l[0] == "neg" else "") + render_atom(l[1]))
        out.append(f"{render_atom(head)} <= {' & '.join(body)}" if body else render_atom(head))
    return "\n".join(out)


def size(rules):
    return sum(1 + len(l) for _, l in rules)


def library():
    blocks = []
    for name in ("kollektiv", "messung", "code"):
        pkg = ph.load(name)
        for b, rs in ph.blocks(pkg["seed"])[0]:
            rules = [r for r in (parse_rule(x) for x in rs if x.strip()) if r]
            if rules:
                blocks.append((f"{name}:{b}", rules))
    return blocks


def preds_of(rules):
    """pred -> arity, and the set of predicates defined by a head in these rules"""
    ar, heads = {}, set()
    for h, lits in rules:
        ar[h[0]] = len(h[1]); heads.add(h[0])
        for l in lits:
            if l[0] != "cmp":
                ar[l[1][0]] = len(l[1][1])
    return ar, heads


def vars_of(rule):
    h, lits = rule
    vs = [a for a in h[1] if VAR.match(a)]
    for l in lits:
        vs += [a for a in (l[1][1] if l[0] != "cmp" else [l[2], l[3]]) if VAR.match(a)]
    return list(dict.fromkeys(vs))


class Task:
    def __init__(self, name, seed):
        t = T.TASKS[name]
        self.name, self.inputs, self.answers, self.consts = name, t["inputs"], t["answers"], t["constants"]
        self.train = T.worlds(name, TRAIN_N, 1000 + seed)
        self.held = T.worlds(name, HELD_N, 5000 + seed)
        self.gold_train = [E.answers(t["REFERENCE"], w, self.answers) for w in self.train]  # the only use of the reference: gold atoms
        self.gold_held = [E.answers(t["REFERENCE"], w, self.answers) for w in self.held]
        self.target = {**self.inputs, **self.answers}


# ── operators ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def remap(rules, task, rnd, pred=None):
    """Replace one non-task predicate p everywhere by a task predicate q (inputs where p is only read, answers where p is defined),
    choosing which of p's argument positions fill q's (a structure-preserving projection); fresh variables fill missing places."""
    ar, heads = preds_of(rules)
    cands = [p for p in ar if p not in task.target]
    if not cands:
        return rules, None
    p = pred or rnd.choice(cands)
    pool = list(task.answers) if p in heads and rnd.random() < 0.6 else list(task.inputs)
    q = rnd.choice(pool)
    n, m = ar[p], task.target[q]
    pos = rnd.sample(range(n), min(n, m)) + [None] * max(0, m - n)
    rnd.shuffle(pos)
    k = [0]

    def tr(a):
        if a[0] != p:
            return a
        out = []
        for i in pos:
            if i is None:
                k[0] += 1
                out.append(f"V{k[0]}x")
            else:
                out.append(a[1][i])
        return (q, out)
    new = [(tr(h), [l if l[0] == "cmp" else (l[0], tr(l[1])) for l in lits]) for h, lits in rules]
    return new, f"map {p}/{n}->{q}/{m} {pos}"


def random_atom(task, rule, rnd, preds=None):
    preds = preds or task.inputs
    q = rnd.choice(list(preds)); vs = vars_of(rule) or ["X"]
    args = []
    for _ in range(task.target.get(q, preds.get(q, 1))):
        r = rnd.random()
        args.append(rnd.choice(task.consts) if task.consts and r < 0.15 else (rnd.choice(vs) if r < 0.8 else f"N{rnd.randint(1, 3)}"))
    return (q, args)


def mutate(rules, task, rnd, ops):
    rules = [(h, list(l)) for h, l in rules]
    op = rnd.choice(ops)
    if not rules:
        op = "add_rule"
    i = rnd.randrange(len(rules)) if rules else 0
    if op == "remap":
        return remap(rules, task, rnd)
    if op == "remap_target":
        return remap_target(rules, task, rnd)
    if op == "drop_lit" and rules[i][1]:
        rules[i][1].pop(rnd.randrange(len(rules[i][1])))
    elif op == "add_lit":
        rules[i][1].append(("neg" if rnd.random() < 0.25 else "pos", random_atom(task, rules[i], rnd)))
    elif op == "flip_neg":
        lits = [k for k, l in enumerate(rules[i][1]) if l[0] in ("pos", "neg")]
        if lits:
            k = rnd.choice(lits); l = rules[i][1][k]
            rules[i][1][k] = ("neg" if l[0] == "pos" else "pos", l[1])
    elif op == "add_neq":
        vs = vars_of(rules[i])
        if len(vs) >= 2:
            a, b = rnd.sample(vs, 2); rules[i][1].append(("cmp", "!=", a, b))
    elif op == "drop_rule" and len(rules) > 1:
        rules.pop(i)
    elif op == "dup_rule":
        rules.append((rules[i][0], list(rules[i][1])))
    elif op == "change_arg":
        h, lits = rules[i]
        atoms = [("h", None)] + [("l", k) for k, l in enumerate(lits) if l[0] != "cmp"]
        where, k = rnd.choice(atoms)
        a = h if where == "h" else lits[k][1]
        if a[1]:
            j = rnd.randrange(len(a[1])); vs = vars_of(rules[i]) or ["X"]
            new_arg = rnd.choice(task.consts) if task.consts and rnd.random() < 0.3 else rnd.choice(vs)
            a2 = (a[0], a[1][:j] + [new_arg] + a[1][j + 1:])
            if where == "h":
                rules[i] = (a2, lits)
            else:
                lits[k] = (lits[k][0], a2)
    elif op == "add_rule":
        head = random_atom(task, ((None, []), []), rnd, preds={**task.answers, "aux1": 1, "aux2": 2})
        rule = (head, [])
        for _ in range(rnd.randint(1, 3)):
            rule[1].append(("pos", random_atom(task, rule, rnd)))
        rules.append(rule)
    return rules, op


def repair(rules):
    """Safety repair (as the back-translation's repair loop does for syntax): a negated literal or comparison whose variables no
    positive literal binds is dropped; a rule whose head keeps an unbound variable is dropped. Applied to every individual alike."""
    out = []
    for h, lits in rules:
        bound = {a for l in lits if l[0] == "pos" for a in l[1][1] if VAR.match(a)}
        keep = [l for l in lits if l[0] == "pos"
                or (l[0] == "neg" and all(a in bound for a in l[1][1] if VAR.match(a)))
                or (l[0] == "cmp" and all(a in bound for a in (l[2], l[3]) if VAR.match(a)))]
        if all(a in bound for a in h[1] if VAR.match(a)):
            out.append((h, keep))
    return out


def crossover(a, b, rnd):
    if not a or not b:
        return a or b
    return [r for r in a if rnd.random() < 0.5] + [r for r in b if rnd.random() < 0.5] or [rnd.choice(a)]


# ── start populations ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def mapped_block(block, task, rnd):
    """A library block with every predicate that is not defined inside it mapped onto task inputs and one defined head mapped onto a
    task answer — a random full structure mapping (later remaps may change it)."""
    bid, rules = block
    ar, heads = preds_of(rules)
    note = []
    for p in [p for p in ar if p not in heads and p not in task.target]:
        rules, m = remap(rules, task, rnd, pred=p)
        note.append(m)
    hs = [p for p in preds_of(rules)[1] if p not in task.target]
    if hs:
        p = rnd.choice(hs)
        for _ in range(5):  # a head mapped onto an answer
            new, m = remap(rules, task, rnd, pred=p)
            if m and m.split("->")[1].split("/")[0] in task.answers:
                rules = new; note.append(m); break
    return rules, note


def mapped_chunk(block, task, rnd):
    """A mechanism = one rule of a block, with probability 0.5 plus the block's rules that define one of its body predicates; every
    predicate it reads but does not define is mapped onto a task input, and the seed rule's head onto a task answer, each with random
    argument positions (one sample of the structure mapping — the start phase draws many)."""
    bid, rules = block
    seed = rnd.choice(rules)
    chunk = [seed]
    body_preds = {l[1][0] for l in seed[1] if l[0] != "cmp"}
    if rnd.random() < 0.5:
        chunk += [r for r in rules if r is not seed and r[0][0] in body_preds]
    ar, heads = preds_of(chunk)
    note = []
    for p in [p for p in ar if p not in heads and p not in task.target]:
        chunk, m = remap(chunk, task, rnd, pred=p)
        note.append(m)
    p = seed[0][0]
    if p not in task.target:
        for _ in range(8):
            new, m = remap(chunk, task, rnd, pred=p)
            if m and m.split("->")[1].split("/")[0] in task.answers:
                chunk = new; note.append(m); break
    return repair(chunk), note


def remap_target(rules, task, rnd):
    """Re-hang one task predicate already in the rules onto another task predicate of the same role (input→input, answer→answer),
    everywhere, with new argument positions — so a wrong early mapping can be undone. Same operator for every arm."""
    ar, _heads = preds_of(rules)
    present = [p for p in ar if p in task.target]
    if not present:
        return rules, None
    p = rnd.choice(present)
    pool = list(task.answers if p in task.answers else task.inputs)
    q = rnd.choice(pool)
    n, m = ar[p], task.target[q]
    pos = rnd.sample(range(n), min(n, m)) + [None] * max(0, m - n)
    rnd.shuffle(pos)

    def tr(a):
        if a[0] != p:
            return a
        return (q, [f"W{i}y" if i is None else a[1][i] for i in pos])
    return [(tr(h), [l if l[0] == "cmp" else (l[0], tr(l[1])) for l in lits]) for h, lits in rules], f"retarget {p}->{q} {pos}"


def random_individual(task, rnd):
    rules = []
    for _ in range(rnd.randint(1, 4)):
        rules, _op = mutate(rules, task, rnd, ["add_rule"])
    return rules


def run(task_name, arm, seed, nearest=None):
    rnd = random.Random(f"{task_name}:{arm}:{seed}")
    task = Task(task_name, seed)
    lib = library()
    ops = ["remap", "remap_target"] if arm == "S" else ["remap", "remap_target", "drop_lit", "add_lit", "flip_neg", "add_neq", "drop_rule", "dup_rule",
                                         "change_arg", "add_rule"]
    pop, evals, t0 = [], 0, time.time()

    def score(rules):
        nonlocal evals
        evals += 1
        rules[:] = repair(rules)
        f1, ex = E.fitness(render(rules), task.train, task.gold_train, task.answers)
        return f1 - SIZE_COST * size(rules), ex

    solved_at, best_held = None, None
    checked = set()

    def held_check(rules, origin, ops):
        nonlocal solved_at, best_held
        prog = render(rules)
        if prog in checked:
            return False
        checked.add(prog)
        _f1, hx = E.fitness(prog, task.held, task.gold_held, task.answers)
        if hx == HELD_N and solved_at is None:
            solved_at = evals
            best_held = {"program": prog, "origin": origin, "ops": ops, "size": size(rules)}
            return True
        return False

    # start phase (INIT evaluations of the budget, every arm alike): sample candidates, keep the best POP
    blocks = [b for b in lib if b[0] == nearest] if arm == "T" else lib
    cands = []
    while evals < INIT:
        if arm == "Z":
            ind, origin = random_individual(task, rnd), "random"
        else:
            block = rnd.choice(blocks)
            ind, _note = mapped_chunk(block, task, rnd)
            origin = block[0]
        if not ind:
            continue
        f, ex = score(ind)
        cands.append({"rules": ind, "fit": f, "exact": ex, "origin": origin, "ops": ["init"]})
        if ex == TRAIN_N and held_check(ind, origin, ["init"]):
            break
    pop = sorted(cands, key=lambda x: -x["fit"])[:POP]
    while evals < BUDGET and solved_at is None:
        def pick():
            return max(rnd.sample(pop, TOURN), key=lambda x: x["fit"])
        a = pick()
        if arm != "S" and rnd.random() < 0.2:
            b = pick(); child = crossover(a["rules"], b["rules"], rnd); op = f"cross {b['origin']}"
        else:
            child, op = a["rules"], None
        for _ in range(rnd.randint(1, 2)):
            child, o = mutate(child, task, rnd, ops)
            op = (op + "; " if op else "") + str(o)
        if not child:
            continue
        f, ex = score(child)
        worst = min(range(len(pop)), key=lambda j: pop[j]["fit"])
        ind = {"rules": child, "fit": f, "exact": ex, "origin": a["origin"], "ops": a["ops"][-20:] + [op]}
        if f > pop[worst]["fit"]:
            pop[worst] = ind
        if ex == TRAIN_N and held_check(child, ind["origin"], ind["ops"]):
            break
    best = max(pop, key=lambda x: x["fit"])
    return {"task": task_name, "arm": arm, "seed": seed, "solved": solved_at is not None, "evals_to_solve": solved_at,
            "evals": evals, "seconds": round(time.time() - t0, 1), "solution": best_held,
            "best_train": {"fit": round(best["fit"], 4), "exact": best["exact"], "origin": best["origin"],
                           "program": render(best["rules"])}}


if __name__ == "__main__":
    task_name, arm, seed, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    nearest = json.load(open(__file__.rsplit("/", 1)[0] + "/nearest.json")).get(task_name) if arm == "T" else None
    json.dump(run(task_name, arm, seed, nearest), open(out, "w"), indent=1)

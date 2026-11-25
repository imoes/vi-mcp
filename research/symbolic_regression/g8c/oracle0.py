"""G8c-0 ORACLE CEILING (after Fable's review 1, finding 4 iii): can ANY static per-task operator prior speed gp2 up by the smallest
effect of interest (ratio 1.5)? If even an oracle that knows the true edit operators of a task cannot, a static reweighting is dead and a
proposer must be conditioned on the candidate (DreamCoder-style guidance), not on the task.

Dreams: a blind task's vocabulary and world generator (the worlds a proposer would read), but a NEW hidden reference P* = a library block
mapped onto the task (arms2.mapped_chunk) plus k EFFECTIVE mutations (canonical form changed; the operator names recorded are only the
effective ones). Kept only if P* translates, its answers vary over the 30 training worlds, and it is NOT equivalent to the unmodified
mapped block on the verify + stress worlds.
Arms (identical start set per (dream, seed): the start RNG does not contain the arm; the start is the L library start of arms2):
  U  uniform operators (gp2 unchanged: bit-identical path)
  O  oracle: 0.8 x uniform over the dream's effective operators + 0.2 x uniform over all 12
  P  permuted oracle: the operator set of another dream (derangement over dreams, redrawn per seed)
  M  mean prior: the mean of all dreams' oracle distributions (task-independent, same marginal shape as O)
Outcome O2 = evaluations after the start phase to the first verified solution (budget 15,000 after the start, censored 15,001);
undefined if the start phase already solves it (counted).
usage: oracle0.py make N OUT          (write N dreams)
       oracle0.py run DREAMS_JSON IDX ARM SEED OUT"""
import json, os, random, sys, time

D = os.path.dirname(os.path.abspath(__file__))
G8B = os.path.join(D, "..", "g8b")
sys.path.insert(0, G8B)
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
import gp2 as gp  # noqa: E402
import arms2  # noqa: E402
import blind_tasks as BT  # noqa: E402

gp.T = BT
OPS = ["add_rule", "add_lit", "add_neg", "add_neq", "del_lit", "del_rule", "flip", "const", "var", "pred", "invent", "recurse"]
BUDGET = 15000


class WeightedRnd:
    """passes every call to the real RNG except the one operator choice in gp2.mutate, which is drawn with the given weights"""
    def __init__(self, rnd, weights):
        self._r, self._w = rnd, weights

    def choice(self, seq):
        if isinstance(seq, list) and seq == OPS:
            return self._r.choices(OPS, weights=self._w)[0]
        return self._r.choice(seq)

    def __getattr__(self, name):
        return getattr(self._r, name)


ORIG_MUTATE = gp.mutate


def install_prior(weights):
    """weights None = gp2 exactly (the real RNG object is passed through)"""
    if weights is None:
        gp.mutate = ORIG_MUTATE
        return

    def mutate(prog, gen, rnd):
        return ORIG_MUTATE(prog, gen, WeightedRnd(rnd, weights))
    gp.mutate = mutate


class DreamTask(gp.Task):
    def __init__(self, name, seed, ref):
        super().__init__(name, seed)  # worlds of the blind task; then the hidden reference is replaced
        self.ref = ref
        self.gold = [gp.E.answers(ref, w, self.answers) for w in self.train]
        self.verify_gold = [gp.E.answers(ref, w, self.answers) for w in self.verify]
        self.stress_gold = [gp.E.answers(ref, w, self.answers) for w in self.stress]
        self._types()


def make(n, out):
    rnd = random.Random("g8c-oracle0-dreams")
    lib = arms2.library()
    names = sorted(BT.TASKS)
    dreams, tries, why = [], 0, {}
    per_k = n // 3
    want = {1: per_k, 2: per_k, 3: n - 2 * per_k}
    seen = set()
    while any(want.values()) and tries < 20000:
        tries += 1
        k = rnd.choice([kk for kk, v in want.items() if v])
        name = rnd.choice(names)
        base = gp.Task(name, 0)
        block = rnd.choice(lib)
        p0 = arms2.mapped_chunk(block, base, rnd)
        if not p0:
            why["empty map"] = why.get("empty map", 0) + 1; continue
        prog, ops, steps = p0, [], 0
        gen = gp.Gen(base, rnd)
        while len(ops) < k and steps < 50:
            steps += 1
            child, op = ORIG_MUTATE(prog, gen, rnd)
            child = gp.canon(child)
            if child and gp.render(child) != gp.render(prog) and all(gp.safe(r) for r in child):
                prog = child; ops.append(op)
        if len(ops) < k:
            why["no effective edit"] = why.get("no effective edit", 0) + 1; continue
        ref = gp.render(prog)
        if ref in seen:
            why["duplicate"] = why.get("duplicate", 0) + 1; continue
        gold = [gp.E.answers(ref, w, base.answers) for w in base.train]
        if any(g is None for g in gold):
            why["does not translate"] = why.get("does not translate", 0) + 1; continue
        if len(set(gold)) < 3:
            why["answers barely vary"] = why.get("answers barely vary", 0) + 1; continue
        ref0 = gp.render(p0)
        worlds = base.verify + base.stress
        if all(gp.E.answers(ref, w, base.answers) == gp.E.answers(ref0, w, base.answers) for w in worlds):
            why["equivalent to the unmodified block"] = why.get("equivalent to the unmodified block", 0) + 1; continue
        seen.add(ref); want[k] -= 1
        dreams.append({"idx": len(dreams), "task": name, "block": block[0], "k": k, "ops": ops, "ref": ref, "ref0": ref0})
    json.dump({"dreams": dreams, "tries": tries, "dropped": why}, open(out, "w"), indent=1)
    print(len(dreams), "dreams;", tries, "tries; dropped:", why)


def prior(d, dreams, arm, seed):
    uni = [1 / 12] * 12

    def oracle(ops):
        s = set(ops)
        return [0.8 * (1 / len(s) if o in s else 0) + 0.2 / 12 for o in OPS]
    if arm == "U":
        return None
    if arm == "O":
        return oracle(d["ops"])
    if arm == "P":
        idx = list(range(len(dreams)))
        r = random.Random(f"derangement:{seed}")
        while True:
            perm = idx[:]; r.shuffle(perm)
            if all(a != b for a, b in zip(idx, perm)):
                break
        return oracle(dreams[perm[d["idx"]]]["ops"])
    if arm == "M":
        ws = [oracle(x["ops"]) for x in dreams]
        return [sum(w[i] for w in ws) / len(ws) for i in range(12)]
    raise ValueError(arm)


def run(dreams_file, idx, arm, seed, out):
    dreams = json.load(open(dreams_file))["dreams"]
    d = dreams[idx]
    task = DreamTask(d["task"], seed, d["ref"])
    task.name = f"dream{idx}"
    search = gp.Search(task, seed, BUDGET, after_solve=0)
    rnd = random.Random(f"start:dream{idx}:{seed}")  # no arm in the start RNG: identical start sets (review finding 2)
    t0 = time.time()
    install_prior(None)  # the start phase is the same for every arm
    pop, stats = arms2.start(task, search, "L", rnd, arms2.library())
    first_in_start = bool(search.solutions)
    search.budget = stats["start_evals"] + BUDGET
    search.start = pop
    w = prior(d, dreams, arm, seed)
    install_prior(w)
    if not first_in_start:
        search.run()
    firsts = sorted(search.solutions.values(), key=lambda x: x["evals"])
    o2 = None if first_in_start else ((firsts[0]["evals"] - stats["start_evals"]) if firsts else 15001)
    res = {"idx": idx, "arm": arm, "seed": seed, "k": d["k"], "ops": d["ops"], "first_in_start": first_in_start, "O2": o2,
           "solved": bool(firsts), "weights": w, "start_evals": stats["start_evals"], "distinct_start": stats["distinct"],
           "seconds": round(time.time() - t0, 1), "solution": firsts[0]["program"] if firsts else None}
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(f"{out}/d{idx}_{arm}_{seed}.json", "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("idx", "arm", "seed", "k", "first_in_start", "O2", "seconds")}))


if __name__ == "__main__":
    if sys.argv[1] == "make":
        make(int(sys.argv[2]), sys.argv[3])
    else:
        run(sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5]), sys.argv[6])

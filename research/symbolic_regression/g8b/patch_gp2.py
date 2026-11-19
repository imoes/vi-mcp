"""gp2.py = gp.py (G8b-0, unchanged for reproducibility) + the fixes of Fable's G8b-1 review:
S6: stop on evaluations only (MAX_GENS effectively off), AFTER_SOLVE configurable (0 for cost runs), the FIRST solution recorded at once
    (on_first callback), the solver timeout raised to 10 s (less load-dependent; correct programs solve in milliseconds);
S8: lineage — every program carries the origin of its start candidate through mutation and crossover (parent a's origin);
S9: the population refill is deduplicated."""
import sys

p = sys.argv[1]
s = open(p).read()


def rep(old, new, count=1):
    global s
    assert s.count(old) >= 1, old[:80]
    s = s.replace(old, new, count)


rep("MAX_GENS = 300\nAFTER_SOLVE = 25\n", "MAX_GENS = 10 ** 9  # gp2: stop on evaluations only\nAFTER_SOLVE = 25\n")
rep("import g8_eval as E  # noqa: E402\n", "import g8_eval as E  # noqa: E402\nE.TIMEOUT = 10.0  # gp2: correct programs solve in ms; 2 s made fitness load-dependent\n")
rep("    def __init__(self, task, seed, budget, start=None):\n",
    "    def __init__(self, task, seed, budget, start=None, after_solve=AFTER_SOLVE, on_first=None, origins=None):\n")
rep("        self.start = start or []\n",
    "        self.start = start or []\n        self.after_solve, self.on_first = after_solve, on_first\n"
    "        self.origin = dict(origins or {})  # gp2 lineage: program text -> origin of its start candidate\n")
rep("""                self.solutions.setdefault(render(prog), {"size": s, "evals": self.evals, "program": render(prog)})""",
    """                if render(prog) not in self.solutions:
                    rec = {"size": s, "evals": self.evals, "program": render(prog), "origin": self.origin.get(render(prog), "?")}
                    if not self.solutions and self.on_first:
                        self.on_first(rec)
                    self.solutions[render(prog)] = rec""")
rep("""        while len(pop) < POP:
            r = self.gen.new_rule({})
            if r:
                pop.append(canon((r,)))""",
    """        have = {render(p) for p in pop}
        tries = 0
        while len(pop) < POP and tries < 50 * POP:  # gp2: deduplicated refill
            tries += 1
            r = self.gen.new_rule({})
            c = canon((r,)) if r else ()
            if c and render(c) not in have:
                have.add(render(c)); pop.append(c); self.origin.setdefault(render(c), "refill")""")
rep("                if gens - first >= AFTER_SOLVE:", "                if gens - first >= self.after_solve:")
rep("""                    child = crossover(a, b, self.gen, self.rnd)""",
    """                    child = crossover(a, b, self.gen, self.rnd)
                    parent = a""")
rep("""                    child = a
""", """                    child = a
                    parent = a
""")
rep("""                seen.add(render(child)); nxt.append(child)""",
    """                seen.add(render(child)); nxt.append(child)
                self.origin.setdefault(render(child), self.origin.get(render(parent), "?") if parent is not None else "immigrant")""")
rep("""            tries = 0
            while len(nxt) < POP:
                tries += 1""", """            tries = 0
            while len(nxt) < POP:
                tries += 1
                parent = None""")
open(p, "w").write(s)
print("gp2 patched")

"""patch gp.py: stress failures are counterexamples too; stop AFTER_SOLVE generations after the first exact solution."""
import sys

p = sys.argv[1]
s = open(p).read()
old_v = """        bad = sum(E.answers(k, w, self.t.answers) != g for w, g in zip(self.t.stress, self.t.stress_gold))
        return None if bad == 0 else f"stress:{bad}\""""
new_v = """        for w, g in zip(self.t.stress, self.t.stress_gold):
            if E.answers(k, w, self.t.answers) != g:
                return w  # a stress world is a counterexample too (it holds distinctions the small domain lacks)
        return None"""
assert old_v in s
s = s.replace(old_v, new_v)
old_n = """            elif not str(res).startswith("stress"):
                # counterexample-guided"""
new_n = """            else:
                # counterexample-guided"""
assert old_n in s
s = s.replace(old_n, new_n)
old_s = """            if self.solutions and gens > 0 and min(x["size"] for x in self.solutions.values()) <= min(self.archive):
                break  # the shortest exact program is found"""
new_s = """            if self.solutions:
                first = first if first is not None else gens
                if gens - first >= AFTER_SOLVE:
                    break  # AFTER_SOLVE generations spent looking for a shorter exact program"""
assert old_s in s
s = s.replace(old_s, new_s)
s = s.replace("        t0 = time.time()\n        gens = 0\n", "        t0 = time.time()\n        gens, first = 0, None\n")
s = s.replace("MAX_GENS = 300\n", "MAX_GENS = 300\nAFTER_SOLVE = 25\n")
open(p, "w").write(s)
print("patched")

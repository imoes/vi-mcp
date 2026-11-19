"""G8b-1 amendment 1, sensitivity analysis: score1.py unchanged, but a solution that failed robust1.json counts as unsolved
(first_solution None, first_in_start False, search cost censored). Writes result_G8b1_sens.json."""
import json, os, sys
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import score1  # noqa: E402

robust = json.load(open(f"{D}/robust1.json"))
_load = score1.load


def load_sens():
    R = _load()
    for (t, a, s), r in R.items():
        if r.get("first_solution") and not robust.get(f"{t}|{a}|{s}", False):
            r["first_solution"], r["first_in_start"], r["search_cost"] = None, False, None
    return R


score1.load = load_sens
sys.argv = [sys.argv[0]]
code = open(f"{D}/score1.py").read().replace('open(f"{D}/result_G8b1.json", "w")', 'open(f"{D}/result_G8b1_sens.json", "w")')
exec(compile(code.split('if __name__ == "__main__":')[1].replace("\n    ", "\n"), "score1_main", "exec"), score1.__dict__)

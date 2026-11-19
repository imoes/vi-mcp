import random
import re
import os, sys

sys.path.insert(0, os.environ.get("VI_MCP_REPO") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clingo_object import notation as n  # noqa: E402
import blind_tasks as bt  # noqa: E402


def answers(name, world):
    t = bt.TASKS[name]
    prog = n.translate_full(t["REFERENCE"] + "\n" + world)[0]
    r = n._solve(prog)
    assert r["satisfiable"] and r["complete"] and len(r["models"]) == 1, (name, r["notes"], len(r["models"]))
    m = r["models"][0]
    preds = set(t["answers"])
    return sorted(a for a in m if re.match(r"[a-z_0-9]+", a).group(0) in preds)


kinds = {"a": 0, "b": 0, "c": 0}
print(f"{'task':22} kind  worlds  with_answers  share   big-check")
for name, t in bt.TASKS.items():
    k = bt.KINDS[name]
    kinds[k] += 1
    ws = bt.verify_worlds(name)
    pos = sum(1 for w in ws if answers(name, w))
    assert 0 < pos < len(ws), (name, pos, len(ws))
    # inputs/constants used in verify worlds match the declaration; big-only constants absent there
    for w in ws:
        for line in w.splitlines():
            pred, args = re.match(r"(\w+)\((.*)\)$", line).groups()
            assert pred in t["inputs"] and len(args.split(", ")) == t["inputs"][pred], (name, line)
            for c in bt.BIG_ONLY_CONSTANTS[name]:
                assert c not in args.split(", "), (name, line)
    # random small and big worlds translate and solve; big worlds show the big-only constants
    rnd = random.Random(7)
    seen_big = set()
    big_pos = 0
    for _ in range(30):
        answers(name, bt.world_text(name, rnd, big=False))
        wb = bt.world_text(name, rnd, big=True)
        big_pos += bool(answers(name, wb))
        seen_big |= {c for c in bt.BIG_ONLY_CONSTANTS[name] if re.search(rf"\b{c}\b", wb)}
    assert seen_big == set(bt.BIG_ONLY_CONSTANTS[name]), (name, seen_big)
    print(f"{name:22} {k:4} {len(ws):7} {pos:13}  {pos/len(ws):5.0%}   big {big_pos}/30 with answers, new consts {sorted(seen_big)}")
print("kinds:", kinds, "total:", len(bt.TASKS))

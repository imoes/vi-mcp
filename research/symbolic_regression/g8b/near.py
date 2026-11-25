"""G8b-1 nearness (after Fable's review S1/S2): what the L arm's mapping can reach, invariant to renaming.

A non-trivial reference rule (body of >= 2 literals) MATCHES a library rule when there is a bijection between their body literals and an
injective map of the reference's variables into the library rule's variables such that
  - signs agree, and a literal is recursive (its predicate = the head's) in both or in neither;
  - every reference literal's variables are a SUBSET of its partner's (the mapping may project arguments away; argument order is free);
  - the head's variables map into the library head's variables; != pairs map onto != pairs.
Predicate names, argument order and arity surplus do not matter — exactly the freedom of arms.mapped_chunk. Left and right recursion of a
closure are the same under this key. Trivial rules (one body literal) are excluded: any arm produces them at once.
nearness(task) = share of the task's non-trivial reference rules with a match (0 when it has none).
usage: near.py -> nearness.json (and a renaming-invariance self-test)"""
import itertools, json, os, random, sys

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
import gp  # noqa: E402
import grade  # noqa: E402


def norm(rule):
    """(head var set, [(sign, recursive, var frozenset)], [!= pairs as frozensets])"""
    (hp, ha), body = rule
    hv = frozenset(a for a in ha if gp.is_var(a))
    lits, neqs = [], []
    for l in body:
        if l[0] == "!=":
            neqs.append(frozenset(a for a in (l[1], l[2]) if gp.is_var(a)))
        else:
            lits.append((l[0], l[1][0] == hp, frozenset(a for a in l[1][1] if gp.is_var(a))))
    return hv, lits, neqs


def matches(ref, lib):
    rh, rl, rn = norm(ref)
    lh, ll, ln = norm(lib)
    if len(rl) != len(ll) or len(rn) > len(ln) or len(rl) < 2:
        return False
    if sorted((s, r) for s, r, _ in rl) != sorted((s, r) for s, r, _ in ll):
        return False
    rvars = sorted(set(rh).union(*[v for *_x, v in rl]))
    lvars = sorted(set(lh).union(*[v for *_x, v in ll]))
    if len(rvars) > len(lvars):
        return False
    for perm in itertools.permutations(range(len(ll))):
        if any((rl[i][0], rl[i][1]) != (ll[j][0], ll[j][1]) for i, j in enumerate(perm)):
            continue
        # search an injective var map consistent with subset constraints (small: <= 7 vars)
        for img in itertools.permutations(lvars, len(rvars)):
            m = dict(zip(rvars, img))
            if not all({m[v] for v in rl[i][2]} <= ll[j][2] for i, j in enumerate(perm)):
                continue
            if not {m[v] for v in rh} <= lh:
                continue
            if all(any({m[v] for v in a} == b for b in ln) for a in rn):
                return True
    return False


def library_rules():
    import arms2
    return [(b, r) for b, rules in arms2.library() for r in rules if len([l for l in r[1] if l[0] != "!="]) >= 2]


def nearness(task_ref, lib):
    rules = [r for r in (grade.parse(x) for x in task_ref.splitlines() if x.strip()) if r]
    nontriv = [r for r in rules if len([l for l in r[1] if l[0] != "!="]) >= 2]
    if not nontriv:
        return 0.0, 0, 0, []
    hits, blocks = 0, set()
    for r in nontriv:
        bs = {b for b, lr in lib if matches(r, lr)}
        hits += bool(bs); blocks |= bs
    return hits / len(nontriv), hits, len(nontriv), sorted(blocks)


def renamed(text, rnd):
    """rename every predicate and variable consistently (self-test of invariance)"""
    import re
    preds = sorted(set(re.findall(r"([a-z_][a-z0-9_]*)\(", text)))
    vars_ = sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b", text)))
    pm = {p: f"q{i}_{rnd.randint(0, 99)}" for i, p in enumerate(rnd.sample(preds, len(preds)))}
    vm = {v: f"W{i}" for i, v in enumerate(rnd.sample(vars_, len(vars_)))}
    text = re.sub(r"([a-z_][a-z0-9_]*)\(", lambda m: pm[m.group(1)] + "(", text)
    return re.sub(r"\b([A-Z][A-Za-z0-9_]*)\b", lambda m: vm.get(m.group(1), m.group(1)), text)


if __name__ == "__main__":
    import blind_tasks as BT
    lib = library_rules()
    out = {}
    for name, t in BT.TASKS.items():
        s, h, n, bl = nearness(t["REFERENCE"], lib)
        out[name] = {"nearness": round(s, 3), "matched": h, "nontrivial": n, "kind": BT.KINDS[name], "blocks": bl[:6]}
    # self-test: renaming every task 3 times never changes its nearness
    rnd = random.Random(5)
    bad = [k for k, t in BT.TASKS.items() for _ in range(3) if round(nearness(renamed(t["REFERENCE"], rnd), lib)[0], 3) != out[k]["nearness"]]
    json.dump(out, open(os.path.join(D, "nearness.json"), "w"), indent=1)
    from collections import Counter
    print("renaming-invariance failures:", bad)
    print("near (> 0):", sum(1 for v in out.values() if v["nearness"] > 0), "by kind", Counter(v["kind"] for v in out.values() if v["nearness"] > 0))
    for k, v in sorted(out.items(), key=lambda kv: (kv[1]["kind"], -kv[1]["nearness"])):
        print(f"{k:22s} {v['kind']} near {v['nearness']:.2f} ({v['matched']}/{v['nontrivial']}) {','.join(v['blocks'][:3])}")

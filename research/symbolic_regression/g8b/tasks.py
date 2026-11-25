"""G8b tasks: the six G8 tasks (reused for the base capability G8b-0 — no library is involved there), with
- world_text(name, rnd, big): a random world (big = larger domains for the stress check: long cycles, long chains, more people);
- verify_worlds(name): EVERY world of a small domain, enumerated exhaustively — "solved" means equal answers on all of them.
The search reads only the gold answer atoms the hidden REFERENCE gives on these worlds."""
import itertools
import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/g8")
from g8_tasks import TASKS  # noqa: E402,F401


def _subsets(items):
    for r in range(len(items) + 1):
        yield from itertools.combinations(items, r)


def world_text(name, rnd, big=False):
    k = 2 if big else 1
    f = []
    if name == "release_gate":
        people = ["ann", "bob", "cyd", "dan", "eve", "fay"][: 4 + (2 if big else 0)]
        for c in [f"c{i}" for i in range(1, 3 * k + 1)][: rnd.randint(1, 3 * k)]:
            f.append(f"owner({c}, {rnd.choice(people)})")
            f += [f"approves({c}, {p})" for p in people if rnd.random() < 0.45]
    elif name == "dependency_cycle":
        pk = [f"p{i}" for i in range(1, 5 * k + 1)][: rnd.randint(2, 5 * k)]
        f += [f"package({p})" for p in pk]
        if big and len(pk) >= 4 and rnd.random() < 0.5:  # a long cycle through several packages
            ring = rnd.sample(pk, rnd.randint(4, len(pk)))
            f += [f"requires({a}, {b})" for a, b in zip(ring, ring[1:] + ring[:1])]
        f += [f"requires({a}, {b})" for a in pk for b in pk if a != b and rnd.random() < 0.2 / k]
    elif name == "sensor_state":
        for h in [f"h{i}" for i in range(1, 4 * k + 1)][: rnd.randint(1, 4 * k)]:
            if rnd.random() < 0.8:
                f.append(f"polled({h})")
            f += [f"ping({h}, {r})" for r in ("ok", "fail") if rnd.random() < 0.5]
    elif name == "trusted_reading":
        meters = [f"m{i}" for i in range(1, 3 * k + 1)]
        f += [f"calibrated({m})" for m in meters if rnd.random() < 0.5]
        for x in [f"x{i}" for i in range(1, 4 * k + 1)][: rnd.randint(1, 4 * k)]:
            f.append(f"reading({x}, {rnd.choice(meters)})")
    elif name == "lineage_root":
        docs = [f"d{i}" for i in range(1, 5 * k + 1)][: rnd.randint(2, 5 * k)]
        f += [f"document({d})" for d in docs]
        for i, d in enumerate(docs[1:], 1):
            if rnd.random() < (0.85 if big else 0.6):
                f.append(f"copied_from({d}, {rnd.choice(docs[:i] if not big else docs[max(0, i - 2):i])})")
    elif name == "bipartisan":
        members = [f"m{i}" for i in range(1, 4 * k + 1)]
        # big (stress) worlds hold parties never seen in training: a mechanism must say "two different parties", not list colours
        parties = ["red", "blue", "green"] + (["yellow", "purple"] if big else [])
        f += [f"party({m}, {rnd.choice(parties)})" for m in members]
        for b in [f"b{i}" for i in range(1, 3 * k + 1)][: rnd.randint(1, 3 * k)]:
            f += [f"supports({b}, {m})" for m in members if rnd.random() < 0.4]
    return "\n".join(dict.fromkeys(f))


def verify_worlds(name):
    """every world of a small domain (sizes chosen so that each task's distinctions all occur: two changes and three people,
    cycles of length 1..4, every forest of 4 documents, ...)."""
    out = []
    if name == "release_gate":
        people = ["ann", "bob", "cyd"]
        for owner in people:
            for appr in _subsets(people):
                out.append("\n".join([f"owner(c1, {owner})"] + [f"approves(c1, {p})" for p in appr]))
        for o1, o2 in itertools.product(people[:2], repeat=2):  # two changes: no cross-talk between changes
            for a1 in _subsets(people[:2]):
                for a2 in _subsets(people[:2]):
                    out.append("\n".join([f"owner(c1, {o1})", f"owner(c2, {o2})"] + [f"approves(c1, {p})" for p in a1]
                                         + [f"approves(c2, {p})" for p in a2]))
    elif name == "dependency_cycle":
        pk = ["p1", "p2", "p3", "p4"]
        edges = [(a, b) for a in pk for b in pk if a != b]
        for es in _subsets(edges[:6]):  # edges among p1..p3 plus p1->p4 (all 2^6) ...
            out.append("\n".join([f"package({p})" for p in pk] + [f"requires({a}, {b})" for a, b in es]))
        for perm in itertools.permutations(pk):  # ... and every 4-cycle, with and without a chord
            ring = [f"requires({a}, {b})" for a, b in zip(perm, perm[1:] + perm[:1])]
            out.append("\n".join([f"package({p})" for p in pk] + ring))
            out.append("\n".join([f"package({p})" for p in pk] + ring[:-1]))
        out.append("package(p1)\nrequires(p1, p1)")
    elif name == "sensor_state":
        per_host = []
        for polled in (False, True):
            for pings in _subsets(["ok", "fail"]):
                per_host.append((polled, pings))
        for (pa, qa), (pb, qb) in itertools.product(per_host, repeat=2):
            f = []
            for h, p, q in (("h1", pa, qa), ("h2", pb, qb)):
                if p:
                    f.append(f"polled({h})")
                f += [f"ping({h}, {r})" for r in q]
            out.append("\n".join(f))
    elif name == "trusted_reading":
        meters = ["m1", "m2"]
        for cal in _subsets(meters):
            for r1 in _subsets(meters):
                for r2 in _subsets(meters):
                    out.append("\n".join([f"calibrated({m})" for m in cal] + [f"reading(x1, {m})" for m in r1]
                                         + [f"reading(x2, {m})" for m in r2]))
    elif name == "lineage_root":
        docs = ["d1", "d2", "d3", "d4"]
        choices = [[None] + docs[:i] for i in range(1, 4)]  # d2..d4 each copied from nothing or an earlier document
        for parents in itertools.product(*choices):
            f = [f"document({d})" for d in docs]
            f += [f"copied_from({d}, {p})" for d, p in zip(docs[1:], parents) if p]
            out.append("\n".join(f))
    elif name == "bipartisan":
        members = ["m1", "m2", "m3"]
        for parties in itertools.product(["red", "blue"], repeat=3):
            for sup in _subsets(members):
                out.append("\n".join([f"party({m}, {p})" for m, p in zip(members, parties)]
                                     + [f"supports(b1, {m})" for m in sup]))
    return [w for w in dict.fromkeys(out)]

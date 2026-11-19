"""G8 target tasks: six small problems from other domains, each with its own vocabulary (no predicate name of the library), a world
generator and a HIDDEN reference program. The search never reads REFERENCE; only the gold answer atoms it produces on the worlds.
A task is solved when a program gives exactly the reference's answer atoms on every held-out world."""
import random

TASKS = {
    "release_gate": {
        "domain": "software review: a change is released when at least two different people other than its owner approved it",
        "inputs": {"approves": 2, "owner": 2}, "answers": {"released": 1},
        "REFERENCE": "ok(C, P) <= approves(C, P) & owner(C, O) & (P != O)\n"
                     "released(C) <= ok(C, P) & ok(C, Q) & (P != Q)",
    },
    "dependency_cycle": {
        "domain": "package manager: a package is in a cycle when its requirements lead back to itself",
        "inputs": {"requires": 2, "package": 1}, "answers": {"in_cycle": 1},
        "REFERENCE": "path(A, B) <= requires(A, B) & package(B)\n"
                     "path(A, C) <= path(A, B) & requires(B, C) & package(C)\n"
                     "in_cycle(A) <= path(A, A)",
    },
    "sensor_state": {
        "domain": "monitoring: a host polled in this round is up (only ok pings), down (only failed pings), flapping (both) or silent "
                  "(polled, no ping)",
        "inputs": {"ping": 2, "polled": 1}, "answers": {"state": 2},
        "constants": ["ok", "fail", "up", "down", "flapping", "silent"],
        "REFERENCE": "okp(H) <= ping(H, ok)\nbad(H) <= ping(H, fail)\n"
                     "no_ok(H) <= polled(H) & ~okp(H)\nno_bad(H) <= polled(H) & ~bad(H)\n"
                     "state(H, up) <= okp(H) & no_bad(H)\nstate(H, down) <= bad(H) & no_ok(H)\n"
                     "state(H, flapping) <= okp(H) & bad(H)\nstate(H, silent) <= no_ok(H) & no_bad(H)",
    },
    "trusted_reading": {
        "domain": "laboratory: a sample's reading is trusted when its meter is calibrated; a meter used for a reading without "
                  "calibration must be recalibrated",
        "inputs": {"reading": 2, "calibrated": 1}, "answers": {"trusted": 1, "recalibrate": 1},
        "REFERENCE": "trusted(X) <= reading(X, M) & calibrated(M)\n"
                     "recalibrate(M) <= reading(X, M) & ~calibrated(M)",
    },
    "lineage_root": {
        "domain": "data provenance: the origin of a document is the end of its copied-from chain (itself when it is no copy)",
        "inputs": {"copied_from": 2, "document": 1}, "answers": {"origin": 2},
        "REFERENCE": "up(D, R) <= copied_from(D, R)\nup(D, R) <= up(D, M) & copied_from(M, R)\n"
                     "is_copy(D) <= copied_from(D, R)\n"
                     "origin(D, D) <= document(D) & ~is_copy(D)\n"
                     "origin(D, R) <= document(D) & up(D, R) & ~is_copy(R)",
    },
    "bipartisan": {
        "domain": "parliament: a bill is bipartisan when supporters from two different parties back it",
        "inputs": {"supports": 2, "party": 2}, "answers": {"bipartisan": 1},
        "REFERENCE": "bipartisan(B) <= supports(B, M) & supports(B, N) & party(M, P) & party(N, Q) & (P != Q)",
    },
}


# visible task constants (answer values, input values); every other task has none
for _t in TASKS.values():
    _t.setdefault("constants", [])


def world(task: str, rnd: random.Random) -> list[str]:
    """Random facts of one world (notation lines)."""
    f = []
    if task == "release_gate":
        people = ["ann", "bob", "cyd", "dan"]
        for c in ["c1", "c2", "c3"][: rnd.randint(1, 3)]:
            f.append(f"owner({c}, {rnd.choice(people)})")
            for p in people:
                if rnd.random() < 0.45:
                    f.append(f"approves({c}, {p})")
    elif task == "dependency_cycle":
        pk = ["p1", "p2", "p3", "p4", "p5"][: rnd.randint(2, 5)]
        f += [f"package({p})" for p in pk]
        for a in pk:
            for b in pk:
                if a != b and rnd.random() < 0.25:
                    f.append(f"requires({a}, {b})")
    elif task == "sensor_state":
        for h in ["h1", "h2", "h3", "h4"][: rnd.randint(1, 4)]:
            if rnd.random() < 0.8:
                f.append(f"polled({h})")
            for r in ("ok", "fail"):
                if rnd.random() < 0.5:
                    f.append(f"ping({h}, {r})")
    elif task == "trusted_reading":
        meters = ["m1", "m2", "m3"]
        for m in meters:
            if rnd.random() < 0.5:
                f.append(f"calibrated({m})")
        for x in ["x1", "x2", "x3", "x4"][: rnd.randint(1, 4)]:
            f.append(f"reading({x}, {rnd.choice(meters)})")
    elif task == "lineage_root":
        docs = ["d1", "d2", "d3", "d4", "d5"][: rnd.randint(2, 5)]
        f += [f"document({d})" for d in docs]
        for i, d in enumerate(docs[1:], 1):  # a forest: each document copied from at most one earlier one
            if rnd.random() < 0.6:
                f.append(f"copied_from({d}, {rnd.choice(docs[:i])})")
    elif task == "bipartisan":
        members = ["m1", "m2", "m3", "m4"]
        for m in members:
            f.append(f"party({m}, {rnd.choice(['red', 'blue', 'green'])})")
        for b in ["b1", "b2", "b3"][: rnd.randint(1, 3)]:
            for m in members:
                if rnd.random() < 0.4:
                    f.append(f"supports({b}, {m})")
    return f


def worlds(task: str, n: int, seed: int) -> list[str]:
    rnd = random.Random(f"{task}:{seed}")
    return ["\n".join(world(task, rnd)) for _ in range(n)]

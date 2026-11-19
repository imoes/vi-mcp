"""G8 evaluator: the answer atoms of a clingo-object program on a world (intersection of all answer sets), and the fitness."""
import os, sys

sys.path.insert(0, os.environ.get("VI_MCP_REPO") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from clingo_object import notation as n  # noqa: E402

TIMEOUT = 2.0


def answers(program: str, facts: str, preds: dict) -> frozenset | None:
    """Answer atoms (predicates in preds) or None when the program does not translate or solve."""
    try:
        asp, stmts, _f = n.translate_full(program + "\n" + facts)
        raw = n.run_program(asp, stmts, n.prior_belief, TIMEOUT)
    except Exception:  # noqa: BLE001 — an invalid individual is unfit, not an error of the search
        return None
    models = [set(m) for m in raw.get("models") or []]
    if not models or raw.get("timeout"):
        return None
    atoms = {"".join(a.split()) for a in set.intersection(*models)}
    return frozenset(a for a in atoms if a.split("(", 1)[0] in preds)


def fitness(program: str, facts_list: list[str], gold: list[frozenset], preds: dict) -> tuple[float, int]:
    """(mean F1 over worlds, number of exactly right worlds); an invalid program scores (0, 0)."""
    f1s, exact = [], 0
    for facts, g in zip(facts_list, gold):
        got = answers(program, facts, preds)
        if got is None:
            return 0.0, 0
        exact += got == g
        if not g and not got:
            f1s.append(1.0)
            continue
        tp = len(got & g)
        f1s.append(0.0 if tp == 0 else 2 * tp / (len(got) + len(g)))
    return sum(f1s) / len(f1s), exact

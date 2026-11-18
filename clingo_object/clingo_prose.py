"""The clingo-object language in both directions: random rule sets and their meaning in plain English (0.66.0).

The user (15.11.2026): "Ich dachte eigentlich, dass wir der KI clingo beibringen und dann den Samen. Und aus ihrem Verständnis heraus kann
sie den Samen in Prosa umformulieren wie bei einer Übersetzung." So a model first learns the LANGUAGE — reading rules and writing them —
on thousands of rule sets that share no predicate with any philosophy seed; only then the seed. When it later translates the seed into
prose, it has never seen the seed's prose: the translation comes from understanding clingo, not from memory.

Every generated program is valid clingo-object notation (checked by translating it); every prose text is produced by a deterministic
renderer from the same rule structure, so code and prose say exactly the same. Rule forms cover what seeds use: conjunction, default
negation (`~p` = "p cannot be derived", never "p is false"), comparison (two different), constants, `never` (a forbidden situation),
deontic duties (obligatory, forbidden, may), recursion (reachability).
"""
from __future__ import annotations

import random
import re

from . import notation as n

#: predicates a generated rule may use — none of them occurs in a philosophy package (exclude= removes more at call time)
UNARY = ["server", "backup", "admin", "critical", "reachable", "patched", "approved", "archived", "monitored", "public", "encrypted",
         "deprecated", "healthy", "expired", "trusted", "internal", "tested", "documented", "running", "locked", "vulnerable",
         "replicated", "orphaned", "scheduled", "staged"]
BINARY = {"runs_on": "runs on", "owns": "owns", "depends_on": "depends on", "located_in": "is located in", "reports": "reports",
          "mentions": "mentions", "manages": "manages", "replaces": "replaces", "connects_to": "connects to", "stores": "stores",
          "watches": "watches", "signs": "signs", "uses": "uses", "hosts": "hosts", "links_to": "links to"}
ACTS = {"restart": "restart", "notify": "notify the owner of", "review": "review", "isolate": "isolate", "delete": "delete",
        "escalate": "escalate", "back_up": "back up", "update": "update"}
CONSTANTS = ["low", "high", "green", "red", "open", "done"]
#: ternary relations: (code name, prose with {0} {1} {2})
TERNARY = {"sends": "{0} sends {1} to {2}", "assigns": "{0} assigns {1} to {2}", "rates": "{0} rates {1} as {2}",
           "logs": "{0} logs {1} at {2}", "grants": "{0} grants {1} to {2}"}
MODES = ["up", "down", "pro", "contra", "yes", "no"]  # no Python keywords (the notation is parsed as Python: "for" fails)
VARS = ["X", "Y", "Z"]


# 0.67.0 (run 8): the forms a philosophy seed uses, on neutral words. Run 7's language stage covered unary and binary predicates over
# X/Y/Z almost only; asked to explain a seed (arity 3–4, constants as arguments, nested duties, closure rules, variables S/P/O) the
# model wrote "Blent holds for S and O when S corvy P O" even with neutral names (probe_route, 15.11.2026). These forms close that gap.
QUAD = {"routes": "{0} routes {1} through {2} for {3}", "records": "{0} records {1} from {2} by {3}",
        "ships": "{0} ships {1} via {2} to {3}", "books": "{0} books {1} at {2} for {3}"}
STATES = ["ok", "late", "lost", "fresh", "stale", "hot", "cold"]
DUTY_WORDS = {"obligatory": "one must", "forbidden": "one must not", "may": "one may"}
#: variable letters a rule set may use instead of X Y Z M N F G (never A or I: they are English words)
VAR_POOL = ["S", "P", "O", "R", "K", "B", "C", "D", "V", "W", "T", "Q", "L", "U", "E", "H", "J"]
VARS_USED = ["X", "Y", "Z", "M", "N", "F", "G"]


def _w(p: str) -> str:
    return p.replace("_", " ")


def _rule_ext(rnd: random.Random, unary: list[str], binary: list[str]) -> tuple[str, str]:
    """One rule in a form a seed uses (code, prose)."""
    form = rnd.choice(["const_head", "quad_body", "quad_guard", "ternary_head", "never_closure", "duty_nested", "single_closure"])
    h, a, b, h2 = rnd.sample(unary, 4)
    r = rnd.choice(binary)
    q, t, st, act = rnd.choice(list(QUAD)), rnd.choice(list(TERNARY)), rnd.choice(STATES), rnd.choice(list(ACTS))
    if form == "const_head":  # like value(S, t) <= pos(S) & absent_neg(S)
        if rnd.random() < 0.5:
            return (f"{h}(X, {st}) <= {a}(X) & ~{b}(X)",
                    f"The {_w(h)} of X is {st} when X is {_w(a)} and it cannot be derived that X is {_w(b)} (absence of evidence, not proof of the opposite).")
        return f"{h}(X, {st}) <= {a}(X) & {b}(X)", f"The {_w(h)} of X is {st} when X is {_w(a)} and X is {_w(b)}."
    if form == "quad_body":  # like pos(S) <= counts(S, pos, O) over a four-place input
        return (f"{h}(X, Y) <= {q}(X, Y, Z, M)",
                f"{_w(h).capitalize()} holds for X and Y when " + QUAD[q].format("X", "Y", "some Z", "some M") + ".")
    if form == "quad_guard":  # like counts(S, P, O) <= line(S, P, O, I) & author(S, A) & (I != A)
        return (f"{h}(X, Y, Z) <= {q}(X, Y, Z, M) & {r}(X, N) & (M != N)",
                f"{_w(h).capitalize()} holds for X, Y and Z when " + QUAD[q].format("X", "Y", "Z", "some M")
                + f", X {BINARY[r]} some N, and M is not the same as N.")
    if form == "ternary_head":
        return (f"{h}(X, Y, Z) <= {t}(X, Y, Z) & {a}(Y)",
                f"{_w(h).capitalize()} holds for X, Y and Z when " + TERNARY[t].format("X", "Y", "Z") + f" and Y is {_w(a)}.")
    if form == "never_closure":  # like never(value(S, V) & ~reasoned(S))
        return (f"never({a}(X) & ~{b}(X))",
                f"It is a violation if X is {_w(a)} and it cannot be derived that X is {_w(b)}.")
    if form == "duty_nested":  # like forbidden(confirm(I, S)) <= author(S, I) or obligatory(verify(R, S)) <= unverified(R, S)
        d = rnd.choice(list(DUTY_WORDS))
        if rnd.random() < 0.5:
            return f"{d}({act}(Y, X)) <= {r}(X, Y)", f"If X {BINARY[r]} Y, {DUTY_WORDS[d]} {ACTS[act]} Y for X."
        return f"{d}({act}(X, {st})) <= {a}(X)", f"If X is {_w(a)}, {DUTY_WORDS[d]} {ACTS[act]} X as {st}."
    # single_closure, like single(S, P) <= counts(S, P, O) & ~two(S, P)
    return (f"{h}(X, Y) <= {r}(X, Y) & ~{h2}(X, Y)",
            f"{_w(h).capitalize()} holds for X and Y when X {BINARY[r]} Y and it cannot be derived that {_w(h2)} holds for X and Y.")


def rename_vars(code: str, prose: str, rnd: random.Random) -> tuple[str, str]:
    """The same rule set with other variable letters, consistently in code and prose (a seed writes S, P, O, R …)."""
    pool = rnd.sample(VAR_POOL, len(VARS_USED))
    m = dict(zip(VARS_USED, pool))
    sub = lambda text: re.sub(r"\b(" + "|".join(VARS_USED) + r")\b", lambda x: m[x.group(1)], text)
    return sub(code), sub(prose)


def _u(p: str, v: str) -> tuple[str, str]:
    return f"{p}({v})", f"{v} is {p.replace('_', ' ')}"


def _b(r: str, a: str, b: str) -> tuple[str, str]:
    return f"{r}({a}, {b})", f"{a} {BINARY[r]} {b}"


def _rule(rnd: random.Random, unary: list[str], binary: list[str]) -> tuple[str, str]:
    """One rule as (code, prose)."""
    form = rnd.choice(["and", "not", "rel", "two", "never", "duty_must", "duty_forbid", "may", "const", "single",
                       "neq", "const_body", "ternary_two", "duty_two", "closure"])
    h, a, b, c = rnd.sample(unary, 4)
    r, r2 = rnd.sample(binary, 2)
    if form == "neq":  # a variable must differ from another one (like "not the author")
        return (f"{h}(X) <= {r}(X, Y) & {r2}(X, Z) & (Y != Z)",
                f"X is {h.replace('_', ' ')} when X {BINARY[r]} some Y, X {BINARY[r2]} some Z, and Y is not the same as Z.")
    if form == "const_body":  # a constant inside a body literal
        t = rnd.choice(list(TERNARY))
        m = rnd.choice(MODES)
        return (f"{h}(X) <= {t}(X, {m}, Y)",
                f"X is {h.replace('_', ' ')} when " + TERNARY[t].format("X", m, "some Y") + ".")
    if form == "ternary_two":  # two different third arguments for the same first two (like "two independent lines")
        t = rnd.choice(list(TERNARY))
        return (f"{h}(X, M) <= {t}(X, M, F) & {t}(X, M, G) & (F != G)",
                f"{h.replace('_', ' ').capitalize()} holds for X and M when " + TERNARY[t].format("X", "M", "two different parties") + ".")
    if form == "duty_two":  # a duty with two participants, a function term inside the deontic head
        act = rnd.choice(list(ACTS))
        return (f"forbidden({act}(Y, X)) <= {r}(Y, X)",
                f"If Y {BINARY[r]} X, then Y must not {ACTS[act]} X.")
    if form == "closure":  # absence over a closed view, as philosophy seeds use it
        return (f"missing_{a}(X) <= {b}(X) & ~{a}(X)",
                f"For an X that is {b.replace('_', ' ')}, it counts as missing that X is {a.replace('_', ' ')} when that cannot be derived.")
    if form == "single":
        code_b, pr_b = _u(a, "X")
        return f"{h}(X) <= {code_b}", f"Every X that is {a.replace('_', ' ')} is {h.replace('_', ' ')}."
    if form == "and":
        (cb1, pb1), (cb2, pb2) = _u(a, "X"), _u(b, "X")
        return f"{h}(X) <= {cb1} & {cb2}", f"X is {h.replace('_', ' ')} when {pb1} and {pb2}."
    if form == "not":
        (cb1, pb1), (cb2, _p) = _u(a, "X"), _u(b, "X")
        return (f"{h}(X) <= {cb1} & ~{cb2}",
                f"X is {h.replace('_', ' ')} when {pb1} and it cannot be derived that X is {b.replace('_', ' ')} (absence of evidence, not proof of the opposite).")
    if form == "rel":
        (cr, _pr), (cu, pu) = _b(r, "X", "Y"), _u(a, "Y")
        # 0.69.9: the prose said "X reports Y some Y" (the relation's own object, then "some Y" again) — a model trained on it
        # reproduced the doubled object in its own explanations (run 27 diagnostic set, 18.11.2026)
        return f"{h}(X) <= {cr} & {cu}", f"X is {h.replace('_', ' ')} when X {BINARY[r]} some Y and {pu}."
    if form == "two":
        return (f"{h}(X) <= {r}(X, Y) & {r}(X, Z) & (Y != Z)",
                f"X is {h.replace('_', ' ')} when X {BINARY[r]} at least two different things.")
    if form == "never":
        (cb1, pb1), (cb2, pb2) = _u(a, "X"), _u(b, "X")
        return f"never({cb1} & {cb2})", f"It is a violation if something is both {a.replace('_', ' ')} and {b.replace('_', ' ')}."
    act = rnd.choice(list(ACTS))
    if form == "duty_must":
        cb1, pb1 = _u(a, "X")
        return f"obligatory({act}(X)) <= {cb1}", f"If {pb1}, one must {ACTS[act]} X."
    if form == "duty_forbid":
        cb1, pb1 = _u(a, "X")
        return f"forbidden({act}(X)) <= {cb1}", f"If {pb1}, one must not {ACTS[act]} X."
    if form == "may":
        cb1, pb1 = _u(a, "X")
        return f"may({act}(X)) <= {cb1}", f"If {pb1}, one may {ACTS[act]} X."
    const = rnd.choice(CONSTANTS)
    cb1, pb1 = _u(a, "X")
    return f"level(X, {const}) <= {cb1}", f"The level of X is {const} when {pb1}."


def rule_run(rnd: random.Random, unary: list[str], k: int) -> tuple[list[str], list[str]]:
    """0.69.9: k rules that differ ONLY in a constant — the shape of a philosophy seed's duty block (forbidden(assert_unqualified(S)) <=
    acceptance(S, tentative|rejected|unresolved)). Measured 18.11.2026 (run 27 adapter, 20 matched pairs): inside such a run 12 of 60
    rules were dropped or replaced, in matched controls of the same form 0 (sign test mid-p 0.007); random programs never contain one
    (0 of 3,080 explain prompts in kit 30). (codes, prose sentences), one per rule."""
    h = rnd.choice(unary)
    states = rnd.sample(STATES, k)
    if rnd.random() < 0.5:
        d, act = rnd.choice(list(DUTY_WORDS)), rnd.choice(list(ACTS))
        return ([f"{d}({act}(X)) <= {h}(X, {st})" for st in states],
                [f"If the {_w(h)} of X is {st}, {DUTY_WORDS[d]} {ACTS[act]} X." for st in states])
    h2 = rnd.choice([u for u in unary if u != h])
    return ([f"{h2}(X) <= {h}(X, {st})" for st in states], [f"X is {_w(h2)} when the {_w(h)} of X is {st}." for st in states])


def program(rnd: random.Random, exclude: set[str] = frozenset(), rules: tuple[int, int] = (1, 4), extended: float = 0.0,
            rename: float = 0.0, runs: float = 0.0) -> tuple[str, str]:
    """A random rule set as (code, prose); predicates in `exclude` are never used. Recursion is added sometimes. extended: the share of
    rules in a seed's forms (_rule_ext); rename: the probability that the set uses other variable letters (0.67.0, run 8); runs: the
    probability that a run of 2–4 near-identical rules (rule_run) sits at a random place among them (0.69.9; 0 keeps older kits)."""
    unary = [p for p in UNARY if p not in exclude]
    binary = [p for p in BINARY if p not in exclude]
    out_c, out_p = [], []
    for _ in range(rnd.randint(*rules)):
        c, p = _rule_ext(rnd, unary, binary) if rnd.random() < extended else _rule(rnd, unary, binary)
        if c not in out_c:
            out_c.append(c)
            out_p.append(p)
    if runs and rnd.random() < runs:
        used = set(re.findall(r"([a-z_]+)\(", "\n".join(out_c)))
        rc, rp = rule_run(rnd, [u for u in unary if u not in used] or unary, rnd.randint(2, 4))
        at = rnd.randint(0, len(out_c))
        out_c[at:at], out_p[at:at] = rc, rp
    if rnd.random() < 0.15:
        r = rnd.choice(binary)
        out_c += [f"reach(X, Y) <= {r}(X, Y)", f"reach(X, Z) <= reach(X, Y) & {r}(Y, Z)"]
        out_p.append(f"Y is reachable from X when X {BINARY[r]} Y, directly or through a chain of such steps.")
    code, prose = "\n".join(out_c), " ".join(out_p)
    if rnd.random() < rename:
        code, prose = rename_vars(code, prose, rnd)
    n.translate(code)  # never a training example that is not valid notation
    return code, prose


def examples(count: int, seed: int, exclude: set[str] = frozenset(), system: str = "", extended: float = 0.0,
             rename: float = 0.0, rules: tuple[int, int] = (1, 4), runs: float = 0.0) -> list[dict]:
    """Translation examples in both directions (explain: code → prose, formalize: prose → code)."""
    rnd = random.Random(seed)
    out = []
    for i in range(count):
        code, prose = program(rnd, exclude, rules=rules, extended=extended, rename=rename, runs=runs)
        if rnd.random() < 0.5:
            q, a, task = f"Translate these clingo-object rules into plain English:\n{code}", prose, "explain_rules"
        else:
            q, a, task = f"Write these rules in clingo-object notation:\n{prose}", code, "write_rules"
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        out.append({"messages": msgs, "meta": {"task": task, "world": i, "seed": seed}})
    return out


# ── crossed vocabulary (0.67.0, run 8): a philosophy's own predicate names in translation tasks, never its rules ────────────────────

def normal_rule(rule: str) -> str:
    """A rule in a canonical form: variables renamed by first occurrence, body literals sorted. Two rules that differ only in variable
    names or body order have the same normal form — the leakage guard compares these."""
    rule = rule.strip().rstrip(".")
    order: dict[str, str] = {}
    canon = re.sub(r"\b([A-Z][A-Za-z0-9_]*)\b", lambda m: order.setdefault(m.group(1), f"V{len(order)}"), rule)
    if "<=" in canon:
        head, body = canon.split("<=", 1)
        parts, depth, cur = [], 0, ""
        for ch in body:
            depth += ch == "("
            depth -= ch == ")"
            if ch == "&" and depth == 0:
                parts.append(cur.strip()); cur = ""
            else:
                cur += ch
        parts.append(cur.strip())
        canon = head.strip() + " <= " + " & ".join(sorted(parts))
    return re.sub(r"\s+", " ", canon)


def _lit_prose(name: str, args: list[str]) -> str:
    if len(args) == 1:
        return f"{args[0]} is {_w(name)}"
    return f"{_w(name)} holds for " + (", ".join(args[:-1]) + " and " + args[-1])


def vocab_program(rnd: random.Random, vocab: dict[str, int], acts: list[str], constants: list[str], forbidden: set[str],
                  rules: tuple[int, int] = (1, 3), tries: int = 50) -> tuple[str, str] | None:
    """A random rule set over a GIVEN vocabulary (a philosophy's predicate names and arities) with generic prose, so the names occur in
    translation tasks too. No rule whose normal form is in `forbidden` (the seed's own rules) is ever produced; None if none was found."""
    names = [p for p, k in vocab.items() if k >= 1]
    letters = ["S", "P", "O", "R", "K", "B", "C", "D"]
    out_c, out_p = [], []
    for _ in range(rnd.randint(*rules)):
        for _t in range(tries):
            hn = rnd.choice(names)
            hv = letters[:vocab[hn]]
            body, prose_b, seen = [], [], set()
            for _k in range(rnd.randint(1, 2)):
                bn = rnd.choice(names)
                args = [rnd.choice(hv) if hv and rnd.random() < 0.6 else rnd.choice(letters) for _a in range(vocab[bn])]
                if constants and len(args) > 1 and rnd.random() < 0.3:
                    args[rnd.randrange(1, len(args))] = rnd.choice(constants)
                body.append(f"{bn}({', '.join(args)})")
                prose_b.append(_lit_prose(bn, args))
                seen |= {a for a in args if a[0].isupper()}
            if any(v not in seen for v in hv):
                continue  # unsafe head
            dutyful = acts and rnd.random() < 0.25
            if dutyful:
                d, act = rnd.choice(list(DUTY_WORDS)), rnd.choice(acts)
                av = rnd.sample(sorted(seen), min(len(seen), rnd.randint(1, 2)))
                head, head_p = f"{d}({act}({', '.join(av)}))", None
                prose = f"If {' and '.join(prose_b)}, {DUTY_WORDS[d]} {_w(act)} {' for '.join(av)}."
            else:
                head = f"{hn}({', '.join(hv)})"
                prose = f"{_lit_prose(hn, hv)[0].upper() + _lit_prose(hn, hv)[1:]} when {' and '.join(prose_b)}."
            if rnd.random() < 0.3:  # a closure: default negation over a positive literal's variables
                nn = rnd.choice(names)
                nargs = [rnd.choice(sorted(seen)) for _a in range(vocab[nn])]
                body.append(f"~{nn}({', '.join(nargs)})")
                prose = prose[:-1] + f", and it cannot be derived that {_lit_prose(nn, nargs)}."
            code = f"{head} <= {' & '.join(body)}"
            if normal_rule(code) in forbidden or code in out_c:
                continue
            try:
                n.translate(code)
            except Exception:  # noqa: BLE001 — an unsafe or invalid draw is redrawn, never kept
                continue
            out_c.append(code); out_p.append(prose)
            break
    return ("\n".join(out_c), " ".join(out_p)) if out_c else None

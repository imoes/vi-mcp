"""Logical descriptions in a Python-like notation, checked by formal logic (0.62.0) — the logic layer of the AI language.

The user (13.11.2026): "Zur VIL brauchen wir noch die Möglichkeit, uns in Python auszudrücken, für logische Beschreibungen. Aber es soll
nach den Prinzipien der formalen Logik geschrieben werden." — and, asked which engine is logically better regardless of effort: answer
set programming (clingo). Reasons (research of the same day): ASP's stable-model semantics contains stratified Datalog as a special case,
is nonmonotonic (rules with exceptions, norms), has three explicit truth values through strong negation (p, -p, neither = unknown), and
searches and optimises; Lifschitz, "What is Answer Set Programming?" (https://www.cs.utexas.edu/~vl/papers/wiasp.pdf).

Notation (Python syntax, read by ast with a whitelist — never executed; clingo receives only the translated program, never #script):
  zone("gate1", "dmz")                                   a fact
  forbidden(run(R, H)) <= zone(H, "dmz") & planned(run(R, H))
                                                        a rule: head <= body; & is "and"; capitalised names are variables
  ~done(A)                                              not derivable (negation as failure)
  -allowed(A)                                           explicitly false (strong negation)
  never(planned(A) & forbidden(A))                      a constraint — a violation is REPORTED with its number, not silently UNSAT
  (H != "gate1"), (N > 3), (H == "web1")                 comparisons inside a body, in parentheses (& binds tighter than <)
  soft(head <= body)  soft(head <= body, 0.9)  soft(fact)
                                                        a rule with a weight that is learned (the optional number is the prior belief)
Built in (the deontic square, SEP "Deontic Logic"): obligatory/forbidden/permitted; obligatory(A) and forbidden(A) together is a named
conflict (axiom NC); violation(A) :- obligatory(A), not done(A).

Nothing vanishes silently (the epistemic rules of the project): p and -p together is reported as a contradiction (state "both", as in
Belnap's four-valued logic) instead of the empty answer ASP would give; an answer is true, false, both, unknown — or undetermined when
several answer sets disagree, or not_derived when the program defines the predicate but this instance does not follow (negation as
failure), as opposed to unknown, when the program says nothing about it. What the engine derives is evidence `inferred`, never `measured`.

Rules in weights (the user, 13.11.2026: "clingo wird auch in Gewichte geschrieben, sodass wir mit Weight-Space Programming clingo schnell
lernen können"). Research of the same day:
- LPMLN (Lee & Wang, "Weight Learning in a Probabilistic Extension of Answer Set Programs", KR 2018, https://arxiv.org/abs/1808.04527):
  a weighted rule may be violated at a cost; the weight of a stable model is exp(sum of the weights of the soft rules it satisfies), so
  P(model) is proportional to exp(-cost of the rules it drops); weights are learned from observations by maximum likelihood.
- plingo (Hahn et al., https://arxiv.org/abs/2206.11515) computes LPMLN inside clingo by translating soft rules into weak constraints
  (the lpmln2asp scheme used here).
- NeurASP (Yang, Ishay, Lee, IJCAI 2020, https://www.ijcai.org/proceedings/2020/243) and ILASP (Law, Russo, Broda,
  https://arxiv.org/abs/2005.00904) go further — neural atoms and learning the rules themselves; neither is part of this module.
Here: every rule has an identity (hash of its translated text) and measured counters — rated conclusions credit exactly the rules that
derived them (`rate`). A soft rule's weight is the log-odds of its beta mean, own counters plus the network's (word_weights, same rating
channel, target sha256("vil-rule-v1|<rule>")). A hard rule stays hard whatever is measured — the measurement is shown next to it
(intension and extension kept apart); turning it soft is the author's decision. Only weights are learned, never new rules.
Simplification, stated: each rated conclusion counts as one Bernoulli observation of every rule that derives it (a beta count), not
the maximum-likelihood gradient of Lee & Wang — fast and explainable, exact for a rule that alone decides a conclusion.
"""
from __future__ import annotations

import ast
import hashlib
import math
import os
import re
import sys
from pathlib import Path

MAX_SOURCE = 20_000
MAX_STATEMENTS = 500
MAX_DEPTH = 24
MAX_MODELS = 50
MAX_SOFT_ENUM = 256
TIMEOUT_S = 5.0
CLINGO_VERSION = "5.8.3"
RULE_VERSION = "vil-rule-v1"
PRIOR_N = 2.0
SCALE = 1000  # clingo weights are integers: log-odds × SCALE

PRELUDE = """
conflict(norm, A) :- obligatory(A), forbidden(A).
violation(A) :- obligatory(A), not done(A).
permitted(A) :- obligatory(A).
"""
_RESERVED = ("vi__", "neg__")


class LogicError(ValueError):
    """The notation is wrong — the message names where and why."""


def extra_dirs() -> list[Path]:
    """Where `vi-mcp logic install` puts clingo when the distribution has no package (Debian/Ubuntu): pip --target into a directory of
    its own, appended to sys.path after the system's packages — never into the system Python (PEP 668)."""
    dirs = [os.environ["VI_MCP_EXTRA_PYTHON"]] if os.environ.get("VI_MCP_EXTRA_PYTHON") else []
    dirs += ["/var/lib/vi-mcp/python", "~/.local/share/vi-mcp/python"] if os.name != "nt" else []
    return [Path(d).expanduser() for d in dirs]


_REASON = ""


def available() -> bool:
    global _REASON
    try:
        import clingo  # noqa: F401
        return True
    except ImportError as e:
        _REASON = str(e)
    for d in extra_dirs():
        if (d / "clingo").is_dir() and str(d) not in sys.path:
            sys.path.append(str(d))
            try:
                import clingo  # noqa: F401,F811
                return True
            except ImportError as e:  # e.g. built for another Python version — said, not hidden
                _REASON = f"{d}: {e}"
    return False


def unavailable_reason() -> str:
    return _REASON or "clingo is not installed"


def install(target: Path | None = None) -> int:
    """vi-mcp logic install [--target DIR] — clingo from PyPI into a directory of its own (it brings cffi and pycparser)."""
    import subprocess
    if available() and target is None:
        import clingo
        print(f"clingo {clingo.__version__} is already importable")
        return 0
    if target is None:
        target = extra_dirs()[-2] if os.name != "nt" and os.geteuid() == 0 else extra_dirs()[-1] if os.name != "nt" else None
    if target is None:  # Windows: the venv of install.ps1 has pip
        cmd = [sys.executable, "-m", "pip", "install", f"clingo=={CLINGO_VERSION}"]
    else:
        target.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(target), f"clingo=={CLINGO_VERSION}"]
    print("running: " + " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        print("pip failed — without pip: apt install python3-pip (Debian/Ubuntu) or dnf install python3-clingo (Fedora); behind a proxy set https_proxy")
        return r.returncode
    ok = available()
    print("clingo importable — restart the service so it loads it" if ok else f"still not importable: {unavailable_reason()}")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    """vi-mcp logic install [--target DIR] | status | check FILE | ask FILE ATOM…"""
    import json
    cmd = argv[0] if argv else "status"
    if cmd == "install":
        return install(Path(argv[argv.index("--target") + 1]) if "--target" in argv else None)
    if cmd == "status":
        if available():
            import clingo
            print(f"logic layer: clingo {clingo.__version__} (tested with {CLINGO_VERSION})")
            return 0
        print(f"logic layer off: {unavailable_reason()} — vi-mcp logic install")
        return 1
    if cmd in ("check", "ask") and len(argv) >= 2:
        if not available():
            print(f"logic layer off: {unavailable_reason()} — vi-mcp logic install")
            return 1
        src = Path(argv[1]).read_text(encoding="utf-8")
        try:
            if cmd == "check":
                print("\n".join(lines(check(src))))
            else:
                print(json.dumps(ask(src, argv[2:]), indent=2, ensure_ascii=False))
        except LogicError as e:
            print(f"notation: {e}")
            return 2
        return 0
    print(main.__doc__)
    return 2


# ── reading the notation ────────────────────────────────────────────────────

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_VAR = re.compile(r"^[A-Z_][A-Za-z0-9_]*$")


def _depth(node, d=0) -> int:
    return max([d] + [_depth(c, d + 1) for c in ast.iter_child_nodes(node)])


def _ident(name: str, line) -> str:
    if name.startswith(_RESERVED):
        raise LogicError(f"line {line}: names starting with vi__ or neg__ are reserved")
    return name


def _term(n) -> str:
    if isinstance(n, ast.Constant) and isinstance(n.value, bool):
        raise LogicError(f"line {n.lineno}: true/false are not terms — use a fact or its strong negation")
    if isinstance(n, ast.Constant) and isinstance(n.value, int):
        return str(n.value)
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        if len(n.value) > 200:
            raise LogicError(f"line {n.lineno}: string longer than 200 characters")
        return '"' + n.value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(n, ast.Name):
        if _VAR.match(n.id):
            return n.id
        if _IDENT.match(n.id):
            return _ident(n.id, n.lineno)
        raise LogicError(f"line {n.lineno}: name {n.id!r} — constants are lower case, variables start with a capital")
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub) and isinstance(n.operand, ast.Constant) and isinstance(n.operand.value, int):
        return str(-n.operand.value)
    if isinstance(n, ast.Call):
        return _atom(n)
    raise LogicError(f"line {getattr(n, 'lineno', '?')}: {type(n).__name__} is not a term (allowed: names, strings, integers, f(…))")


def _atom(n) -> str:
    if isinstance(n, ast.Name) and _IDENT.match(n.id) and n.id not in ("never", "soft"):  # a proposition without arguments: a, raining
        return _ident(n.id, n.lineno)
    if isinstance(n, (ast.Compare, ast.Name)) and not (isinstance(n, ast.Name) and _IDENT.match(n.id)):
        raise LogicError(f"line {getattr(n, 'lineno', '?')}: expected a predicate — a comparison inside a rule goes in parentheses, "
                         "e.g. bad <= in_(P, H) & in_(Q, H) & (P < Q), because & binds tighter than < in Python")
    if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Name) or not _IDENT.match(n.func.id):
        raise LogicError(f"line {getattr(n, 'lineno', '?')}: expected a predicate like zone(\"gate1\", \"dmz\") (lower-case name)")
    if n.keywords:
        raise LogicError(f"line {n.lineno}: keyword arguments are not part of the notation")
    if n.func.id in ("never", "soft"):
        raise LogicError(f"line {n.lineno}: {n.func.id}(…) is a statement of its own, not a term")
    _ident(n.func.id, n.lineno)
    return f"{n.func.id}({','.join(_term(a) for a in n.args)})" if n.args else n.func.id  # no blanks: as clingo prints symbols


_CMP = {ast.Eq: "=", ast.NotEq: "!=", ast.Lt: "<", ast.Gt: ">", ast.GtE: ">="}


def _literal(n) -> str:
    """One body literal: atom, ~atom (not derivable), -atom (explicitly false), or a comparison."""
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Invert):
        return "not " + _literal(n.operand)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return "-" + _atom(n.operand)
    if isinstance(n, ast.Compare):
        if len(n.ops) != 1 or type(n.ops[0]) not in _CMP:
            raise LogicError(f"line {n.lineno}: comparisons allowed in a body: == != < > >= (one at a time; <= is the rule arrow)")
        return f"{_term(n.left)} {_CMP[type(n.ops[0])]} {_term(n.comparators[0])}"
    return _atom(n)


def _conj(n) -> list[str]:
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitAnd):
        return _conj(n.left) + _conj(n.right)
    return [_literal(n)]


def _head(n) -> str:
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return "-" + _atom(n.operand)
    return _atom(n)


def _as_term(head: str) -> str:
    """A head atom as a term for vi__fired: -p(x) becomes vi__neg(p(x))."""
    return f"vi__neg({head[1:]})" if head.startswith("-") else head


def rule_hash(asp_rule: str) -> str:
    return hashlib.sha256(f"{RULE_VERSION}|{asp_rule}".encode()).hexdigest()


def translate(source: str) -> tuple[str, list[dict]]:
    """The notation → an ASP program (without weights) and the list of statements (art, nr, line, text, asp, hash, soft, prior).
    Raises LogicError with the reason. Soft rules carry the marker {W<nr>} where their weight goes (`_weighted`)."""
    if len(source or "") > MAX_SOURCE:
        raise LogicError(f"program longer than {MAX_SOURCE} characters")
    try:
        tree = ast.parse(source or "", mode="exec")
    except SyntaxError as e:
        raise LogicError(f"line {e.lineno}: {e.msg}") from None
    if _depth(tree) > MAX_DEPTH:
        raise LogicError(f"nested deeper than {MAX_DEPTH}")
    if len(tree.body) > MAX_STATEMENTS:
        raise LogicError(f"more than {MAX_STATEMENTS} statements")
    out, stmts = [], []
    for i, st in enumerate(tree.body):
        nr = i + 1
        if not isinstance(st, ast.Expr):
            raise LogicError(f"line {st.lineno}: {type(st).__name__} — only facts, rules (head <= body), soft(…) and never(…) are allowed")
        e = st.value
        soft, prior = False, None
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "soft":
            if e.keywords or not 1 <= len(e.args) <= 2:
                raise LogicError(f"line {st.lineno}: soft(rule) or soft(rule, belief between 0 and 1)")
            if len(e.args) == 2:
                b = e.args[1]
                if not (isinstance(b, ast.Constant) and isinstance(b.value, (int, float)) and not isinstance(b.value, bool) and 0 < b.value < 1):
                    raise LogicError(f"line {st.lineno}: the belief of soft(…) is a number strictly between 0 and 1")
                prior = float(b.value)
            soft, e = True, e.args[0]
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "never":
            if soft:
                raise LogicError(f"line {st.lineno}: never(…) is a check, it has no weight")
            if len(e.args) != 1 or e.keywords:
                raise LogicError(f"line {st.lineno}: never(…) takes one condition")
            out.append(f"vi__violated({nr}) :- {', '.join(_conj(e.args[0]))}.")
            stmts.append({"art": "never", "nr": nr, "zeile": st.lineno, "text": ast.unparse(e)})
            continue
        if isinstance(e, ast.Compare) and len(e.ops) == 1 and isinstance(e.ops[0], ast.LtE):
            head, body, art = _head(e.left), _conj(e.comparators[0]), "rule"
        else:
            head, body, art = _head(e), [], "fact"
        asp = f"{head} :- {', '.join(body)}." if body else f"{head}."
        if soft:  # LPMLN → ASP (lpmln2asp): every ground instance may be dropped at a cost; vi__unsat(nr, vars) marks a dropped one
            names = list(dict.fromkeys(x.id for x in ast.walk(e) if isinstance(x, ast.Name) and _VAR.match(x.id) and x.id != "_"))
            inst = "(" + ",".join(names) + ("," if len(names) == 1 else "") + ")"
            nb = body + [f"not vi__unsat({nr},{inst})"]
            out.append(f"{head} :- {', '.join(nb)}.")
            out.append(f"vi__unsat({nr},{inst}) :- {', '.join(body + ['not ' + head])}.")
            out.append(f"vi__fired({nr},{_as_term(head)}) :- {', '.join(nb)}.")
            out.append(f":~ vi__unsat({nr},T). [{{W{nr}}}@0,{nr},T]")
        else:
            out.append(asp)
            out.append(f"vi__fired({nr},{_as_term(head)}) :- {', '.join(body)}." if body else f"vi__fired({nr},{_as_term(head)}).")
        stmts.append({"art": art, "nr": nr, "zeile": st.lineno, "text": ast.unparse(st.value), "asp": asp, "hash": rule_hash(asp),
                      "soft": soft, "prior": prior})
    return "\n".join(out), stmts


# ── weights ─────────────────────────────────────────────────────────────────

def _tables() -> bool:
    from . import memory as g
    try:
        with g.lock:
            g.db().execute("CREATE TABLE IF NOT EXISTS logik_gewicht (hash TEXT PRIMARY KEY, regel TEXT NOT NULL, ja REAL NOT NULL, "
                           "nein REAL NOT NULL, zeit TEXT NOT NULL)")
            g.db().commit()
        return True
    except Exception:  # no memory open (pure use of the module): every rule is unmeasured
        return False


def counts(h: str) -> tuple[float, float]:
    """This memory's (helped, wrong) for a rule."""
    from . import memory as g
    if not _tables():
        return 0.0, 0.0
    with g.lock:
        r = g.db().execute("SELECT ja, nein FROM logik_gewicht WHERE hash = ?", (h,)).fetchone()
    return (float(r[0]), float(r[1])) if r else (0.0, 0.0)


def belief(stmt: dict) -> dict:
    """The rule's probability: the stated belief as PRIOR_N pseudo-observations (0.5 without one) plus own and network counters."""
    from . import word_weights
    y, n_ = counts(stmt["hash"])
    p0 = stmt.get("prior") if stmt.get("prior") is not None else 0.5
    try:
        c = word_weights.combine(y, n_, stmt["hash"])
    except Exception:
        c = {"ja": y, "nein": n_, "netz": 0}
    a, b = PRIOR_N * p0 + c["ja"], PRIOR_N * (1 - p0) + c["nein"]
    p = min(0.99, max(0.01, a / (a + b)))  # unmeasured = the stated belief (0.5 = undecided, weight 0)
    return {"p": round(p, 3), "gewicht": round(math.log(p / (1 - p)), 3), "eigen": [y, n_], "netz": c["netz"]}


def _weighted(program: str, stmts: list[dict]) -> tuple[str, dict[int, float]]:
    w = {s["nr"]: belief(s)["gewicht"] for s in stmts if s.get("soft")}
    for nr, x in w.items():
        program = program.replace(f"{{W{nr}}}", str(round(x * SCALE)))
    return program, w


# ── solving ─────────────────────────────────────────────────────────────────

def _solve(program: str, limit: int = MAX_MODELS, timeout: float | None = None, optimal: bool = False) -> dict:
    import clingo
    timeout = TIMEOUT_S if timeout is None else timeout
    msgs: list[str] = []

    def logger(code, msg):
        if code != clingo.MessageCode.AtomUndefined:  # the built-in deontic predicates need not be used — not worth a note
            msgs.append(" ".join(msg.split())[:200])
    args = [str(limit), "--opt-mode=optN" if optimal else "--opt-mode=ignore"]
    ctl = clingo.Control(args, logger=logger)
    try:
        ctl.add("base", [], PRELUDE + "\n" + program)
        ctl.ground([("base", [])])
    except RuntimeError as e:
        raise LogicError("the program could not be grounded: " + ("; ".join(msgs) or str(e))[:300]) from None
    models: list[set[str]] = []

    def on_model(m):
        if not optimal or m.optimality_proven:
            models.append({str(s) for s in m.symbols(atoms=True)})
    with ctl.solve(on_model=on_model, async_=True) as h:
        finished = h.wait(timeout)
        if not finished:
            h.cancel()
        result = h.get()
    return {"models": models, "satisfiable": bool(result.satisfiable), "timeout": not finished,
            "complete": finished and bool(result.exhausted), "notes": msgs[:5]}


def _cost(model: set[str], w: dict[int, float]) -> float:
    """LPMLN: every dropped ground instance of a soft rule costs the rule's weight."""
    return sum(x * sum(1 for a in model if a.startswith(f"vi__unsat({nr},")) for nr, x in w.items())


def _run(source: str) -> dict:
    """Translate, weight and solve. With soft rules: all stable models with their LPMLN probability where the enumeration is complete,
    otherwise the most probable ones (clingo optimisation) and probabilities marked approximate."""
    program, stmts = translate(source)
    program, w = _weighted(program, stmts)
    if not w:
        r = _solve(program)
        return {**r, "stmts": stmts, "program": program, "w": w, "prob": None, "map": r["models"], "exact": True}
    r = _solve(program, limit=MAX_SOFT_ENUM)
    models = r["models"]
    exact = r["complete"]
    if models:
        zs = [math.exp(-_cost(m, w)) for m in models]
        total = sum(zs)
        prob = [z / total for z in zs]
        best = min(_cost(m, w) for m in models)
        mapm = [m for m in models if abs(_cost(m, w) - best) < 1e-9]
        if not exact:
            o = _solve(program, optimal=True)
            mapm = o["models"] or mapm
    else:
        prob, mapm = [], []
    return {**r, "stmts": stmts, "program": program, "w": w, "prob": prob, "map": mapm, "exact": exact}


def _split(atom: str) -> tuple[bool, str]:
    return (True, atom[1:]) if atom.startswith("-") else (False, atom)


def _visible(a: str) -> bool:
    return not a.startswith(("vi__", "conflict("))


def check(source: str) -> dict:
    """Translate and solve: what follows, which constraints are violated, which contradictions and norm conflicts exist — and, where
    rules are soft or measured, each rule's weight. With soft rules the answer is the most probable stable model(s) (LPMLN MAP)."""
    r = _run(source)
    stmts = r["stmts"]
    if r["timeout"] and not r["models"]:
        return {"zustand": "zeitlimit", "grund": f"no answer within {TIMEOUT_S} s — the search was stopped", "aussagen": len(stmts)}
    if not r["models"]:
        # only strong negation between hard rules can make the translated program unsatisfiable (never(…) only marks): p and -p together
        return {"zustand": "widerspruch", "grund": "the program derives an atom and its strong negation (p and -p) — see contradictions",
                "widersprueche": _contradictions(r["program"]), "aussagen": len(stmts), "hinweise": r["notes"]}
    best = r["map"]
    common = set.intersection(*best)
    violated = sorted(int(a[13:-1]) for a in common if a.startswith("vi__violated("))
    by_nr = {s["nr"]: s for s in stmts}
    conflicts = sorted(a for a in common if a.startswith("conflict("))
    derived = sorted(a for a in common if _visible(a))
    rules = []
    for s in stmts:
        if s["art"] == "never":
            continue
        b = belief(s)
        if s["soft"] or sum(b["eigen"]) or b["netz"]:
            dropped = sorted({a for m in best for a in m if a.startswith(f"vi__unsat({s['nr']},")})
            rules.append({"nr": s["nr"], "zeile": s["zeile"], "regel": s["text"], "soft": s["soft"], "p": b["p"], "gewicht": b["gewicht"],
                          "gemessen": b["eigen"], "netz": b["netz"], **({"verworfen": len(dropped)} if s["soft"] and dropped else {}),
                          **({"hinweis": "hard rule measured mostly wrong — make it soft(…) or correct it"}
                             if not s["soft"] and b["eigen"][1] > b["eigen"][0] + 2 else {})})
    out = {"zustand": "verletzt" if violated or conflicts else "erfuellt",
           "modelle": len(r["models"]) if r["complete"] else f"≥ {len(r['models'])}", "vollstaendig": bool(r["complete"]),
           "verletzt": [{"nr": n, "zeile": by_nr[n]["zeile"], "never": by_nr[n]["text"]} for n in violated],
           "normkonflikte": conflicts, "folgerungen": derived[:200], "nur_in_einigen": len({a for m in best for a in m if _visible(a)} - common),
           "aussagen": len(stmts), "hinweise": r["notes"], "evidenz": "inferred"}
    if rules:
        out["regeln"] = rules
    if r["w"]:
        out["wahrscheinlichste"] = len(best)
        out["wahrscheinlichkeit"] = "exact over all stable models" if r["exact"] else f"approximate: {len(r['models'])} of more stable models"
        out["verletzt_p"] = {s["nr"]: round(sum(p for m, p in zip(r["models"], r["prob"]) if f"vi__violated({s['nr']})" in m), 3)
                             for s in stmts if s["art"] == "never"}
    return out


def _contradictions(program: str) -> list[str]:
    """Which atoms are derived together with their strong negation — solved again with strong negation renamed, so the contradiction
    is named instead of making the whole answer vanish (Belnap's 'both')."""
    renamed = re.sub(r"(?<![\w\"])-([a-z][a-z0-9_]*)", r"neg__\1", program)
    preds = set(re.findall(r"neg__([a-z][a-z0-9_]*)", renamed))
    extra = "\n".join(f"vi__both({p}(X)) :- {p}(X), neg__{p}(X).\nvi__both({p}) :- {p}, neg__{p}." for p in preds)
    try:
        r = _solve(renamed + "\n" + extra, limit=1)
    except LogicError:
        return []
    return sorted({a[9:-1] for m in r["models"] for a in m if a.startswith("vi__both(")})


def _query(q: str) -> str:
    try:
        return _head(ast.parse(q, mode="eval").body)
    except SyntaxError as e:
        raise LogicError(f"query {q!r}: {e.msg}") from None


def ask(source: str, queries: list[str]) -> dict:
    """Answers for atoms in the notation: true, false, both, unknown, not_derived — or undetermined across answer sets. With soft rules
    the value comes from the most probable model(s) and `ask_probabilities` gives P(atom)."""
    qs = [_query(q) for q in queries[:50]]
    r = _run(source)
    if not r["models"]:
        both = set(_contradictions(r["program"]))
        return {q: ("both" if q.lstrip("-") in both else "unknown") for q in qs}
    models = r["map"]
    out = {}
    for q in qs:
        neg, base = _split(q)
        pos_all = all(base in m for m in models)
        neg_all = all(f"-{base}" in m for m in models)
        pos_some = any(base in m for m in models)
        neg_some = any(f"-{base}" in m for m in models)
        if pos_all and not neg_some:
            v = "true"
        elif neg_all and not pos_some:
            v = "false"
        elif pos_some or neg_some:
            v = "undetermined"
        elif re.search(r"\b" + re.escape(base.split("(")[0]) + r"\b", PRELUDE + r["program"]):
            v = "not_derived"  # the program defines the predicate, this instance does not follow (negation as failure) — not "unknown"
        else:
            v = "unknown"  # the program says nothing about the predicate (Kleene: no value)
        if neg and v in ("true", "false"):
            v = "false" if v == "true" else "true"
        out[q] = v
    return out


def ask_probabilities(source: str, queries: list[str]) -> dict:
    """P(atom) under LPMLN: the summed probability of the stable models containing it. Without soft rules every model is equally likely."""
    qs = [_query(q) for q in queries[:50]]
    r = _run(source)
    if not r["models"]:
        return {q: None for q in qs}
    prob = r["prob"] or [1 / len(r["models"])] * len(r["models"])
    return {q: round(sum(p for m, p in zip(r["models"], prob) if q in m), 3) for q in qs} | {"_exact": r["exact"]}


def rate(source: str, conclusion: str, correct: bool) -> dict:
    """A conclusion was checked against reality: credit (or blame) exactly the rules that derive it in some stable model.
    A correct conclusion no rule derives teaches nothing here — it points to a missing rule, which is reported, not invented."""
    from . import memory as g
    q = _query(conclusion)
    r = _run(source)
    if not r["models"]:
        raise LogicError("the program has no stable model — resolve the contradiction first (check)")
    term = _as_term(q)
    by_nr = {s["nr"]: s for s in r["stmts"]}
    # every rule that derives the conclusion in some stable model — not only the most probable one, or a rule once outweighed
    # could never earn its weight back
    credited = sorted({nr for nr, s in by_nr.items() if s["art"] != "never" and any(f"vi__fired({nr},{term})" in m for m in r["models"])})
    if not credited:
        return {"gutgeschrieben": [], "grund": "no rule derives this conclusion in any stable model — "
                + ("a missing rule (the VI learns weights, not new rules)" if correct else "nothing to blame")}
    if not _tables():
        raise LogicError("no memory open — weights cannot be stored")
    now = g.now()
    with g.lock:
        for nr in credited:
            s = by_nr[nr]
            row = g.db().execute("SELECT ja, nein FROM logik_gewicht WHERE hash = ?", (s["hash"],)).fetchone()
            y, n_ = (float(row[0]), float(row[1])) if row else (0.0, 0.0)
            y, n_ = (y + 1, n_) if correct else (y, n_ + 1)
            g.db().execute("DELETE FROM logik_gewicht WHERE hash = ?", (s["hash"],))
            g.db().execute("INSERT INTO logik_gewicht (hash, regel, ja, nein, zeit) VALUES (?,?,?,?,?)", (s["hash"], s["asp"], y, n_, now))
        g.db().commit()
    return {"gutgeschrieben": [{"nr": nr, "regel": by_nr[nr]["text"], **{k: v for k, v in belief(by_nr[nr]).items() if k in ("p", "gewicht", "eigen")}}
                               for nr in credited], "richtig": bool(correct)}


# ── exchange (the same rating channel as the word weights) ─────────────────

def known_hash(h: str) -> bool:
    from . import memory as g
    if not _tables():
        return False
    with g.lock:
        return bool(g.db().execute("SELECT 1 FROM logik_gewicht WHERE hash = ?", (h,)).fetchone())


def outgoing(net: str, limit: int = 1000) -> list[dict]:
    """Measured rule weights as ratings. An open network gets only rules without string constants and without anything the
    anonymisation flags — a hash of a rule that names a host or a person could be confirmed by guessing; a company network gets all."""
    from . import anonymize, p2p
    from . import memory as g
    from .word_weights import MIN_N
    if not _tables():
        return []
    company = p2p.is_company(net)
    with g.lock:
        rows = g.db().execute("SELECT hash, regel, ja, nein FROM logik_gewicht WHERE ja + nein >= ? ORDER BY ja + nein DESC LIMIT ?",
                              (MIN_N, limit)).fetchall()
    return [{"ziel": h, "gezeigt": round(y + n_, 2), "ja": round(y, 2), "nein": round(n_, 2), "bestaetigt": 0, "widerlegt": 0}
            for h, text, y, n_ in rows if company or ('"' not in text and not anonymize.categories(text))]


def lines(r: dict) -> list[str]:
    """A check result for people and agents."""
    if r["zustand"] in ("zeitlimit", "widerspruch"):
        return [f"state: {r['zustand']} — {r['grund']}"] + [f"  both: {a}" for a in r.get("widersprueche", [])]
    out = [f"state: {'violated' if r['zustand'] == 'verletzt' else 'satisfied'} · {r['aussagen']} statements · stable models: {r['modelle']}"
           + (f" · most probable: {r['wahrscheinlichste']} ({r['wahrscheinlichkeit']})" if "wahrscheinlichste" in r else "")
           + " · evidence: inferred"]
    out += [f"  violated never #{v['nr']} (line {v['zeile']}): {v['never']}"
            + (f" · P = {r['verletzt_p'].get(v['nr'])}" if r.get("verletzt_p") else "") for v in r["verletzt"]]
    out += [f"  norm conflict: {c}" for c in r["normkonflikte"]]
    for x in r.get("regeln", []):
        out.append(f"  rule #{x['nr']} (line {x['zeile']}) {'soft' if x['soft'] else 'hard'} · p {x['p']} · weight {x['gewicht']} · measured "
                   f"{x['gemessen'][0]:g} right / {x['gemessen'][1]:g} wrong · network {x['netz']}" + (f" · {x['verworfen']} instance(s) dropped in the answer" if x.get("verworfen") else "")
                   + (f" · {x['hinweis']}" if x.get("hinweis") else ""))
    out.append(f"  follows ({len(r['folgerungen'])}): " + ", ".join(r["folgerungen"][:40]) + (" …" if len(r["folgerungen"]) > 40 else ""))
    if not r["vollstaendig"]:
        out.append(f"  not every answer set was seen (limit {MAX_MODELS} or {TIMEOUT_S} s) — what 'follows' holds in the ones seen")
    if r["nur_in_einigen"]:
        out.append(f"  {r['nur_in_einigen']} atoms hold only in some answer sets (undetermined)")
    out += [f"  note: {n}" for n in r["hinweise"]]
    return out

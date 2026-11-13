"""clingo-object: the language core — a Python-like notation translated to answer set programming and solved with clingo.

One language for the VI server (vi_mcp.logic runs exactly this core on programs that arrive as text) and for the Python package
clingo-object on a trusted machine (its classes and methods compile to this notation). The notation is read by `ast` against a
whitelist and never executed; clingo receives only the translated program, never #script.

Notation:
  zone("gate1", "dmz")                                   a fact
  forbidden(run(R, H)) <= zone(H, "dmz") & planned(run(R, H))
                                                        a rule: head <= body; & is "and"; capitalised names are variables
  ~done(A)                                              not derivable (negation as failure)
  -allowed(A)                                           explicitly false (strong negation)
  never(planned(A) & forbidden(A))                      a constraint — a violation is REPORTED with its number, not silently UNSAT
  (H != "gate1"), (N > 3), (H == "web1")                 comparisons inside a body, in parentheses (& binds tighter than <)
  soft(head <= body)  soft(head <= body, 0.9)  soft(fact)
                                                        a rule with a weight (the optional number is the prior belief)
Objects of the VI memory (0.63.0, clingo-objekt): (O in objects("art:skill host:web*")) binds O to the objects of a filter;
(O.host == H) reads a hashtag, (O.kind == "skill") a field, numbers compare: (O.age > 90); linked(O, B) follows an edge;
propose(tag(O, "kind", "value")) / propose(link(A, B, "reason")) as a head proposes a change that a person decides.
Built in (the deontic square, SEP "Deontic Logic"): obligatory/forbidden/permitted; obligatory(A) and forbidden(A) together is a named
conflict (axiom NC); violation(A) :- obligatory(A), not done(A).

Nothing vanishes silently: p and -p together is reported as a contradiction (Belnap's "both") instead of the empty answer; an answer is
true, false, both, unknown — or undetermined when answer sets disagree, or not_derived when the program defines the predicate but this
instance does not follow. What the engine derives is evidence `inferred`, never `measured`.

Soft rules follow LPMLN (Lee & Wang, KR 2018, https://arxiv.org/abs/1808.04527) in the lpmln2asp scheme of plingo
(https://arxiv.org/abs/2206.11515). Weights come from a `belief` function: here the stated prior only; the VI server passes one with
measured counters (vi_mcp.logic.belief).
"""
from __future__ import annotations

import ast
import contextvars
import hashlib
import math
import re

MAX_SOURCE = 20_000


MAX_STATEMENTS = 500


MAX_DEPTH = 24


MAX_MODELS = 50


MAX_SOFT_ENUM = 256


TIMEOUT_S = 5.0


CLINGO_VERSION = "5.8.3"  # tested with; `vi-mcp logic install` installs exactly this one
#: the one place the minimum clingo is stated — the wheel's Requires-Dist (deploy/clingo-object/build_wheel.py) and the check below
CLINGO_MIN = "5.8"


RULE_VERSION = "vil-rule-v1"


PRIOR_N = 2.0


SCALE = 1000  # clingo weights are integers: log-odds × SCALE


MAX_FILTERS = 20


#: O.<field> → the objekt column; any other attribute name is a hashtag kind (O.host → host:…)
OBJ_FIELDS = {"kind": "art", "mode": "modus", "visibility": "sicht", "instance": "instanz", "index": "idx", "text": "text",
              # numbers (0.63.0): age in days, importance 0–3, confirmations, refutations, accesses
              "age": "zeit", "importance": "wichtigkeit", "confirmed": "bestaetigt", "refuted": "widerlegt", "accesses": "zugriffe"}


_DIALECT = ("objects", "linked", "propose")


PRELUDE = """
conflict(norm, A) :- obligatory(A), forbidden(A).
violation(A) :- obligatory(A), not done(A).
permitted(A) :- obligatory(A).
"""


_RESERVED = ("vi__", "neg__")


class LogicError(ValueError):
    """The notation is wrong — the message names where and why."""


#: per translation: the filters of objects(…) in order, and per statement the object variables bound and used
_STATE: contextvars.ContextVar[dict | None] = contextvars.ContextVar("logic_state", default=None)


def _state() -> dict:
    st = _STATE.get()
    if st is None:
        st = {"filters": [], "bound": set(), "used": {}, "fresh": 0, "nr": 0}
        _STATE.set(st)
    return st


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
        if n.id.startswith("Vi__"):
            raise LogicError(f"line {n.lineno}: variables starting with Vi__ are reserved")
        if _VAR.match(n.id):
            return n.id
        if _IDENT.match(n.id):
            return _ident(n.id, n.lineno)
        raise LogicError(f"line {n.lineno}: name {n.id!r} — constants are lower case, variables start with a capital")
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub) and isinstance(n.operand, ast.Constant) and isinstance(n.operand.value, int):
        return str(-n.operand.value)
    if isinstance(n, ast.Call):
        return _atom(n)
    if isinstance(n, ast.Attribute):
        raise LogicError(f"line {n.lineno}: a field like {getattr(n.value, 'id', '?')}.{n.attr} is read in a comparison of its own: "
                         f"({getattr(n.value, 'id', '?')}.{n.attr} == V), then use V")
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
    if n.func.id == "objects":
        raise LogicError(f"line {n.lineno}: objects(\"filter\") binds a variable: (O in objects(\"art:skill\")) — in parentheses")
    if n.func.id in ("linked", "propose"):
        raise LogicError(f"line {n.lineno}: {n.func.id}(…) is a word of the object dialect — linked(O, B) only in a body, "
                         "propose(tag(…)) / propose(link(…)) only as a head")
    _ident(n.func.id, n.lineno)
    return f"{n.func.id}({','.join(_term(a) for a in n.args)})" if n.args else n.func.id  # no blanks: as clingo prints symbols


_CMP = {ast.Eq: "=", ast.NotEq: "!=", ast.Lt: "<", ast.Gt: ">", ast.GtE: ">="}


_FIELD_CMP = {ast.Eq: "=", ast.Lt: "<", ast.Gt: ">", ast.GtE: ">=", ast.LtE: "<="}


_MIRROR = {ast.Lt: ast.Gt, ast.Gt: ast.Lt, ast.GtE: ast.LtE, ast.LtE: ast.GtE}


def _objvar(n, what: str) -> str:
    if not (isinstance(n, ast.Name) and _VAR.match(n.id)):
        raise LogicError(f"line {getattr(n, 'lineno', '?')}: {what} needs an object variable (capitalised), e.g. O")
    return n.id


def _attribute(a: ast.Attribute, other, op: str = "=") -> str:
    """O.field == term → vi__obj / vi__tag (0.63.0); O.age > 90 and the like through a fresh variable."""
    var = _objvar(a.value, f"{getattr(a.value, 'id', '?')}.{a.attr}")
    _state()["used"].setdefault(var, a.lineno)
    if isinstance(other, ast.Attribute):
        raise LogicError(f"line {a.lineno}: compare a field with a value or a variable, not with another field — bind it first: "
                         f"({var}.{a.attr} == V) & (P.{other.attr} == V)")
    val = _term(other)
    if a.attr in OBJ_FIELDS:
        pred = f'vi__obj({var},"{a.attr}",'
    elif re.fullmatch(r"[a-z][a-z0-9_]{0,30}", a.attr):
        pred = f'vi__tag({var},"{a.attr}",'
    else:
        raise LogicError(f"line {a.lineno}: {a.attr!r} is no hashtag kind (lower case, digits, _)")
    if op == "=":
        return pred + val + ")"
    st = _state()
    st["fresh"] += 1
    x = f"Vi__{st['fresh']}"
    return f"{pred}{x}), {x} {op} {val}"


def _literal(n) -> str:
    """One body literal: atom, ~atom (not derivable), -atom (explicitly false), or a comparison — and, in the object dialect (0.63.0),
    (O in objects("filter")), (O.field == value), linked(O, B)."""
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Invert):
        o = n.operand
        if (isinstance(o, ast.Compare) and len(o.ops) == 1 and not isinstance(o.ops[0], ast.Eq)
                and (isinstance(o.left, ast.Attribute) or isinstance(o.comparators[0], ast.Attribute))):
            raise LogicError(f"line {n.lineno}: write the opposite comparison instead of ~(…), e.g. (O.age <= 90) for ~(O.age > 90)")
        return "not " + _literal(o)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return "-" + _atom(n.operand)
    if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.In):
        c = n.comparators[0]
        if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "objects" and len(c.args) == 1 and not c.keywords
                and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str)):
            raise LogicError(f"line {n.lineno}: `in` only as (O in objects(\"filter\")) — the filter is a string as in vi_recall, and the "
                             "whole comparison goes in parentheses because & binds tighter than in")
        var = _objvar(n.left, "objects(…)")
        f = c.args[0].value.strip()
        if not f or len(f) > 300:
            raise LogicError(f"line {n.lineno}: objects(…) needs a filter of 1–300 characters")
        st = _state()
        if f not in st["filters"]:
            if len(st["filters"]) >= MAX_FILTERS:
                raise LogicError(f"line {n.lineno}: at most {MAX_FILTERS} different objects(…) filters in one program")
            st["filters"].append(f)
        st["bound"].add(var)
        return f"vi__in({st['filters'].index(f)},{var})"
    if isinstance(n, ast.Compare) and len(n.ops) == 1 and (isinstance(n.left, ast.Attribute) or isinstance(n.comparators[0], ast.Attribute)):
        op = type(n.ops[0])
        if op not in _FIELD_CMP:
            raise LogicError(f"line {n.lineno}: a field is compared with == < > <= >=; for \"not\" write ~(O.host == \"web1\")")
        if isinstance(n.left, ast.Attribute):
            return _attribute(n.left, n.comparators[0], _FIELD_CMP[op])
        return _attribute(n.comparators[0], n.left, _FIELD_CMP[_MIRROR.get(op, op)])
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "linked":
        if n.keywords or len(n.args) not in (2, 3):
            raise LogicError(f"line {n.lineno}: linked(O, B) or linked(O, B, reason)")
        var = _objvar(n.args[0], "linked(…)")
        _state()["used"].setdefault(var, n.lineno)
        if isinstance(n.args[1], ast.Name) and _VAR.match(n.args[1].id):  # edges exist only between imported objects: B is an object
            _state()["bound"].add(n.args[1].id)
        return f"vi__edge({','.join(_term(x) for x in n.args)})"
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
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "propose":
        a = n.args[0] if len(n.args) == 1 and not n.keywords else None
        if not (isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id in ("tag", "link") and len(a.args) == 3 and not a.keywords):
            raise LogicError(f"line {n.lineno}: propose(tag(O, \"kind\", \"value\")) or propose(link(A, B, \"reason\"))")
        _state()["used"].setdefault(_objvar(a.args[0], "propose(…)"), n.lineno)
        if a.func.id == "link":
            _state()["used"].setdefault(_objvar(a.args[1], "propose(link(…))"), n.lineno)
        return f"vi__propose({a.func.id}({','.join(_term(x) for x in a.args)}))"
    return _atom(n)


def _as_term(head: str) -> str:
    """A head atom as a term for vi__fired: -p(x) becomes vi__neg(p(x))."""
    return f"vi__neg({head[1:]})" if head.startswith("-") else head


def rule_hash(asp_rule: str) -> str:
    return hashlib.sha256(f"{RULE_VERSION}|{asp_rule}".encode()).hexdigest()


def translate(source: str) -> tuple[str, list[dict]]:
    """The notation → an ASP program (without weights) and the list of statements (art, nr, line, text, asp, hash, soft, prior).
    Raises LogicError with the reason. Soft rules carry the marker {W<nr>} where their weight goes (`_weighted`)."""
    program, stmts, _filters = translate_full(source)
    return program, stmts


def translate_full(source: str) -> tuple[str, list[dict], list[str]]:
    """translate, plus the filters of objects(…) in the order their numbers refer to (0.63.0)."""
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
    state = {"filters": [], "bound": set(), "used": {}, "fresh": 0, "nr": 0}
    token = _STATE.set(state)
    try:
        for st in tree.body:
            if isinstance(st, (ast.ClassDef, ast.FunctionDef)):
                raise LogicError(f"line {st.lineno}: classes and methods belong to the Python package clingo-object (import clingo_object), "
                                 "which runs where code is trusted and compiles them to flat rules of this notation — the server runs no Python")
            state["nr"] += 1
            state["bound"], state["used"] = set(), {}
            _statement(state["nr"], st, out, stmts)
            _check_bound()
    finally:
        _STATE.reset(token)
    return "\n".join(out), stmts, list(state["filters"])


def _check_bound() -> None:
    st = _state()
    loose = sorted(v for v in st["used"] if v not in st["bound"])
    if loose:
        raise LogicError(f"line {st['used'][loose[0]]}: object variable {loose[0]} is not bound — add ({loose[0]} in objects(\"filter\")) "
                         "or linked(X, " + loose[0] + ") to the body")


def _statement(nr: int, st, out: list[str], stmts: list[dict]) -> None:
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
        return
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


def _quote(v) -> str:
    return '"' + " ".join(str(v).split()).replace("\\", "\\\\").replace('"', '\\"') + '"'


TEXT_FIELDS = ("kind", "mode", "visibility", "instance", "index", "text")


NUMBER_FIELDS = ("age", "importance", "confirmed", "refuted", "accesses")


def facts(data: dict) -> list[str]:
    """The data of object_data as ASP facts — vi__in(K, O), vi__obj(O, field, value), vi__tag(O, kind, value), vi__edge(A, B[, reason])."""
    out = [f"vi__in({k},{_quote(i)})." for k, ids in enumerate(data["members"]) for i in ids]
    for o in data["objects"]:
        q = _quote(o["id"])
        out += [f'vi__obj({q},"{f}",{_quote(o[f])}).' for f in TEXT_FIELDS if o.get(f) not in (None, "")]
        out += [f'vi__obj({q},"{f}",{int(o[f])}).' for f in NUMBER_FIELDS if o.get(f) is not None]
        out += [f"vi__tag({q},{_quote(k)},{_quote(v)})." for k, vals in o["tags"].items() for v in vals]
    for a_, b_, w in data["edges"]:
        out += [f"vi__edge({_quote(a_)},{_quote(b_)}).", f"vi__edge({_quote(a_)},{_quote(b_)},{_quote(w)})."]
    return out


def _cost(model: set[str], w: dict[int, float]) -> float:
    """LPMLN: every dropped ground instance of a soft rule costs the rule's weight."""
    return sum(x * sum(1 for a in model if a.startswith(f"vi__unsat({nr},")) for nr, x in w.items())


def _split(atom: str) -> tuple[bool, str]:
    return (True, atom[1:]) if atom.startswith("-") else (False, atom)


def _visible(a: str) -> bool:
    return not a.startswith(("vi__", "conflict("))


def proposals(model: set[str]) -> list[dict]:
    """0.63.0: what the rules propose to write — propose(tag(O, kind, value)) / propose(link(A, B, reason)) — with the rule numbers
    that derive each one (its reason chain). Only what holds in every most probable answer set."""
    import clingo
    out = []
    for a in sorted(x for x in model if x.startswith("vi__propose(")):
        sym = clingo.parse_term(a).arguments[0]
        args = [x.string if x.type == clingo.SymbolType.String else str(x) for x in sym.arguments]
        rules = sorted(int(f[10:].split(",", 1)[0]) for f in model if f.startswith("vi__fired(") and f.endswith(f",{a})"))
        p = {"aktion": sym.name, "ziel": args[0], "regeln": rules}
        p.update({"art": args[1], "wert": args[2]} if sym.name == "tag" else {"b": args[1], "grund": args[2]})
        out.append(p)
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
    imp = r.get("importiert")
    if imp:
        out.append(f"  imported {imp['objekte']} objects ({', '.join(f'{f!r}: {n}' for f, n in zip(imp['filter'], imp['je_filter']))}), "
                   f"{imp['fakten']} facts" + (f" · {imp['nicht_sichtbar']} not visible to you" if imp["nicht_sichtbar"] else "")
                   + (f" · {imp['abgeschnitten']} cut (limit {imp.get('limit', '?')} objects) — narrow the filter" if imp["abgeschnitten"] else "")
                   + (f" · {imp['ausgeschlossen']} in quarantine or archive, never imported" if imp["ausgeschlossen"] else "")
                   + (f" · {imp['ueber_kanten']} more one edge away" if imp.get("ueber_kanten") else ""))
    for p in r.get("vorschlaege", []):
        what = f"tag {p['art']}:{p['wert']} on {p['ziel']}" if p["aktion"] == "tag" else f"link {p['ziel']} → {p['b']} ({p['grund']})"
        out.append(f"  proposes {what} · by rule " + ", ".join(f"#{n}" for n in p["regeln"]) + " — vi_logic action=propose holds it for review")
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


# ── engine (weights injected: prior here, measured on the server) ───────────

def prior_belief(stmt: dict) -> dict:
    """A rule's probability from its stated belief alone (0.5 without one) — what a program has before anything was measured."""
    p0 = stmt.get("prior") if stmt.get("prior") is not None else 0.5
    p = min(0.99, max(0.01, p0))
    return {"p": round(p, 3), "gewicht": round(math.log(p / (1 - p)), 3), "eigen": [0, 0], "netz": 0}


def weighted(program: str, stmts: list[dict], belief=prior_belief) -> tuple[str, dict[int, float]]:
    w = {s["nr"]: belief(s)["gewicht"] for s in stmts if s.get("soft")}
    for nr, x in w.items():
        program = program.replace(f"{{W{nr}}}", str(round(x * SCALE)))
    return program, w


def run_program(program: str, stmts: list[dict], belief=prior_belief, timeout: float | None = None) -> dict:
    """Weight and solve. With soft rules: all stable models with their LPMLN probability where the enumeration is complete, otherwise
    the most probable ones (clingo optimisation) and probabilities marked approximate."""
    program, w = weighted(program, stmts, belief)
    if not w:
        r = _solve(program, timeout=timeout)
        return {**r, "stmts": stmts, "program": program, "w": w, "prob": None, "map": r["models"], "exact": True, "timeout_s": timeout or TIMEOUT_S}
    r = _solve(program, limit=MAX_SOFT_ENUM, timeout=timeout)
    models = r["models"]
    exact = r["complete"]
    if models:
        zs = [math.exp(-_cost(m, w)) for m in models]
        total = sum(zs)
        prob = [z / total for z in zs]
        best = min(_cost(m, w) for m in models)
        mapm = [m for m in models if abs(_cost(m, w) - best) < 1e-9]
        if not exact:
            o = _solve(program, optimal=True, timeout=timeout)
            mapm = o["models"] or mapm
    else:
        prob, mapm = [], []
    return {**r, "stmts": stmts, "program": program, "w": w, "prob": prob, "map": mapm, "exact": exact, "timeout_s": timeout or TIMEOUT_S}


def check_result(r: dict, belief=prior_belief) -> dict:
    """What follows, which constraints are violated, which contradictions and norm conflicts exist — and, where rules are soft or
    measured, each rule's weight. With soft rules the answer is the most probable stable model(s) (LPMLN MAP)."""
    stmts = r["stmts"]
    if r["timeout"] and not r["models"]:
        return {"zustand": "zeitlimit", "grund": f"no answer within {r['timeout_s']} s — the search was stopped", "aussagen": len(stmts),
                **({"importiert": r["importiert"]} if r.get("importiert") else {})}
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
    if r.get("importiert"):
        out["importiert"] = r["importiert"]
    props = proposals(common)
    if props:
        out["vorschlaege"] = props
    if r["w"]:
        out["wahrscheinlichste"] = len(best)
        out["wahrscheinlichkeit"] = "exact over all stable models" if r["exact"] else f"approximate: {len(r['models'])} of more stable models"
        out["verletzt_p"] = {s["nr"]: round(sum(p for m, p in zip(r["models"], r["prob"]) if f"vi__violated({s['nr']})" in m), 3)
                             for s in stmts if s["art"] == "never"}
    return out


def ask_result(r: dict, qs: list[str]) -> dict:
    """Answers for (already translated) query atoms: true, false, both, unknown, not_derived — or undetermined across answer sets."""
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


def probabilities_result(r: dict, qs: list[str]) -> dict:
    """P(atom) under LPMLN: the summed probability of the stable models containing it. Without soft rules every model is equally likely."""
    if not r["models"]:
        return {q: None for q in qs}
    prob = r["prob"] or [1 / len(r["models"])] * len(r["models"])
    return {q: round(sum(p for m, p in zip(r["models"], prob) if q in m), 3) for q in qs} | {"_exact": r["exact"]}


def check(source: str, facts_text: str = "", belief=prior_belief, timeout: float | None = None) -> dict:
    """Translate, add facts (e.g. memory objects as facts) and check — the whole path for a program that needs no memory of its own."""
    program, stmts, _filters = translate_full(source)
    r = run_program((facts_text + "\n" + program) if facts_text else program, stmts, belief, timeout)
    return check_result(r, belief)


def ask(source: str, queries: list[str], facts_text: str = "", belief=prior_belief, timeout: float | None = None) -> dict:
    qs = [_query(q) for q in queries[:50]]
    program, stmts, _filters = translate_full(source)
    return ask_result(run_program((facts_text + "\n" + program) if facts_text else program, stmts, belief, timeout), qs)


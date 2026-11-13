"""Expressions of clingo-object as real Python objects — operator overloading builds the notation of clingo_object.notation.

    H = Var("H")
    O = Obj("O")
    rel.in_dmz(H) <= O.where("zone:dmz") & (O.host == H)        → in_dmz(H) <= (O in objects("zone:dmz")) & (O.host == H)

Python gives `==`, `<`, `&`, `~`, `-` and `<=` their meaning here; `in` cannot be overloaded to return an expression (Python turns its
result into a bool), so membership is O.where("filter"). As in the notation, a comparison inside & goes in parentheses: & binds tighter.
"""
from __future__ import annotations

import re

_VAR = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED = ("objects", "linked", "propose", "never", "soft", "tag", "link")


class ExprError(ValueError):
    """An expression that has no form in the notation — said where it is built, not later on the server."""


def term(x) -> str:
    """A Python value as a term of the notation."""
    if isinstance(x, bool):
        raise ExprError("true/false are not terms — use a fact or its strong negation")
    if isinstance(x, int):
        return str(x)
    if isinstance(x, str):
        if len(x) > 200:
            raise ExprError("string longer than 200 characters")
        return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(x, (Var, Atom)):
        return x.notation()
    raise ExprError(f"{type(x).__name__} is not a term (allowed: Var, str, int, a predicate)")


class Literal:
    """Something that can stand in a body: & joins, ~ negates (not derivable)."""

    def notation(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def __and__(self, other: "Literal") -> "Conj":
        return Conj(_parts(self) + _parts(other))

    def __invert__(self) -> "Literal":
        return Not(self)

    def __bool__(self):
        raise ExprError("an expression has no truth value in Python — combine with & and ~, compare in parentheses")

    def __repr__(self):
        return self.notation()


def _parts(x) -> list:
    if isinstance(x, Conj):
        return list(x.parts)
    if not isinstance(x, Literal):
        raise ExprError(f"{x!r} cannot be joined with & — a comparison goes in parentheses: (O.host == H)")
    return [x]


class Conj(Literal):
    def __init__(self, parts: list):
        self.parts = parts

    def notation(self) -> str:
        return " & ".join(p.notation() for p in self.parts)


class Not(Literal):
    def __init__(self, inner: Literal):
        if isinstance(inner, FieldCmp) and inner.op != "==":
            raise ExprError("write the opposite comparison instead of ~(…), e.g. (O.age <= 90) for ~(O.age > 90)")
        if isinstance(inner, Conj):
            raise ExprError("~ applies to one literal — name the conjunction as a predicate first")
        self.inner = inner

    def notation(self) -> str:
        return "~" + self.inner.notation()


class Cmp(Literal):
    def __init__(self, left, op: str, right):
        self.left, self.op, self.right = left, op, right

    def notation(self) -> str:
        return f"({term(self.left)} {self.op} {term(self.right)})"


class Var:
    """A logic variable (capitalised). Comparisons build literals, so a Var is hashed by identity."""

    def __init__(self, name: str):
        if not _VAR.match(name) or name.startswith("Vi__"):
            raise ExprError(f"variable {name!r}: starts with a capital letter (Vi__ is reserved)")
        self.name = name

    def notation(self) -> str:
        return self.name

    __hash__ = object.__hash__

    def __eq__(self, other):
        return Cmp(self, "==", other)

    def __ne__(self, other):
        return Cmp(self, "!=", other)

    def __lt__(self, other):
        return Cmp(self, "<", other)

    def __gt__(self, other):
        return Cmp(self, ">", other)

    def __ge__(self, other):
        return Cmp(self, ">=", other)

    def __repr__(self):
        return self.name


class Obj(Var):
    """A variable that stands for a memory object: O.where("filter") binds it, O.host / O.kind / O.age read fields, O.stale() calls a
    method of the classes in the program."""

    def where(self, filter_text: str) -> "In":
        return In(self, filter_text)

    def __getattr__(self, name: str) -> "Field":
        if name.startswith("_"):
            raise AttributeError(name)
        if not _IDENT.match(name):
            raise ExprError(f"{name!r} is no field or hashtag kind (lower case, digits, _)")
        return Field(self, name)


class In(Literal):
    def __init__(self, obj: Obj, filter_text: str):
        if not isinstance(obj, Obj):
            raise ExprError("where(…) binds an Obj")
        if not str(filter_text).strip():
            raise ExprError("where(…) needs a vi_recall filter with at least one kind:value")
        self.obj, self.filter = obj, str(filter_text).strip()

    def notation(self) -> str:
        return f"({self.obj.name} in objects({term(self.filter)}))"


class Field:
    """O.<field>: compared it becomes a literal; called it is a method call."""

    def __init__(self, obj: Obj, name: str):
        self.obj, self.name = obj, name

    def _cmp(self, op: str, other) -> "FieldCmp":
        if isinstance(other, Field):
            raise ExprError(f"compare a field with a value or a variable, not with another field — bind it first: "
                            f"({self.obj.name}.{self.name} == V) & (…{other.name} == V)")
        return FieldCmp(self, op, other)

    __hash__ = object.__hash__

    def __eq__(self, other):
        return self._cmp("==", other)

    def __ne__(self, other):
        raise ExprError(f'a field is compared with == < > <= >=; for "not" write ~({self.obj.name}.{self.name} == …)')

    def __lt__(self, other):
        return self._cmp("<", other)

    def __gt__(self, other):
        return self._cmp(">", other)

    def __ge__(self, other):
        return self._cmp(">=", other)

    def __le__(self, other):
        return self._cmp("<=", other)

    def __call__(self, *args) -> "Atom":
        if self.name in RESERVED:
            raise ExprError(f"{self.name} is a word of the dialect, not a method")
        return Atom(self.name, (self.obj,) + args)


class FieldCmp(Literal):
    def __init__(self, field: Field, op: str, value):
        self.field, self.op, self.value = field, op, value

    def notation(self) -> str:
        return f"({self.field.obj.name}.{self.field.name} {self.op} {term(self.value)})"


class Atom(Literal):
    """A predicate with arguments. -atom is its strong negation; atom <= body is a rule."""

    def __init__(self, name: str, args: tuple = (), negated: bool = False):
        if not _IDENT.match(name) or name.startswith(("vi__", "neg__")):
            raise ExprError(f"predicate {name!r}: lower case, digits, _ (vi__/neg__ are reserved)")
        self.name, self.args, self.negated = name, tuple(args), negated

    def notation(self) -> str:
        core = f"{self.name}({', '.join(term(a) for a in self.args)})" if self.args else self.name
        return ("-" if self.negated else "") + core

    def __neg__(self) -> "Atom":
        return Atom(self.name, self.args, not self.negated)

    def __le__(self, body) -> "Rule":
        return Rule(self, body)

    __hash__ = object.__hash__


class Rel:
    """rel.planned(R, H) → the atom planned(R, H) — predicates are made by name."""

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in RESERVED:
            raise ExprError(f"{name} is a word of the dialect — use linked(…), propose_tag(…), propose_link(…), never(…), soft(…)")
        return lambda *args: Atom(name, args)


rel = Rel()


class Linked(Literal):
    def __init__(self, a: Obj, b, reason=None):
        if not isinstance(a, Obj):
            raise ExprError("linked(O, B) starts at an Obj")
        self.a, self.b, self.reason = a, b, reason

    def notation(self) -> str:
        return f"linked({self.a.name}, {term(self.b)}" + (f", {term(self.reason)})" if self.reason is not None else ")")


def linked(a: Obj, b, reason=None) -> Linked:
    return Linked(a, b, reason)


class Head:
    """propose(tag(…)) / propose(link(…)) — heads only."""

    def __init__(self, text: str):
        self.text = text

    def notation(self) -> str:
        return self.text

    def __le__(self, body) -> "Rule":
        return Rule(self, body)


def propose_tag(o: Obj, kind: str, value) -> Head:
    return Head(f"propose(tag({o.name}, {term(kind)}, {term(value)}))")


def propose_link(a: Obj, b: Obj, reason: str) -> Head:
    return Head(f"propose(link({a.name}, {b.name}, {term(reason)}))")


class Statement:
    def notation(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def __repr__(self):
        return self.notation()


class Rule(Statement):
    def __init__(self, head, body):
        if isinstance(body, bool):
            raise ExprError("the body is a Python bool — a comparison inside & needs parentheses: rel.p(H) <= (O.host == H) & …")
        _parts(body)  # raises for anything that is no literal
        self.head, self.body = head, body

    def notation(self) -> str:
        return f"{self.head.notation()} <= {self.body.notation()}"


class Fact(Statement):
    def __init__(self, atom: Atom):
        self.atom = atom

    def notation(self) -> str:
        return self.atom.notation()


class Never(Statement):
    def __init__(self, body: Literal):
        _parts(body)
        self.body = body

    def notation(self) -> str:
        return f"never({self.body.notation()})"


class Soft(Statement):
    def __init__(self, rule, belief: float | None = None):
        if belief is not None and not 0 < belief < 1:
            raise ExprError("the belief of soft(…) is a number strictly between 0 and 1")
        self.rule, self.belief = (rule if isinstance(rule, Statement) else Fact(rule)), belief

    def notation(self) -> str:
        return f"soft({self.rule.notation()}" + (f", {self.belief})" if self.belief is not None else ")")


def never(body: Literal) -> Never:
    return Never(body)


def soft(rule, belief: float | None = None) -> Soft:
    return Soft(rule, belief)

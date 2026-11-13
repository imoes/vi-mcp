"""Classes of clingo-object: real Python classes whose methods are rules about memory objects.

    class Knowledge(VIObject):                  abstract: no kind of its own
        def stale(self):
            return (self.mode == "test") & (self.age > 90)

    class Insight(Knowledge):
        kind = "erkenntnis"                     the memory kind (objekt.art) the class stands for

    class Skill(Knowledge):
        kind = "skill"
        def stale(self):                        overrides Knowledge.stale for skills
            return (self.mode == "test") & (self.age > 30)

Each method becomes one flat rule of the notation — the server runs no Python, it receives the compiled rule. The membership filter
holds exactly the kinds whose objects resolve to that definition, so overriding needs no negation:
    stale(Self) <= (Self in objects("art:erkenntnis")) & (Self.mode == "test") & (Self.age > 90)
    stale(Self) <= (Self in objects("art:skill")) & (Self.mode == "test") & (Self.age > 30)
Dispatch is Python's method resolution order: an object of kind k answers with the method of the most specific class of kind k that
defines it. Parameters after self become variables: def blocks(self, H) → blocks(Self, H).
"""
from __future__ import annotations

import inspect

from .expr import RESERVED, Conj, ExprError, Literal, Obj, Rule, Atom, Var, _IDENT


class VIObject:
    """Base of all clingo-object classes. `kind` names the memory kind; without it a class is abstract."""

    kind: str | None = None


def _concrete(cls, universe: list[type] | None) -> list[type]:
    """The class and its subclasses that stand for a memory kind — only those of the program (universe), so a subclass defined
    elsewhere never joins silently."""
    out, todo = [], [cls]
    while todo:
        c = todo.pop()
        if c.__dict__.get("kind") and (universe is None or c in universe):
            out.append(c)
        todo += c.__subclasses__()
    return out


def _own_methods(cls) -> dict:
    return {n: f for n, f in cls.__dict__.items() if inspect.isfunction(f) and not n.startswith("_")}


def compile_class(cls, universe: list[type] | None = None) -> list[Rule]:
    """Every method the class itself defines, as flat rules over the kinds that resolve to it (Python's MRO decides overriding)."""
    if not (isinstance(cls, type) and issubclass(cls, VIObject)):
        raise ExprError(f"{cls!r} is no VIObject class")
    rules = []
    for name, fn in _own_methods(cls).items():
        if not _IDENT.match(name) or name in RESERVED:
            raise ExprError(f"{cls.__name__}.{name}: a method name is lower case and no word of the dialect")
        # the kinds whose objects use exactly this definition: concrete classes below cls whose MRO finds name in cls first
        kinds = sorted({c.kind for c in _concrete(cls, universe) if next(k for k in c.__mro__ if name in k.__dict__) is cls})
        if not kinds:
            continue  # every concrete subclass overrides it, or none exists: the definition never applies
        params = list(inspect.signature(fn).parameters)
        if not params or params[0] != "self":
            raise ExprError(f"{cls.__name__}.{name}: a method is def {name}(self, …)")
        self_ = Obj("Self")
        args = [Var(p[:1].upper() + p[1:]) for p in params[1:]]
        body = fn(self_, *args)
        if not isinstance(body, Literal):
            raise ExprError(f"{cls.__name__}.{name} returns {type(body).__name__} — a method returns a condition built from fields, & and ~")
        filt = kinds[0] if len(kinds) == 1 else None
        member = self_.where(f"art:{filt}" if filt else "(" + " OR ".join(f"art:{k}" for k in kinds) + ")")
        rules.append(Rule(Atom(name, (self_,) + tuple(args)), Conj([member]) & body))
    return rules

"""A clingo-object program: classes and statements, compiled to the notation, solved locally with the clingo Python API or sent to the
VI server — the same text either way, so both give the same answers.

    prog = Program(Knowledge, Insight, Skill)
    prog.add(rel.review(O) <= O.where("thema:oo") & O.stale())
    prog.notation()                  the program as text (what the server runs)
    prog.check(memory)               solved here: the objects of its filters come from memory.objects(filters)
    prog.ask(memory, ["review(\\"skill:x\\")"])
"""
from __future__ import annotations

from . import notation
from .expr import Atom, ExprError, Fact, Head, Rule, Statement
from .model import VIObject, compile_class


class Program:
    def __init__(self, *items):
        self.classes: list[type] = []
        self.statements: list[Statement] = []
        self.add(*items)

    def add(self, *items) -> "Program":
        for x in items:
            if isinstance(x, type) and issubclass(x, VIObject):
                if x not in self.classes:
                    self.classes.append(x)
            elif isinstance(x, Statement):
                self.statements.append(x)
            elif isinstance(x, Atom):
                self.statements.append(Fact(x))
            elif isinstance(x, Head):
                raise ExprError("a proposal needs a body: propose_tag(O, …) <= O.where(…) & …")
            elif isinstance(x, bool):
                raise ExprError("a Python bool was added — a comparison inside & needs parentheses")
            else:
                raise ExprError(f"{type(x).__name__} is no statement, fact or VIObject class")
        return self

    __iadd__ = add

    def rules(self) -> list[Statement]:
        out: list[Statement] = []
        for c in self.classes:
            out += compile_class(c, self.classes)
        return out + self.statements

    def notation(self) -> str:
        text = "\n".join(s.notation() for s in self.rules())
        notation.translate(text)  # every compiled program is valid notation — checked here, not first on the server
        return text

    def filters(self) -> list[str]:
        return notation.translate_full(self.notation())[2]

    def _facts(self, memory) -> tuple[str, dict | None]:
        fs = self.filters()
        if not fs:
            return "", None
        if memory is None:
            raise ExprError("the program reads memory objects — pass a memory (clingo_object.Memory or anything with objects(filters))")
        data = memory.objects(fs)
        c = data["counts"]
        facts = notation.facts(data)
        return "\n".join(facts), {"filter": data["filters"], "je_filter": [len(m) for m in data["members"]], "objekte": len(data["objects"]),
                                  "fakten": len(facts), "abgeschnitten": c["cut"], "nicht_sichtbar": c["not_visible"],
                                  "ausgeschlossen": c["excluded"], "ueber_kanten": c.get("via_edge", 0), "limit": data.get("limit")}

    def check(self, memory=None) -> dict:
        """Solved here with the clingo Python API — rule weights are the stated priors (measured weights live on the server)."""
        text = self.notation()
        facts, imported = self._facts(memory)
        program, stmts, _f = notation.translate_full(text)
        r = notation.run_program((facts + "\n" + program) if facts else program, stmts)
        r["importiert"] = imported
        return notation.check_result(r)

    def ask(self, memory, queries: list[str]) -> dict:
        text = self.notation()
        facts, _imported = self._facts(memory)
        return notation.ask(text, queries, facts_text=facts)

    def lines(self, memory=None) -> list[str]:
        return notation.lines(self.check(memory))


__all__ = ["Program", "Rule"]

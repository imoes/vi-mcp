"""clingo-object — clingo as an object-oriented language over the objects of a VI memory (vi-mcp).

The user (13.11.2026): "Wir machen gerade aus clingo eine objektorientierte Programmiersprache" — and: "clingo ist die Sprache für
LLMs". Real Python on the clingo Python API: classes, methods and inheritance (model), expressions by operator overloading (expr), a
Program that compiles to the notation (notation) the VI server runs and that solves the same text locally.

    from clingo_object import VIObject, Program, Obj, Var, rel, linked, never, soft, propose_tag, propose_link

Runs where code is trusted (an agent's machine, tests, an administrator); the server runs only the compiled notation, never Python.
Standard library plus clingo; it never imports vi_mcp.
"""
from .expr import ExprError, Obj, Var, linked, never, propose_link, propose_tag, rel, soft
from .model import VIObject, compile_class
from .notation import CLINGO_VERSION, LogicError
from .program import Program

__version__ = "0.63.0"
__all__ = ["CLINGO_VERSION", "ExprError", "LogicError", "Obj", "Program", "VIObject", "Var", "compile_class", "linked", "never",
           "propose_link", "propose_tag", "rel", "soft"]

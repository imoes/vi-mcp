"""Reasoning traces for kollektiv 1.3.0 — what a model writes between the facts it read and its verdict (0.70.1).

Measured on kollektiv 1.2.0 (docs/FINETUNING_PAPER.md §5.6–5.19): a small model reaches the verdict targets when it writes every step
of the seed's derivation as short, enumerated lines — the count of each evidence line with the reason it counts or not, the value with
the closed condition, every duty condition statement by statement — and fails where a step is left implicit or a line exists only
sometimes (run 30: a conditional line skipped in 34 % of short worlds). The user decided (18.11.2026) that the product targets
kollektiv 1.3.0 directly; this module writes its traces. Design rules, all from those measurements:

- One block per step of the seed, in the seed's order: Count (P1, P7), Origins (P8), Totals, Holds (P9, P10, P12), Value check (P3, P5,
  P11, P13), Duty check (P6, P7, P11, P13).
- Enumerate, never summarize: one line per evidence line, per origin, per statement and side, per duty condition.
- Lines that depend on a condition are written for every statement with "→ not met" when it does not hold (H7, run 31): the model never
  has to decide whether a line exists.
- No second semantics: every block names the atoms it claims, and `check` compares them with the solver's; a block that disagrees
  raises `TraceError` and no training row is written from that world.

Pure functions over the solver's derived atoms; `derive` returns them complete (the notation caps its output at MAX_SHOWN)."""
from __future__ import annotations

import re

from . import notation as n
from . import philosophy as ph

#: the statement-level input facts: their first argument is a statement (origin-level facts — derives_from, machine_made,
#: evidence_kind, camp — are about origins and give no statement of their own)
STATEMENT_FACTS = ("author", "line", "source", "closed", "peer_offers", "foreign", "unreviewed", "untestable", "testable_by",
                   "extraordinary", "withdrawn")
DUTY = re.compile(r"^(obligatory|forbidden|may)\(")
BLOCK_REASONS = {"hearsay_only": "hearsay only", "one_camp": "one camp only", "camp_unknown": "a camp unknown",
                 "extraordinary": "extraordinary, not strong"}


class TraceError(AssertionError):
    """A trace block names other atoms than the solver derives — the world gives no training row."""


def derive(pkg: dict, facts: str) -> set[str]:
    """Every atom the seed derives over `facts` (input facts included), complete — never cut at notation.MAX_SHOWN."""
    old = n.MAX_SHOWN
    n.MAX_SHOWN = 10 ** 9
    try:
        r = ph.solve(pkg, facts)
    finally:
        n.MAX_SHOWN = old
    if r.get("folgerungen_gesamt", len(r["folgerungen"])) != len(r["folgerungen"]):
        raise TraceError("derived atoms were cut")
    return {a.replace(" ", "") for a in r["folgerungen"]}


def _args(atom: str) -> tuple[str, ...]:
    """Top-level arguments of an atom: 'forbidden(confirm(x,s1))' → ('confirm(x,s1)',)."""
    inner, depth, out, cur = atom[atom.index("(") + 1:-1], 0, [], ""
    for c in inner:
        if c == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += c == "("
        depth -= c == ")"
        cur += c
    return tuple(out + [cur])


def atoms(derived: set[str], name: str) -> list[tuple[str, ...]]:
    return sorted(_args(a) for a in derived if a.startswith(name + "("))


def one(derived: set[str], name: str) -> set[str]:
    return {a[0] for a in atoms(derived, name)}


def statements(derived: set[str]) -> list[str]:
    """The statements of a world, in natural order (s2 before s10)."""
    ss = {a[0] for p in STATEMENT_FACTS for a in atoms(derived, p)}
    return sorted(ss, key=lambda s: (len(s), s))


def _gold(derived: set[str], *names: str) -> set[str]:
    return {a for a in derived if a.split("(", 1)[0] in names}


# ---- Count (P1, P7): every evidence line, counted or not, with the reason
def count_block(derived: set[str]) -> tuple[str, set[str]]:
    authors = {s: {i for ss, i in atoms(derived, "author") if ss == s} for s in one(derived, "author")}
    verified = set(atoms(derived, "verified"))
    lines, named = [], set()
    for s, p, o, i in sorted(atoms(derived, "line"), key=lambda a: (len(a[0]), a)):
        if i in authors.get(s, set()):
            lines.append(f"{s} {p} {o} by {i}: excluded, {i} is the author of {s}")
        else:
            lines.append(f"{s} {p} {o} by {i}: counted")
            named.add(f"counts({s},{p},{o})")
    for s, p, r, k in sorted(atoms(derived, "source"), key=lambda a: (len(a[0]), a)):
        if (r, s) in verified:
            lines.append(f"{s} {p} {r} via {k}: counted, verified")
            named.add(f"counts({s},{p},{r})")
        else:
            lines.append(f"{s} {p} {r} via {k}: not counted, not verified")
    return "Count:\n" + ("\n".join(lines) if lines else "no evidence lines"), named


# ---- Origins (P8): every counted origin — an origin of its own, a copy (with its roots) or machine-made
def origins_block(derived: set[str]) -> tuple[str, set[str]]:
    counted = sorted({o for _s, _p, o in atoms(derived, "counts")})
    copies = {o: sorted(r for oo, r in atoms(derived, "derives_from") if oo == o) for o in counted}
    machine = one(derived, "machine_made")
    roots = {o: sorted(r for oo, r in atoms(derived, "root") if oo == o) for o in counted}
    lines, named = [], set()
    for o in counted:
        named |= {f"root({o},{r})" for r in roots[o]}
        if copies[o]:
            ups = sorted(r for oo, r in atoms(derived, "upstream") if oo == o)
            tail = f"root {', '.join(roots[o])}" if roots[o] else "no root (every origin it comes from is a copy or machine-made)"
            lines.append(f"{o}: copy of {', '.join(copies[o])}" + (f", upstream {', '.join(ups)}" if ups != copies[o] else "") + f" → {tail}")
        elif o in machine:
            lines.append(f"{o}: machine-made → no root")
        else:
            lines.append(f"{o}: an origin of its own → root {o}")
    return "Origins:\n" + ("\n".join(lines) if lines else "no counted origins"), named


# ---- Totals: the distinct roots per statement and side
def totals_block(derived: set[str], ss: list[str]) -> tuple[str, set[str]]:
    g = atoms(derived, "grounded")
    lines, named = [], set()
    for s in ss:
        side = {p: sorted({r for gs, gp, r in g if gs == s and gp == p}) for p in ("pos", "neg")}
        named |= {f"grounded({s},{p},{r})" for p in side for r in side[p]}
        lines.append(f"{s}: support {len(side['pos'])}" + (f" ({', '.join(side['pos'])})" if side["pos"] else "")
                     + f", opposition {len(side['neg'])}" + (f" ({', '.join(side['neg'])})" if side["neg"] else ""))
    return "Totals:\n" + "\n".join(lines), named


# ---- Holds (P9, P10, P12): for every statement and side with a root — one root, or two and whether something holds them back
def holds_block(derived: set[str], ss: list[str]) -> tuple[str, set[str]]:
    g = atoms(derived, "grounded")
    weak = {r for r, k in atoms(derived, "evidence_kind") if k == "hearsay"}
    camps = {}
    for r, c in atoms(derived, "camp"):
        camps.setdefault(r, set()).add(c)
    two, firm, measured = set(atoms(derived, "two")), set(atoms(derived, "firm")), set(atoms(derived, "measured"))
    strong, extraordinary = one(derived, "strong"), one(derived, "extraordinary")
    bridged = set(atoms(derived, "bridged"))
    blocked = {}
    for s, p, w in atoms(derived, "blocked"):
        blocked.setdefault((s, p), set()).add(w)
    lines, named = [], set()
    for s in ss:
        for p in ("pos", "neg"):
            roots = sorted({r for gs, gp, r in g if gs == s and gp == p})
            if not roots:
                continue
            if (s, p) not in two:
                named.add(f"single({s},{p})")
                lines.append(f"{s} {p}: one root ({roots[0]}) → single")
                continue
            parts = [f"hearsay only {'no' if (s, p) in firm else 'yes'}"]
            known = [r for r in roots if r in camps]
            if not known:
                parts.append("camps none")
            else:
                cs = sorted(set().union(*(camps[r] for r in known)))
                parts.append(f"camps {', '.join(cs)}" + (", bridged" if (s, p) in bridged else ", not bridged")
                             + (", a root without camp" if len(known) < len(roots) else ""))
            if p == "pos" and s in extraordinary:
                parts.append(f"extraordinary, strong {'yes' if s in strong else 'no'}"
                             + (" (measured)" if (s, "pos") in measured else ""))
            why = sorted(blocked.get((s, p), ()))
            named |= {f"blocked({s},{p},{w})" for w in why}
            if why:
                lines.append(f"{s} {p}: two or more roots, {'; '.join(parts)} → held: {', '.join(BLOCK_REASONS[w] for w in why)}")
            else:
                named.add(f"clear({s},{p})")
                lines.append(f"{s} {p}: two or more roots, {'; '.join(parts)} → clear")
    return "Holds:\n" + ("\n".join(lines) if lines else "no grounded evidence"), named


# ---- Value check (P3, P5, P11, P13): support, opposition, closed → value; then the acceptance with its reason
ACC_WHY = {("t", "accepted"): "support clear → accepted", ("t", "tentative"): "support single or held → tentative",
           ("f", "rejected"): "opposition clear → rejected", ("f", "tentative"): "opposition single or held → tentative",
           ("b", "unresolved"): "both sides → unresolved", ("n", "unresolved"): "nothing on either side → unresolved",
           ("n", "withdrawn"): "withdrawn by its author, nothing else → withdrawn"}


def value_block(derived: set[str], ss: list[str]) -> tuple[str, set[str]]:
    pos, neg, closed = one(derived, "pos"), one(derived, "neg"), one(derived, "closed")
    untestable = one(derived, "untestable")
    vals, accs = {}, {}
    for s, v in atoms(derived, "value"):
        vals.setdefault(s, set()).add(v)
    for s, a in atoms(derived, "acceptance"):
        accs.setdefault(s, set()).add(a)
    lines, named = [], set()
    for s in ss:
        head = f"{s}: support {'yes' if s in pos else 'no'}, opposition {'yes' if s in neg else 'no'}, closed {'yes' if s in closed else 'no'}"
        v = "b" if s in pos and s in neg else ("t" if s in pos else "f" if s in neg else "n") if s in closed else None
        if v is None:
            lines.append(f"{head} → no value " + ("(lines on one side need a closed view)" if s in pos or s in neg else "(no lines, view not closed)"))
            continue
        named.add(f"value({s},{v})")
        parts = []
        for a in sorted(accs.get(s, ())):
            named.add(f"acceptance({s},{a})")
            parts.append("untestable, nothing could refute it → untestable" if a == "untestable" else ACC_WHY.get((v, a), a))
        if s in untestable and not parts:
            parts.append("untestable")
        lines.append(f"{head} → {v}" + (f"; {', '.join(parts)}" if parts else ""))
    return "Value check:\n" + ("\n".join(lines) if lines else "no statements"), named


# ---- Duty check (P6, P7, P11, P13): statement by statement, conditions in a fixed order; ask and adopt always written (H7)
ACC_DUTY = {"accepted": ("may assert {s}", ["may(assert_unqualified({s}))"]),
            "tentative": ("may state {s} only as a hypothesis, must not assert it",
                          ["may(state_as_hypothesis({s}))", "forbidden(assert_unqualified({s}))"]),
            "rejected": ("must not assert {s}", ["forbidden(assert_unqualified({s}))"]),
            "unresolved": ("must not assert {s}", ["forbidden(assert_unqualified({s}))"]),
            "withdrawn": ("must not assert {s}", ["forbidden(assert_unqualified({s}))"]),
            "untestable": ("may state {s} only as untestable, must not assert it",
                           ["may(state_as_untestable({s}))", "forbidden(assert_unqualified({s}))"])}


def duty_block(derived: set[str], ss: list[str]) -> tuple[str, set[str]]:
    verified = set(atoms(derived, "verified"))
    vals, accs = {}, {}
    for s, v in atoms(derived, "value"):
        vals.setdefault(s, set()).add(v)
    for s, a in atoms(derived, "acceptance"):
        accs.setdefault(s, set()).add(a)
    peer, foreign, unrev = one(derived, "peer_offers"), one(derived, "foreign"), one(derived, "unreviewed")
    refutable = one(derived, "refutable")
    lines, named = [], set()
    for s in ss:
        for _s, i in [a for a in atoms(derived, "author") if a[0] == s]:
            lines.append(f"{s}: author {i} → {i} must not confirm {s}")
            named.add(f"forbidden(confirm({i},{s}))")
        for _s, _p, r, _k in [a for a in atoms(derived, "source") if a[0] == s]:
            if (r, s) in verified:
                lines.append(f"{s}: source {r} verified → no duty")
            else:
                lines.append(f"{s}: source {r} not verified → verify {s} against {r}, must not cite {r} for {s}")
                named |= {f"obligatory(verify({r},{s}))", f"forbidden(cite({r},{s}))"}
        for a in sorted(accs.get(s, ())):
            text, duties = ACC_DUTY[a]
            lines.append(f"{s}: acceptance {a} → " + text.format(s=s))
            named |= {d.format(s=s) for d in duties}
            if a == "accepted":  # P11: an accepted statement needs a named refuting observation — written for every accepted one
                if s in refutable:
                    lines.append(f"{s}: accepted, refuting observation named yes → no duty")
                else:
                    lines.append(f"{s}: accepted, refuting observation named no → name an observation that would refute {s}")
                    named.add(f"obligatory(name_refuter({s}))")
        vs = vals.get(s, set())
        if "b" in vs:
            lines.append(f"{s}: value b → report the conflict about {s}")
            named.add(f"obligatory(report({s}))")
        v_txt = "n" if "n" in vs else (", ".join(sorted(vs)) or "none")
        if "n" in vs and s in peer:
            lines.append(f"{s}: value n, peer offers yes → ask the collective about {s}")
            named.add(f"obligatory(ask({s}))")
        else:
            lines.append(f"{s}: value {v_txt}, peer offers {'yes' if s in peer else 'no'} → not met, no ask")
        if s in foreign and s in unrev:
            lines.append(f"{s}: foreign yes, unreviewed yes → must not adopt {s}")
            named.add(f"forbidden(adopt({s}))")
        else:
            lines.append(f"{s}: foreign {'yes' if s in foreign else 'no'}, unreviewed {'yes' if s in unrev else 'no'} → not met, no adopt rule")
    return "Duty check:\n" + ("\n".join(lines) if lines else "no duty conditions"), named


#: block → the solver predicates whose atoms it must name exactly
CHECKS = {"count": ("counts",), "origins": ("root",), "totals": ("grounded",), "holds": ("blocked", "clear", "single"),
          "value": ("value", "acceptance"), "duty": None}


def check(name: str, named: set[str], derived: set[str]) -> None:
    gold = {a for a in derived if DUTY.match(a)} if CHECKS[name] is None else _gold(derived, *CHECKS[name])
    if named != gold:
        raise TraceError(f"{name}: trace and seed differ: {sorted(named ^ gold)}")


def trace(pkg: dict, facts: str) -> str:
    """The whole trace for a world in notation: Count, Origins, Totals, Holds, Value check, Duty check — every block checked."""
    derived = derive(pkg, facts)
    ss = statements(derived)
    blocks = [("count", count_block(derived)), ("origins", origins_block(derived)), ("totals", totals_block(derived, ss)),
              ("holds", holds_block(derived, ss)), ("value", value_block(derived, ss)), ("duty", duty_block(derived, ss))]
    for name, (_text, named) in blocks:
        check(name, named, derived)
    return "\n\n".join(text for _n, (text, _named) in blocks)

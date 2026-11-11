"""0.41.0: the view of a network wiki page — pure functions, no database.

A page is a set of revisions; each names its parents (eltern) by revision id (the SHA-256 of its content). The set only grows, so
whoever holds the same revisions computes the same view: no master, no locks, no consensus (a grow-only set over a DAG).

  heads     accepted revisions without an accepted descendant
  one head  that is the page
  several   folded pairwise in revision-id order with a three-way merge on paragraphs (blank-line separated); the base is the deepest
            common ancestor (ties: the smallest id). Changes in different places merge silently — a computed view, not a new
            revision, the same on every server. Overlapping different changes become a named conflict with both versions and
            their authors; nothing disappears silently. A revision with all heads as parents resolves it.
  deleted   a revision with geloescht = true; a later one restores the page. If only some heads deleted it, the page stays and
            the deletion is named.
  forgotten a revision whose text was revoked keeps its place in the graph (ancestry) but is never a head; as a base it counts as empty.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

CONFLICT_OPEN, CONFLICT_MID, CONFLICT_CLOSE = "<<<<<<<", "=======", ">>>>>>>"


@dataclass
class Rev:
    rev: str
    parents: list[str]
    text: str | None  # None: forgotten (content revoked)
    title: str = ""
    deleted: bool = False
    author: str = ""
    hashtags: list[str] = field(default_factory=list)


@dataclass
class Conflict:
    a_rev: str
    b_rev: str
    a: list[str]
    b: list[str]
    a_author: str = ""
    b_author: str = ""


@dataclass
class View:
    text: str
    title: str
    heads: list[str]
    conflicts: list[Conflict]
    deleted: bool
    deleted_by: list[str]
    merged_silently: bool

    @property
    def state(self) -> str:
        """Exhaustive: empty · deleted · conflict · merged · current."""
        if not self.heads:
            return "empty"
        if self.deleted:
            return "deleted"
        if self.conflicts:
            return "conflict"
        return "merged" if len(self.heads) > 1 else "current"


def paragraphs(text: str | None) -> list[str]:
    blocks, cur = [], []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if line.strip():
            cur.append(line.rstrip())
        elif cur:
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def ancestors(revs: dict[str, Rev], r: str) -> set[str]:
    out, todo = set(), list(revs[r].parents) if r in revs else []
    while todo:
        x = todo.pop()
        if x in out:
            continue
        out.add(x)
        if x in revs:
            todo.extend(revs[x].parents)
    return out


def depth(revs: dict[str, Rev], r: str, memo: dict | None = None) -> int:
    memo = {} if memo is None else memo
    if r in memo:
        return memo[r]
    stack, order = [r], []
    while stack:  # iterative: long histories must not hit the recursion limit
        x = stack.pop()
        if x in memo or x in order:
            continue
        order.append(x)
        stack.extend(p for p in (revs[x].parents if x in revs else []) if p not in memo)
    for x in reversed(order):
        ps = [p for p in (revs[x].parents if x in revs else []) if p in revs]
        memo[x] = 1 + max((memo.get(p, 0) for p in ps), default=0)
    return memo[r]


def heads(revs: dict[str, Rev], accepted: set[str]) -> list[str]:
    cand = {r for r in accepted if r in revs and revs[r].text is not None}
    covered = set()
    for r in cand:
        covered |= ancestors(revs, r)
    return sorted(cand - covered)


def lca(revs: dict[str, Rev], a: str, b: str) -> str | None:
    common = (ancestors(revs, a) | {a}) & (ancestors(revs, b) | {b})
    common = {c for c in common if c in revs}
    if not common:
        return None
    memo: dict = {}
    return sorted(common, key=lambda c: (-depth(revs, c, memo), c))[0]


def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes() if tag != "equal"]


def _apply(base: list[str], lo: int, hi: int, hunks: list[tuple[int, int, list[str]]]) -> list[str]:
    out, pos = [], lo
    for i1, i2, rep in sorted(hunks, key=lambda h: (h[0], h[1])):
        out += base[pos:i1] + rep
        pos = i2
    return out + base[pos:hi]


def merge3(base: list[str], a: list[str], b: list[str]) -> list:
    """Paragraph lists → merged list; an element is a str or a pair (a_part, b_part) for a conflict. Pure and deterministic."""
    tagged = sorted([(i1, i2, rep, "a") for i1, i2, rep in _hunks(base, a)] + [(i1, i2, rep, "b") for i1, i2, rep in _hunks(base, b)],
                    key=lambda h: (h[0], h[1], h[3]))
    clusters: list[list] = []
    for h in tagged:
        if clusters:
            last = clusters[-1]
            hi = max(x[1] for x in last)
            # overlapping ranges belong together, and an insertion at the edge of the other's change (its place is ambiguous);
            # changes of neighbouring paragraphs do not
            if h[0] < hi or (h[0] == hi and (h[0] == h[1] or any(x[0] == x[1] == hi for x in last))):
                last.append(h)
                continue
        clusters.append([h])
    out, pos = [], 0
    for c in clusters:
        lo, hi = min(x[0] for x in c), max(x[1] for x in c)
        out += base[pos:lo]
        sides = {x[3] for x in c}
        va = _apply(base, lo, hi, [(x[0], x[1], x[2]) for x in c if x[3] == "a"])
        vb = _apply(base, lo, hi, [(x[0], x[1], x[2]) for x in c if x[3] == "b"])
        if sides == {"a"}:
            out += va
        elif sides == {"b"}:
            out += vb
        elif va == vb:
            out += va
        else:
            out.append((va, vb))
        pos = hi
    return out + base[pos:]


def view(revs: dict[str, Rev], accepted: set[str]) -> View:
    hs = heads(revs, accepted)
    if not hs:
        return View("", "", [], [], False, [], False)
    live = [h for h in hs if not revs[h].deleted]
    deleted_by = [h for h in hs if revs[h].deleted]
    if not live:
        return View("", revs[hs[0]].title, hs, [], True, deleted_by, False)
    cur, merged_from, conflicts = paragraphs(revs[live[0]].text), [live[0]], []
    for h in live[1:]:
        bases = [x for x in (lca(revs, m, h) for m in merged_from) if x]
        memo: dict = {}
        base = sorted(set(bases), key=lambda c: (-depth(revs, c, memo), c))[0] if bases else None
        base_par = paragraphs(revs[base].text) if base and revs[base].text is not None else []
        parts = []
        for p in merge3(base_par, cur, paragraphs(revs[h].text)):
            if isinstance(p, tuple):
                c = Conflict(merged_from[-1] if len(merged_from) == 1 else "+".join(x[:8] for x in merged_from), h, p[0], p[1],
                             revs[merged_from[-1]].author if len(merged_from) == 1 else "several", revs[h].author)
                conflicts.append(c)
                # markers name revisions only: an author's label differs per server (instance here, pseudonym elsewhere), the view must not
                parts.append("\n".join([f"{CONFLICT_OPEN} {c.a_rev[:12]}", *p[0], CONFLICT_MID, *p[1], f"{CONFLICT_CLOSE} {h[:12]}"]))
            else:
                parts.append(p)
        cur = parts
        merged_from.append(h)
    title = sorted({revs[h].title for h in live if revs[h].title})[0] if any(revs[h].title for h in live) else ""
    return View("\n\n".join(cur), title, hs, conflicts, False, deleted_by, len(live) > 1 and not conflicts)

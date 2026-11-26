"""Philosophy packages: equip an AI with a philosophy written as a clingo-object rule set (0.66.0).

The user (15.11.2026): "Die Philosophie-Technik muss als Skill vorhanden sein, damit man eine KI mit irgendeiner Philosophie ausstatten
kann." A philosophy is a PACKAGE, never code wired into vi-mcp:

  name, version, author      identity; the package hash covers everything below
  profile                    the semantics the seed relies on (e.g. fde-signed-v1: support and opposition as separate predicates,
                             default negation only over a closed snapshot) — two packages with different profiles are not mixed
  vocabulary                 every predicate with arity and kind: input · derived · closure · answer · duty
  answers                    answer predicates, the argument position of the value and the allowed values
  seed                       the rule set in clingo-object notation (the server-safe subset; never Python that is executed)
  worlds                     test worlds: facts, atoms that must hold and must not hold; `counterfactual_of` names a world whose
                             answers MUST differ (Codex's review: a seed that calls everything "unknown" conforms to itself perfectly)

Only the seed is stored (philosophy-v2, the user, 15.11.2026: "Wir hatten gesagt, dass wir nur clingo speichern und diese dann in Prosa
übersetzt werden"). Prose is a translation of the seed (clingo_object/philosophy_explain.py), checked by the round trip prose → seed →
same verdicts; it is never a source and never covered by the package hash. The seed's rules stand in blocks marked by an id comment
(`# P1`) and nothing else: no title, because any word next to the rules is meaning outside them — it can drift from the rules, and a
translator would copy it instead of reading the rules, so the round trip would measure the title, not the understanding.

`check` refuses a package unless: the seed translates; every predicate is declared with its arity; default negation appears only in
rules deriving a closure predicate or a never-violation (it must not turn missing evidence into opposition); every rule lies in a
marked block and the seed holds no other comment; every world solves to exactly one complete answer set with the expected atoms and no unexpected violation;
every allowed answer value is produced by some world; every counterfactual world changes an answer. With a priority profile
(profile.priority, e.g. maximal-candidates-v1) its fixed rules run with the seed: the seed must not derive what the profile owns, nor
derive the profile's inputs (candidates, ranks) from its outputs.

A package is a directory (philosophy.json, seed.co, worlds.jsonl) or a built-in module (BUILTIN). Standard library plus clingo only:
it runs where the agent runs, without a VI server.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from pathlib import Path

from . import notation as n

FORMAT = "philosophy-v2"
#: a block marker: the only comment a seed may hold
MARKER = re.compile(r"^#\s*([A-Z]+[0-9]+)\s*$")
#: package keys that are never covered by the hash: the hash itself and derived artifacts (a translation is never a source)
UNHASHED = ("hash", "translation")
PROFILES = {"fde-signed-v1": "support pos(S) and opposition neg(S) are ordinary predicates; values t/f/b/n; default negation only over "
                             "a closed snapshot (closure predicates); strong negation '-' is not used for values"}
#: interface: a predicate a priority profile reads — given by the world, or derived by the seed from its own evidence, never from the
#: profile's outputs (Codex: "candidate applicability must depend only on immutable evidence, not effective verdicts")
KINDS = ("input", "derived", "closure", "answer", "duty", "interface")
#: predicates of the notation's prelude (deontic) and internal atoms: usable without declaring them as derived rules of the seed
BUILTIN_PREDICATES = {"obligatory", "forbidden", "permitted", "conflict", "violation", "done"}
BUILTIN = {"kollektiv": "clingo_object.philosophy_kollektiv", "messung": "clingo_object.philosophy_messung",
           "code": "clingo_object.philosophy_code"}

# ── Defeasible priorities (lex superior / lex posterior) as a reusable profile ─────────────────────────────────────────────────────
# Codex's review (frage:e05f78b192e7fdb964119b82, question 3): "maximal applicable candidates in each conflict group" — a deliberately
# restricted policy, not Brewka/Eiter preferred answer sets. `higher` comes from ONE strict lexicographic rank tuple (authority, then
# evidence quality, then observation time — and the time only where the group permits supersession), so "superior OR newer" as two
# independent rules cannot produce higher(a,b) and higher(b,a). Explicit preferences (prefer) are allowed, but the transitive closure is
# checked: a cycle makes the group INVALID — reported as a violation, no effective candidate, never the value n. Raw conflicts and
# suppression reasons are kept. Arrival time is not an input: only the observation time (observed) can order candidates.
MAXIMAL_CANDIDATES_V1 = """\
# MC1
higher(R, T, G) <= candidate(R, G, P) & candidate(T, G, Q) & rank(R, A, X) & rank(T, B, Y) & (A > B)
higher(R, T, G) <= candidate(R, G, P) & candidate(T, G, Q) & rank(R, A, X) & rank(T, A, Y) & (X > Y)
higher(R, T, G) <= candidate(R, G, P) & candidate(T, G, Q) & rank(R, A, X) & rank(T, A, X) & supersedes(G) & observed(R, U) & observed(T, V) & (U > V)
higher(R, T, G) <= prefer(R, T, G) & candidate(R, G, P) & candidate(T, G, Q)
# MC2
reach(R, T, G) <= higher(R, T, G)
reach(R, T, G) <= reach(R, U, G) & higher(U, T, G)
ranked(R) <= rank(R, A, X)
unranked(R) <= candidate(R, G, P) & ~ranked(R)
two_ranks(R) <= rank(R, A, X) & rank(R, B, Y) & (A != B)
two_ranks(R) <= rank(R, A, X) & rank(R, A, Y) & (X != Y)
bad(G, cycle) <= reach(R, R, G)
bad(G, unranked) <= candidate(R, G, P) & unranked(R)
bad(G, two_ranks) <= candidate(R, G, P) & two_ranks(R)
invalid(G) <= bad(G, W)
never(invalid(G))
# MC3
dominated(R, G) <= candidate(R, G, P) & candidate(T, G, Q) & reach(T, R, G)
suppressed(R, T, G) <= candidate(R, G, P) & candidate(T, G, Q) & reach(T, R, G) & (R != T)
effective(R, G, P) <= candidate(R, G, P) & complete(G) & ~dominated(R, G) & ~invalid(G)
raw_conflict(G) <= candidate(R, G, P) & candidate(T, G, Q) & (P != Q)
"""

PRIORITY_PROFILES: dict[str, dict | None] = {
    "none": None,
    "maximal-candidates-v1": {
        "rules": MAXIMAL_CANDIDATES_V1,
        "vocabulary": {
            "candidate": {"arity": 3, "kind": "interface", "doc": "candidate(R, G, P): R is an admissible candidate with polarity or norm tag P in conflict group G"},
            "rank": {"arity": 3, "kind": "interface", "doc": "rank(R, A, Q): trusted policy gives R authority A and evidence quality Q (integers)"},
            "observed": {"arity": 2, "kind": "interface", "doc": "observed(R, T): R was observed at time T (an integer) — not when it arrived"},
            "supersedes": {"arity": 1, "kind": "interface", "doc": "supersedes(G): in group G a later observation replaces an earlier one"},
            "prefer": {"arity": 3, "kind": "interface", "doc": "prefer(R, T, G): an explicit preference of R over T in group G"},
            "complete": {"arity": 1, "kind": "interface", "doc": "complete(G): the candidate set of G is complete"},
            "higher": {"arity": 3, "kind": "derived"}, "reach": {"arity": 3, "kind": "derived"}, "ranked": {"arity": 1, "kind": "derived"},
            "unranked": {"arity": 1, "kind": "closure"}, "two_ranks": {"arity": 1, "kind": "derived"}, "bad": {"arity": 2, "kind": "derived"},
            "invalid": {"arity": 1, "kind": "derived"}, "dominated": {"arity": 2, "kind": "derived"},
            "suppressed": {"arity": 3, "kind": "derived"}, "effective": {"arity": 3, "kind": "closure"},
            "raw_conflict": {"arity": 1, "kind": "derived"}},
    },
}


def priority_profile(pkg: dict) -> dict | None:
    name = (pkg.get("profile") or {}).get("priority", "none")
    if name not in PRIORITY_PROFILES:
        raise PackageError(f"profile.priority {name!r} unknown — known: {', '.join(PRIORITY_PROFILES)}")
    return PRIORITY_PROFILES[name]


def program(pkg: dict) -> str:
    """The rules that run: the seed plus the rules of its priority profile (engine rules, fixed per profile name)."""
    prof = priority_profile(pkg)
    return pkg["seed"] + ("\n" + prof["rules"] if prof else "")


def vocabulary(pkg: dict) -> dict:
    """The package's vocabulary plus its priority profile's."""
    prof = priority_profile(pkg)
    return {**pkg["vocabulary"], **(prof["vocabulary"] if prof else {})}


def blocks(seed: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """([(block id, its rule lines)], problems) of a seed: every rule after a marker `# P1`; any other comment or a rule before the
    first marker is a problem (named, never skipped). Pure."""
    out: list[tuple[str, list[str]]] = []
    problems: list[str] = []
    for nr, line in enumerate(seed.splitlines(), 1):
        t = line.strip()
        if not t:
            continue
        if t.startswith(("#", "%")):
            m = MARKER.match(t)
            if not m:
                problems.append(f"line {nr}: a comment that is not a block marker ({t[:40]!r}) — the seed stores only rules and markers "
                                "like '# P1'; prose is a translation (vi-mcp philosophy explain)")
            elif any(b == m.group(1) for b, _r in out):
                problems.append(f"line {nr}: block {m.group(1)} is marked twice")
            else:
                out.append((m.group(1), []))
            continue
        if "#" in t and not re.search(r"[\"'].*#.*[\"']", t):
            problems.append(f"line {nr}: a comment after a rule — the seed stores only rules and markers")
        if not out:
            problems.append(f"line {nr}: a rule before the first block marker — every rule lies in a marked block (# P1)")
            continue
        out[-1][1].append(t)
    problems += [f"block {b} holds no rule" for b, r in out if not r]
    return out, problems


class PackageError(ValueError):
    pass


def load(ref: str) -> dict:
    """A package by built-in name or directory."""
    if ref in BUILTIN:
        return json.loads(json.dumps(importlib.import_module(BUILTIN[ref]).PACKAGE))  # a copy: callers may not change the module
    d = Path(ref)
    if not (d / "philosophy.json").exists():
        raise PackageError(f"{ref}: neither a built-in philosophy ({', '.join(sorted(BUILTIN))}) nor a directory with philosophy.json")
    pkg = json.loads((d / "philosophy.json").read_text(encoding="utf-8"))
    pkg["seed"] = (d / "seed.co").read_text(encoding="utf-8")
    pkg["worlds"] = [json.loads(x) for x in (d / "worlds.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return pkg


#: 0.69.6: the largest package accepted from its parts (manifest + seed + worlds as JSON characters)
MAX_PACKAGE_CHARS = 400_000


def from_parts(manifest, seed, worlds) -> dict:
    """A package from its three parts — what philosophy.json, seed.co and worlds.jsonl hold — as text or data, without a directory
    (0.69.6: a philosophy can be handed over MCP). The same package `load` reads from a directory; `check` decides whether it is valid."""
    try:
        m = json.loads(manifest) if isinstance(manifest, str) else dict(manifest or {})
    except (ValueError, TypeError) as e:
        raise PackageError(f"manifest: the content of philosophy.json, a JSON object ({e})") from e
    if not isinstance(m, dict) or not m.get("name"):
        raise PackageError("manifest: the content of philosophy.json — an object with at least name, version, format")
    if not isinstance(seed, str) or not seed.strip():
        raise PackageError("seed: the content of seed.co (the rule set, blocks marked # P1 …)")
    if isinstance(worlds, str):
        try:
            worlds = [json.loads(x) for x in worlds.splitlines() if x.strip()]
        except ValueError as e:
            raise PackageError(f"worlds: the lines of worlds.jsonl, one JSON object per line ({e})") from e
    if not isinstance(worlds, list) or not all(isinstance(w, dict) for w in worlds):
        raise PackageError("worlds: the test worlds — a list of objects, or the text of worlds.jsonl")
    pkg = {**{k: v for k, v in m.items() if k not in ("seed", "worlds")}, "seed": seed, "worlds": worlds}
    if len(json.dumps(pkg, ensure_ascii=False)) > MAX_PACKAGE_CHARS:
        raise PackageError(f"package larger than {MAX_PACKAGE_CHARS} characters")
    return pkg


def to_parts(pkg: dict) -> dict:
    """The three parts of a package, as from_parts takes them (export)."""
    return {"manifest": {k: v for k, v in pkg.items() if k not in ("seed", "worlds") + UNHASHED},
            "seed": pkg["seed"], "worlds": list(pkg.get("worlds") or [])}


def package_hash(pkg: dict) -> str:
    """sha256 over the package (never over a derived translation); with a priority profile also over the profile's rules — they run
    with the seed. A philosophy-v1 package that still carries prose principles keeps them in its hash, so an installed v1 object still
    matches the hash it was bound to."""
    body = {k: v for k, v in pkg.items() if k not in UNHASHED}
    prof = PRIORITY_PROFILES.get((pkg.get("profile") or {}).get("priority", "none"))
    if prof:
        body["_priority_rules_sha256"] = hashlib.sha256(prof["rules"].encode()).hexdigest()
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(pkg: dict, directory: str) -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    (d / "seed.co").write_text(pkg["seed"], encoding="utf-8")
    (d / "worlds.jsonl").write_text("".join(json.dumps(w, ensure_ascii=False) + "\n" for w in pkg["worlds"]), encoding="utf-8")
    meta = {k: v for k, v in pkg.items() if k not in ("seed", "worlds")}
    (d / "philosophy.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return d


def _norm(atom: str) -> str:
    return "".join(atom.split())


def _signatures(program: str) -> tuple[dict[str, set[int]], list[tuple[str, bool, set[str]]]]:
    """(predicate -> arities used, [(head predicate, rule uses default negation, body predicates)]) from clingo's AST of the
    translated program."""
    from clingo import ast
    used: dict[str, set[int]] = {}
    rules: list[tuple[str, bool, set[str]]] = []

    def atom_sig(sym):
        if sym.ast_type == ast.ASTType.UnaryOperation:
            sym = sym.argument
        if sym.ast_type == ast.ASTType.Function:
            return sym.name, len(sym.arguments)
        if sym.ast_type == ast.ASTType.SymbolicTerm:
            return str(sym.symbol), 0
        return None

    def visit(stm):
        if stm.ast_type != ast.ASTType.Rule:
            return
        head = stm.head
        hname = None
        if head.ast_type == ast.ASTType.Literal and head.atom.ast_type == ast.ASTType.SymbolicAtom:
            sig = atom_sig(head.atom.symbol)
            if sig:
                hname = sig[0]
                used.setdefault(sig[0], set()).add(sig[1])
        negated = False
        body: set[str] = set()
        for lit in stm.body:
            if lit.ast_type == ast.ASTType.Literal and lit.atom.ast_type == ast.ASTType.SymbolicAtom:
                sig = atom_sig(lit.atom.symbol)
                if sig:
                    used.setdefault(sig[0], set()).add(sig[1])
                    body.add(sig[0])
                if lit.sign == ast.Sign.Negation:
                    negated = True
        if hname and not hname.startswith("vi__fired"):
            rules.append((hname, negated, body))
    ast.parse_string(program, visit)
    return used, rules


#: the translated seed (plus profile) per program text: the program is constant, only the facts change — translating it was 72 % of
#: the time of a verdict (cProfile 15.11.2026: translate_full 5.6 of 7.8 s for 360 verdicts of messung)
_TRANSLATED: dict[str, tuple[str, list]] = {}


def solve(pkg: dict, facts: str) -> dict:
    """ONE solve of the seed (with its profile's rules) over facts in notation: the same result as n.check(program + facts), with the
    constant program translated once per process. Every verdict of this module goes through here."""
    prog = program(pkg)
    hit = _TRANSLATED.get(prog)
    if hit is None:
        asp, stmts, _filters = n.translate_full(prog)
        if len(_TRANSLATED) >= 32:
            _TRANSLATED.clear()
        hit = _TRANSLATED[prog] = (asp, stmts)
    facts_asp = n.translate_full(facts)[0] if facts.strip() else ""
    return n.check_result(n.run_program((hit[0] + "\n" + facts_asp) if facts_asp else hit[0], hit[1]))


def _solve_world(pkg: dict, world: dict) -> dict:
    return solve(pkg, world.get("facts", ""))


def _depends_on(rules: list[tuple[str, bool, set[str]]], targets: set[str]) -> set[str]:
    """Every head that depends, through any chain of rules, on one of the target predicates."""
    out: set[str] = set()
    changed = True
    while changed:
        changed = False
        for head, _neg, body in rules:
            if head not in out and body & (targets | out):
                out.add(head)
                changed = True
    return out


def check(pkg: dict) -> dict:
    """Every rule of the format (module docstring). Returns {ok, errors, warnings, worlds, coverage, hash}."""
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("name", "version", "author", "profile", "vocabulary", "answers", "seed", "worlds"):
        if key not in pkg:
            errors.append(f"missing field {key}")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "worlds": [], "coverage": {}, "hash": None}
    sits = pkg.get("situations")  # 0.69.6: optional — the situations the author meant the philosophy for, as kind:value hashtags
    if sits is not None and (not isinstance(sits, list) or not all(isinstance(t, str) and re.fullmatch(r"[a-z][a-z0-9_-]*:[^\s:]\S{0,80}", t) for t in sits)):
        errors.append("situations: a list of kind:value hashtags, e.g. [\"topic:incident\", \"task:judge-claims\"]")
    if pkg.get("format", FORMAT) != FORMAT:
        errors.append(f"format {pkg.get('format')} — this engine reads {FORMAT}"
                      + (" (v1 stored prose principles; v2 stores only the seed: remove principles, keep the markers '# P1' in the seed, "
                         "and get prose with vi-mcp philosophy explain)" if pkg.get("format") == "philosophy-v1" else ""))
    if "principles" in pkg:
        errors.append("the package stores prose principles — only the seed is stored; prose is a translation (vi-mcp philosophy explain)")
    sem = (pkg["profile"] or {}).get("semantics")
    if sem not in PROFILES:
        errors.append(f"profile.semantics {sem!r} unknown — known: {', '.join(PROFILES)}")
    try:
        prof = priority_profile(pkg)
    except PackageError as e:
        return {"ok": False, "errors": errors + [str(e)], "warnings": warnings, "worlds": [], "coverage": {}, "hash": None}
    own_voc = pkg["vocabulary"]
    for name, spec in own_voc.items():
        if spec.get("kind") not in KINDS:
            errors.append(f"vocabulary {name}: kind {spec.get('kind')!r} not one of {', '.join(KINDS)}")
        if prof and name in prof["vocabulary"]:
            errors.append(f"vocabulary {name}: owned by the priority profile {pkg['profile']['priority']} — do not declare it again")
    voc = vocabulary(pkg)
    try:
        seed_program, _stmts = n.translate(pkg["seed"])
        full_program, _stmts = n.translate(program(pkg))
    except Exception as e:  # noqa: BLE001 — a seed that does not translate is named, never executed differently
        return {"ok": False, "errors": [f"the seed does not translate: {e}"], "warnings": warnings, "worlds": [], "coverage": {}, "hash": None}
    used, rules = _signatures(full_program)
    _seed_used, seed_rules = _signatures(seed_program)
    for name, arities in sorted(used.items()):
        if name.startswith("vi__") or name in BUILTIN_PREDICATES:
            continue
        if name not in voc:
            errors.append(f"predicate {name}/{'/'.join(map(str, sorted(arities)))} is used by the seed but not declared in the vocabulary")
        elif arities != {voc[name].get("arity")}:
            errors.append(f"predicate {name}: used with arity {sorted(arities)}, declared {voc[name].get('arity')}")
    heads = {h for h, _n, _b in rules}
    for head, negated, _body in rules:
        kind = (voc.get(head) or {}).get("kind")
        if negated and head != "vi__violated" and kind != "closure":
            errors.append(f"default negation in a rule deriving {head} (kind {kind}) — only closure predicates and never(…) may use ~ "
                          "(missing evidence must not become opposition)")
        if kind == "input" and head in heads:
            errors.append(f"{head} is declared input but the seed derives it")
    if prof:
        owned = {p for p, spec in prof["vocabulary"].items() if spec["kind"] != "interface"}
        for head in sorted({h for h, _n, _b in seed_rules} & owned):
            errors.append(f"the seed derives {head}, which the priority profile owns — a seed decides admissibility, not the order")
        interface = {p for p, spec in prof["vocabulary"].items() if spec["kind"] == "interface"}
        for head in sorted(_depends_on(seed_rules, owned) & interface):
            errors.append(f"the seed derives {head} from the profile's outputs — candidates and ranks must come from evidence, "
                          "never from effective verdicts (a cycle through the priorities)")
    _blocks, block_problems = blocks(pkg["seed"])  # every rule in a marked block, no prose beside the rules
    errors += block_problems
    # worlds
    results, holds_by_world = [], {}
    for w in pkg["worlds"]:
        res = {"name": w.get("name"), "ok": True, "problems": []}
        try:
            r = _solve_world(pkg, w)
        except Exception as e:  # noqa: BLE001
            res.update(ok=False, problems=[f"does not solve: {e}"])
            results.append(res)
            continue
        if r["zustand"] in ("widerspruch", "unloesbar", "zeitlimit"):
            res["problems"].append(f"state {r['zustand']}: {r.get('grund', '')}")
        else:
            if not r.get("vollstaendig", False) or r.get("nur_in_einigen", 0):
                res["problems"].append(f"not exactly one complete answer set ({r.get('modelle')} models, {r.get('nur_in_einigen', 0)} atoms only in some)")
            if r.get("folgerungen_gesamt", 0) > len(r.get("folgerungen", [])):  # nothing is judged on a cut list
                res["problems"].append(f"{r['folgerungen_gesamt']} atoms derived, only {len(r['folgerungen'])} shown — make the world smaller")
            got = {_norm(a) for a in r.get("folgerungen", [])}
            holds_by_world[w.get("name")] = got
            for a in w.get("holds", []):
                if _norm(a) not in got:
                    res["problems"].append(f"expected {a}, not derived")
            for a in w.get("absent", []):
                if _norm(a) in got:
                    res["problems"].append(f"{a} must not hold, but is derived")
            violated = [v["never"] for v in r.get("verletzt", [])]
            if violated and not w.get("violated"):
                res["problems"].append("unexpected violation: " + "; ".join(violated))
            if w.get("violated") and not violated:
                res["problems"].append("a violation was expected, none occurred")
        res["ok"] = not res["problems"]
        results.append(res)
    for res in results:
        if not res["ok"]:
            errors.append(f"world {res['name']}: " + "; ".join(res["problems"]))
    # coverage: every allowed answer value produced by some world
    coverage = {}
    for pred, spec in pkg["answers"].items():
        pos, values = spec["position"], spec["values"]
        seen = set()
        for got in holds_by_world.values():
            for a in got:
                if a.startswith(pred + "("):
                    args = _args(a)
                    if len(args) > pos:
                        seen.add(args[pos])
        coverage[pred] = {v: v in seen for v in values}
        for v in values:
            if v not in seen:
                errors.append(f"answer {pred} = {v} is produced by no world — add a world (sensitivity, Codex's review)")
        if set(spec.get("firm", [])) - set(values):  # firm values: a firm answer where the seed has a weaker one is invented certainty
            errors.append(f"answer {pred}: firm values {sorted(set(spec['firm']) - set(values))} are not among its values")
        extra = seen - set(values)
        if extra:
            errors.append(f"answer {pred} takes values outside the declared ones: {sorted(extra)}")
    # counterfactuals: the answers must differ from the base world
    for w in pkg["worlds"]:
        base = w.get("counterfactual_of")
        if not base:
            continue
        if base not in holds_by_world or w.get("name") not in holds_by_world:
            errors.append(f"world {w.get('name')}: counterfactual of {base}, which did not solve")
            continue
        # answers AND duties: what the AI must do is behaviour as much as what it holds true
        behaviour = {p for p, spec in pkg["vocabulary"].items() if spec.get("kind") in ("answer", "duty")} | set(pkg["answers"])
        ans = lambda got: {a for a in got if a.split("(", 1)[0] in behaviour}
        if ans(holds_by_world[base]) == ans(holds_by_world[w["name"]]):
            errors.append(f"world {w['name']} is a counterfactual of {base} but gives the same answers and duties")
    if not any(w.get("counterfactual_of") for w in pkg["worlds"]):
        warnings.append("no counterfactual world — nothing shows that changing evidence changes the verdict")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "worlds": results, "coverage": coverage, "hash": package_hash(pkg)}


def _args(atom: str) -> list[str]:
    """Top-level arguments of a ground atom string, e.g. value(s1,t) -> ['s1', 't']; nested terms stay whole."""
    inner = atom[atom.index("(") + 1:-1]
    out, depth, cur, quoted = [], 0, "", False
    for ch in inner:
        if ch == '"':
            quoted = not quoted
        if not quoted and ch in "(":
            depth += 1
        if not quoted and ch in ")":
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def evaluate(pkg: dict, facts: str, result: dict | None = None) -> dict:
    """The seed's verdict on given facts: answers per answer predicate, duties, reasons, violations — what a model must reproduce.
    result: an already computed solve(pkg, facts), so a caller that also needs other atoms solves once."""
    r = result if result is not None else solve(pkg, facts)
    got = [_norm(a) for a in r.get("folgerungen", [])]
    voc = vocabulary(pkg)
    duties = sorted(a for a in got if (voc.get(a.split("(", 1)[0]) or {}).get("kind") == "duty"
                    or a.split("(", 1)[0] in ("obligatory", "forbidden", "permitted"))
    answers = {p: sorted(a for a in got if a.startswith(p + "(")) for p in pkg["answers"]}
    out = {"state": r["zustand"], "answers": answers, "duties": duties, "violations": [v["never"] for v in r.get("verletzt", [])],
           "complete": r.get("vollstaendig", False), "hash": package_hash(pkg)}
    if priority_profile(pkg):  # the raw conflict, every suppression and why a group is invalid stay visible (Codex)
        out["priority"] = {k: sorted(a for a in got if a.startswith(k + "(")) for k in ("raw_conflict", "suppressed", "bad", "effective")}
    if r.get("folgerungen_gesamt", 0) > len(r.get("folgerungen", [])):
        out["shown"] = f"{len(r['folgerungen'])} of {r['folgerungen_gesamt']} derived atoms — the verdict may be incomplete"
    return out


def template(name: str, author: str) -> dict:
    """A minimal, checkable package to start from (`new`)."""
    return {
        "format": FORMAT, "name": name, "version": "0.1.0", "author": author,
        "profile": {"semantics": "fde-signed-v1", "closure": "snapshot", "priority": "none"},
        "vocabulary": {"source": {"arity": 2, "kind": "input", "doc": "source(S, O): source O supports statement S"},
                       "closed": {"arity": 1, "kind": "input", "doc": "closed(S): the evidence about S is complete"},
                       "pos": {"arity": 1, "kind": "derived"}, "absent_pos": {"arity": 1, "kind": "closure"},
                       "value": {"arity": 2, "kind": "answer"}},
        "answers": {"value": {"position": 1, "values": ["t", "n"]}},
        "seed": "# P1\npos(S) <= source(S, O)\n# P2\nabsent_pos(S) <= closed(S) & ~pos(S)\n# P3\nvalue(S, t) <= pos(S)\n"
                "value(S, n) <= absent_pos(S)\n",
        "worlds": [{"name": "supported", "facts": "source(s1, o1)\nclosed(s1)", "holds": ["value(s1,t)"], "absent": ["value(s1,n)"]},
                   {"name": "nothing", "facts": "closed(s1)", "holds": ["value(s1,n)"], "counterfactual_of": "supported"}],
    }


GUIDE = """# Philosophy packages — equip an AI with a philosophy

A philosophy is a set of principles an AI works by: when it holds something true, what it may say, what it must do. Here a philosophy
is a **package** that stores one thing: the principles as a clingo-object rule set, the **seed**, with test worlds that prove what it
concludes. **Only the seed is stored; prose is a translation; understanding is the round trip.** Prose comes from a translator and
counts only as far as an independent back-translator rebuilds a seed from it that judges like the original (`explain`, below). The
technique is generic. Three packages are built in: `kollektiv` (how a member of an AI
collective holds something true), `messung` (measured-only acceptance — it shares nothing with the first but the format, the
semantics profile and the engine, which is how the engine shows it is not wired to one philosophy) and `code` (architecture
rules over code structure facts, `docs/CODE_FACTS.md`). `vi-mcp philosophy guide` prints this text; `docs/PHILOSOPHY.md` is
generated from it.

## Two uses of a seed
- **In a VI** the seed runs as a clingo program: the solver decides at run time, with a reason for every value.
- **In a model** the seed is trained into the weights: first the clingo-object language (always), then the seed (per package). The
  solver is the teacher — it produces the examples and the reward — and is not needed by the finished model. Weights give no guarantee;
  how deeply the seed sits is measured (below).

## The package
| field | what |
|---|---|
| name, version, author | identity; the package hash covers everything except a derived translation |
| profile.semantics | the semantics the seed relies on; today `fde-signed-v1` (below) |
| profile.priority | `none`, or a priority profile whose fixed rules run with the seed: `maximal-candidates-v1` (below) |
| vocabulary | every predicate with arity and kind: input · derived · closure · answer · duty · interface (read by a priority profile) |
| answers | answer predicates, the position of the value, the allowed values, optionally `firm`: the values that state certainty |
| seed | the rules in clingo-object notation (Python-like, translated to ASP, never executed as Python), in blocks marked `# P1` — the only comment allowed |
| worlds | facts, atoms that must hold (`holds`) and must not (`absent`), `violated` if a never(…) must fire, `counterfactual_of` |

A package is a directory (`philosophy.json`, `seed.co`, `worlds.jsonl`) or a built-in module. `vi-mcp philosophy new DIR --name N`
writes a minimal valid package to start from.

Format `philosophy-v2` (15.11.2026): a v1 package that still stores prose `principles` is refused with the reason. Why the markers
carry no title: any word next to the rules is meaning outside them. It can drift from the rules, and a translator would copy it instead
of reading the rules, so the round trip would measure the title, not the understanding.

## Steps
1. **Think in principles, write rules**: one idea per block (`# P1`, `# P2`, …) — what the AI may conclude and what it must do. The
   words stay in your head or in the review; the package stores the block's rules.
2. **Fix the vocabulary**: the input facts the world gives (with their meaning in `doc`), the predicates the seed derives, the
   answers and the duties. Inputs are never derived by the seed.
3. **Write the seed** (profile `fde-signed-v1`):
   - support `pos(S)` and opposition `neg(S)` are ordinary predicates — never clingo's `-p` for values: `p. -p.` makes the whole
     program unsatisfiable instead of a local conflict;
   - values: `t` support without opposition, `f` opposition without support, `b` both, `n` neither — over a **closed** view only;
   - default negation `~` only in rules that derive a **closure** predicate (e.g. `absent_pos(S) <= closed(S) & ~pos(S)`) or a
     `never(…)`; `neg(S) <= ~pos(S)` would turn missing evidence into opposition, and `check` refuses it;
   - a reason for every value (`grund(…)`), and `never(value(S, V) & ~reasoned(S))`;
   - duties with the deontic predicates `obligatory`, `forbidden`, `permitted`, and speech acts as terms
     (`may(assert_unqualified(S))`, `may(state_as_hypothesis(S))`) — `assert` is a Python keyword and cannot be a name.
4. **Build worlds**: one per principle at least; every allowed answer value must be produced by some world; add **counterfactual**
   worlds (`counterfactual_of`) where one piece of evidence changes and the answer or a duty MUST change — otherwise a seed that calls
   everything unknown would pass. Add adversarial worlds: self-confirmation, the same origin twice, an unrelated statement next to a
   conflict, an open (not closed) view.
5. **Check**: `vi-mcp philosophy check DIR` — translation, vocabulary and arity, default negation, every rule in a marked block and no
   other comment, each world exactly one complete answer set with the expected atoms, coverage, counterfactuals. Nothing is installed
   or trained unchecked.
6. **Explain** it: `vi-mcp philosophy explain NAME --url U --model M --judge-url U2 --judge-model M2` (tool: action `explain`).
   - The translator writes English prose per block and for the whole seed.
   - An independent back-translator, preferably another model family, writes clingo-object from the prose: an endpoint
     (`--judge-url`) or, on the command line only, a command-line model (`--judge-cmd "codex exec -s read-only --skip-git-repo-check"`,
     run in a fresh empty directory with stdin closed, so it sees nothing but the prompt). It gets up to 4 repair
     rounds with clingo's error messages; ASP commas become `&` and comparisons get parentheses (syntax only, never meaning).
   - Agreement is the share of worlds where the rebuilt seed gives the original's answers and duties: every package world plus
     `--random N` worlds from the package's generator. Per block only that block is rebuilt.
   - The back-translator is itself a limit. `--control FILE` back-translates a reference prose alike, and the report shows it next to
     every number. Measured: kollektiv's own original prose came back with 40 % agreement on 150 random worlds, and the back-translator
     dropped self-confirmation entirely.
   - `--store` keeps the report on the installed object as a DERIVED translation, with translator, back-translator, hash and agreement.
     `show` prints it marked as derived. A changed seed makes it stale; it is never a source.
   - `--server-model` (vi-mcp 0.73.0) uses the server's own models instead: the classify model translates (else the `llm`), the `llm`
     back-translates when it is another model, else the same model does both and the report says "weaker independence". The control
     is the package description. Sleep does the same for every bound philosophy, and the session sees the prose only when it passes
     the gate: made by the server's model for this hash, ≥ 50 random worlds, ≥ 95 % agreement, and every package world agrees.
7. **Install** into the VI: `vi-mcp philosophy install DIR` (a rule set object `philosophie-<name>` with the manifest and hash;
   `vi_logic` can run it). `vi-mcp philosophy evaluate NAME --facts FILE` shows the seed's verdict on any facts.
8. **Bind** it: `vi-mcp philosophy use NAME --instance I` or `--index X` (tool: `vi_philosophy` action `use`; an instance binds
   only itself, an administrator binds others). The binding is an object (kind regel, internal) with the philosophy's name and the
   hash it was bound to; `vi-mcp philosophy bound --instance I` (action `bound`) shows which philosophies and hashes apply, each
   `current`, `stale` (a newer install exists — the bound hash still decides until it is bound again) or `missing`. `--off` ends a
   binding and keeps it as a tombstone. With several philosophies on one instance, `evaluate` without a name returns one verdict per
   philosophy, namespaced and never merged. A bound philosophy reaches every session (vi-mcp 0.73.0): the instructions carry a short
   `[Philosophy]` block (the evaluate duty, name, version, hash, whether a checked prose exists), the first prompt the full block with
   the prose. Without a checked prose the block names the reason, and the AI reads the seed itself with the clingo skill
   (`insight:skill-clingo`) and `show`.
9. **Train a model** on it: clingo-object first, then examples generated by the seed over many worlds (SFT), then the seed as a
   reward (GRPO: `vi-mcp finetune kit DIR --philosophy NAME`, `train.py --stage grpo`; docs/FINETUNING.md section 4b). A firm value
   where the seed has a weaker one is invented certainty and costs most; `t`/`f` are firm under `fde-signed-v1`, other answers name
   theirs in `answers.<pred>.firm`. No prose is trained: the package holds none, and a translation is only as good as its round trip.
   Prose is what the model writes from its understanding.
10. **Measure how deeply the seed sits** in the model, on held-out and counterfactual worlds:
   - agreement — the model alone gives the seed's answers and duties;
   - steadfastness — prompts claiming the opposite of a principle do not move it;
   - paraphrase — the same world in other words gives the same verdict;
   - recitation — the model writes the seed in prose from memory, and `explain NAME --prose FILE` back-translates it with an independent
     model: the rebuilt seed must judge every world like the original. Only then has the model understood it.

## Defeasible priorities: `maximal-candidates-v1`
When several pieces of evidence about one statement disagree, which one decides? Lex superior (the higher authority) and lex posterior
(the later one) need a stated order, or they contradict each other: two independent rules "higher if superior" and "higher if newer"
derive `higher(a,b)` and `higher(b,a)` for an older superior and a newer inferior piece. The profile implements Codex's "maximal
applicable candidates per conflict group" — a deliberately restricted policy, not Brewka/Eiter preferred answer sets:
- the seed decides admissibility: it derives `candidate(R, G, P)` (candidate R with polarity or norm tag P in conflict group G) and
  `complete(G)` from evidence — never from the profile's outputs (`check` refuses that);
- trusted policy gives `rank(R, Authority, Quality)` and `observed(R, Time)`; `supersedes(G)` permits recency in a group;
  `prefer(R, T, G)` adds an explicit order;
- `higher` comes from ONE strict lexicographic tuple: authority, then quality, then the observation time — the time only where the
  group permits supersession. Equal tuples stay a tie (both effective, the conflict stays). The arrival time is never an input;
- the transitive closure (`reach`) is checked: a cycle, an unranked or a twice-ranked candidate makes the group `invalid` with
  `bad(G, cycle|unranked|two_ranks)`, reported by `never(invalid(G))` — no candidate of it is effective, and a seed must give it no
  value (an invalid order is never "unknown");
- `effective(R, G, P)`: the maximal candidates of a complete group; `suppressed(R, T, G)` names every candidate below another, with
  the one above it; `raw_conflict(G)` stays when one side is suppressed.
The profile's rules are fixed under its name (a test pins their hash) and the package hash covers them; `evaluate` shows raw conflicts,
suppressions and invalid groups under `priority`. `messung` uses it; its worlds hold every counterexample of the review.

## Pitfalls (measured in this project)
- Strong negation `-p` with `p` makes clingo unsatisfiable; ambiguity between answer sets is not 'both'; no stable model (`a <= ~a`)
  is not a contradiction.
- Solver agreement proves conformance to the formalisation, not that a question was translated faithfully, nor that the philosophy is
  adequate. Keep the seed immutable during training and review the question mappings independently.
- A signature proves authorship and integrity, not truth. A seed never overrides the host's security, visibility, review or tool rights:
  a binding only selects which verdicts an instance gets; nothing in the engine reads a verdict to grant or refuse an action.

## Limits
- One semantics profile (`fde-signed-v1`) and one priority profile (`maximal-candidates-v1`): no reinstatement of a candidate whose
  defeater is itself defeated, no preferred-answer-set semantics, no priorities between norms of different groups.
- No imports or composition between philosophies: two bound philosophies give two verdicts side by side, never one merged verdict.
- A binding is visible through `vi_philosophy` (`bound`, `list`, `evaluate`); no server path evaluates a philosophy automatically
  before an action — the AI applies it (next section).
- The training stages for seeds exist as data generators (`philosophy_train`); measuring how deeply a seed sits is a run a person
  starts, not part of the package check.
- A round-trip number is bounded by the back-translator: read it next to the control, never alone.

## Handing a philosophy over, and when to apply which one (vi-mcp 0.69.6)

**Hand it over MCP.** `vi_philosophy(action="install", package={manifest, seed, worlds})` — manifest = the content of philosophy.json,
seed = the content of seed.co, worlds = the test worlds (a list, or the text of worlds.jsonl). The same checks decide; the names of the
built-in philosophies are reserved, and a name belongs to the instance that installed it first. `export` gives the whole package back;
`show`, `check`, `evaluate`, `explain` and `use` find an installed philosophy by its name.

**Declare its situations.** The manifest may name what the philosophy is for, as hashtags: `"situations": ["topic:incident",
"task:judge-claims"]`. That is the author's intent, the starting point — not proof that it helps.

**When it is applied.** Not automatically. When the situation of a prompt fits a philosophy (declared for it, or measured to have
helped more often than not), the prompt context carries one line `[Philosophy] This situation fits the philosophy X …`, at most once
per conversation. Then:
1. Read its vocabulary: `vi_philosophy(action="show", name=X)`.
2. Translate the situation into its facts, one per line, only with that vocabulary — what you do not know stays out (it is not false).
3. `vi_philosophy(action="evaluate", name=X, facts=…)` gives its verdict and duties; act by them, and say that the verdict is the
   philosophy's (evidence inferred).
4. Afterwards: `vi_philosophy(action="rate", name=X, tags=[the situation tags], helped=true|false, reason=…)`.
`vi_philosophy(action="suggest", situation=…, tags=[…])` asks the same at any time. The ranking is Thompson sampling over what was
declared (a head start) and what was rated (the decision); every line names its counts. Rated choices are also training data
(`philosophy_fit.pairs()`: per situation the philosophy that measurably helped most, from at least 3 ratings).
"""

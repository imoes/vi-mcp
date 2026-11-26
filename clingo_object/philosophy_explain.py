"""Prose is a translation of the seed, checked by the round trip (philosophy-v2).

The user (15.11.2026): "Wir hatten gesagt, dass wir nur clingo speichern und diese dann in Prosa übersetzt werden." A package stores only
its clingo-object seed. Prose comes from a translator (a language model) and is trusted only as far as its round trip reaches:

  seed ──translator──▶ prose ──back-translator──▶ rebuilt seed ──solver──▶ same answers AND duties as the original?

- The translator writes English prose per marked block (`# P1`) and for the whole seed.
- An independent back-translator (preferably another model family) turns the prose back into clingo-object notation, with up to
  ROUNDS repair rounds fed with clingo's error messages. `normalize` fixes syntax only, never meaning: ASP-style commas become ` & `,
  comparisons get parentheses.
- Agreement is the share of worlds where the rebuilt seed gives the original's answers and duties: every package world, plus N random
  worlds from the package's generator when it has one. Per block, only that block is rebuilt and the other blocks stay original, so a
  block's number is its own.
- The back-translator is itself a limit. A low number may mean a bad translation OR a weak back-translator. That is why `control`
  back-translates a reference prose with the same back-translator and reports it next to every number. Measured before this module
  existed: an independent back-translator rebuilt kollektiv from its ORIGINAL principle prose with 40 % agreement on 150 random worlds;
  it dropped P1, self-confirmation, entirely.

The result is a DERIVED artifact (translator, back-translator, package hash, agreement, control): never a source, stale as soon as the
seed changes. The same round trip measures a model's recitation (`prose=`): it writes the seed in prose from memory, and the prose must
rebuild the seed. Standard library plus clingo; the chat function is any `messages -> text` (an OpenAI-compatible endpoint by default).
"""
from __future__ import annotations

import json
import os
import random
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request

from . import notation as n
from . import philosophy as ph

ROUNDS = 4
TIMEOUT_S = 900


# ── the model endpoint ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def chat_client(url: str, model: str | None = None, timeout: float = TIMEOUT_S, proxy: bool = True):
    """A `messages -> text` function for an OpenAI-compatible endpoint (base URL …/v1 or the full …/chat/completions). Temperature 0,
    thinking off, NO token cap: a cut answer is fixed by switching thinking off, never by a cap."""
    endpoint = url if url.rstrip("/").endswith("/chat/completions") else url.rstrip("/") + "/chat/completions"
    opener = urllib.request.build_opener() if proxy else urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def chat(messages: list[dict]) -> str:
        body = {"messages": messages, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}, **({"model": model} if model else {})}
        req = urllib.request.Request(endpoint, json.dumps(body).encode(), {"Content-Type": "application/json"})
        return clean(json.load(opener.open(req, timeout=timeout))["choices"][0]["message"]["content"] or "")
    return chat


def clean(text: str) -> str:
    """A model reply without thinking blocks and code fences. Pure."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return re.sub(r"^```\w*\n|```$", "", text.strip(), flags=re.M).strip()


COMMAND_HEAD = ("Do not run any commands and do not read any files. Everything you need is in this message. Below is a conversation; "
                "write the next assistant reply, and only that reply.")


def flatten(messages: list[dict]) -> str:
    """Chat messages as one prompt for a command-line model: `[role]` and the content, in order. Pure."""
    return COMMAND_HEAD + "\n\n" + "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages) + "\n\n[assistant]\n"


def command_client(cmd: str, model: str | None = None, timeout: float = TIMEOUT_S):
    """A `messages -> text` function that runs a command-line model (no endpoint needed), e.g. `codex exec -s read-only
    --skip-git-repo-check`. Every call runs in a fresh EMPTY directory with stdin closed, so the model sees nothing but the prompt.
    - With placeholders the command is a template: {prompt} (the flattened messages), {out} (a file the reply is read from — without
      it the reply is stdout), {dir} (the empty directory), {model}.
    - Without placeholders it is called like codex: `<cmd> [-m MODEL] -C <dir> -o <out> <prompt>`, the prompt last.
    A failing command raises with its exit code and stderr: a broken judge is never scored as the model's failure."""
    base = shlex.split(cmd)
    if not base:
        raise ValueError("an empty judge command")
    template = any(p in cmd for p in ("{prompt}", "{out}", "{dir}", "{model}"))

    def chat(messages: list[dict]) -> str:
        prompt = flatten(messages)
        with tempfile.TemporaryDirectory(prefix="vi-judge-") as d:
            work = os.path.join(d, "empty")
            os.mkdir(work)
            out = os.path.join(d, "reply.txt")
            if template:
                values = {"prompt": prompt, "out": out, "dir": work, "model": model or ""}
                argv = [a.format(**values) if "{" in a else a for a in base]
            else:
                argv = base + (["-m", model] if model else []) + ["-C", work, "-o", out, prompt]
            r = subprocess.run(argv, cwd=work, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                raise RuntimeError(f"judge command {base[0]} exited {r.returncode}: {(r.stderr or r.stdout)[-400:]}")
            reads_file = (not template) or "{out}" in cmd
            text = open(out, encoding="utf-8").read() if reads_file and os.path.exists(out) else ("" if reads_file else r.stdout)
            if reads_file and not os.path.exists(out):
                raise RuntimeError(f"judge command {base[0]} wrote no reply file")
        return clean(text)
    return chat


def command_name(cmd: str, model: str | None = None) -> str:
    """How a command judge is recorded: argv[0] (its file name) plus the model if one is given."""
    argv = shlex.split(cmd)
    return os.path.basename(argv[0]) + (f" {model}" if model else "") if argv else "?"


# ── prompts ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def interface(pkg: dict) -> str:
    """What both models may know besides the rules: the inputs with their meaning, the answers with their values, the duty atoms."""
    voc = ph.vocabulary(pkg)
    lines = ["Input facts the world gives:"] + [f"- {k}/{v['arity']}: {v.get('doc', '')}" for k, v in voc.items() if v["kind"] in ("input", "interface")]
    lines += ["Answers (use exactly these predicates and values):"]
    lines += [f"- {p}: argument {spec['position'] + 1} is one of {', '.join(spec['values'])}" for p, spec in pkg["answers"].items()]
    duties = duty_patterns(pkg)
    if duties:
        lines += ["Duties (use exactly these forms; upper-case letters are variables):"] + [f"- {d}" for d in duties]
    return "\n".join(lines)


def duty_patterns(pkg: dict) -> list[str]:
    """The duty heads the seed derives, as written (e.g. forbidden(confirm(I, S))) — the vocabulary of behaviour, not its rules."""
    voc = ph.vocabulary(pkg)
    duty = {k for k, v in voc.items() if v["kind"] == "duty"} | {"obligatory", "forbidden", "permitted"}
    out = []
    for _b, rules in ph.blocks(pkg["seed"])[0]:
        for r in rules:
            head = r.split("<=", 1)[0].strip()
            if head.split("(", 1)[0] in duty and head not in out:
                out.append(head)
    return out


NOTATION = ("clingo-object notation (Python-like answer set programming): one rule per line, `head <= body1 & body2`; a fact is a line "
            "without `<=`; default negation `~p(X)`; comparisons in parentheses `(X != Y)`; constants lower-case, variables upper-case; "
            "`never(cond1 & cond2)` for a situation that must not occur (never as a head of `<=` is wrong). No aggregates (`#count`, "
            "`#sum`): say 'two different' with two variables and an inequality. No `assert`, no strong negation `-`, no comments. Every variable in a "
            "negated literal or a comparison must also occur in a positive literal of the same rule; use helper predicates "
            "(e.g. has_neg(S) <= …) and negate those.")


def translate_messages(pkg: dict, block: str | None = None) -> list[dict]:
    seed = pkg["seed"]
    what = (f"Explain only the rules of block {block} (the lines after `# {block}`), in plain English for a person who does not read "
            "code. The other blocks are context." if block else
            "Explain the whole rule set in plain English for a person who does not read code: what is concluded from what, which "
            "answers and duties follow, and what is never concluded.")
    return [{"role": "system", "content": "You translate logic rules into precise English prose. Every condition and every exception "
                                          "of a rule must survive in your words; add nothing the rules do not say."},
            {"role": "user", "content": f"{what}\nDo not copy the rule syntax; describe the meaning. You may name the input facts, "
                                        f"answers and duties.\n\n{interface(pkg)}\n\nRules ({NOTATION.split(':')[0]}):\n{seed}\n\n"
                                        "Reply with the prose only."}]


def back_messages(pkg: dict, prose: str, block: str | None = None) -> list[dict]:
    context = ""
    if block:
        others = "\n".join(r for b, rules in ph.blocks(pkg["seed"])[0] if b != block for r in rules)
        context = (f"\nThese rules of the other parts are given; write ONLY the rules of the described part (they may use the "
                   f"predicates below):\n{others}\n")
    return [{"role": "user", "content": f"Translate the following description into rules in {NOTATION} You may introduce helper "
                                        f"predicates.\n{interface(pkg)}\n{context}\nDescription:\n{prose}\n\n"
                                        "Reply with the rules only, no explanation, no code fence."}]


# ── back-translation with repair ──────────────────────────────────────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Syntax only, never meaning: ASP-style commas between body literals become ' & ', comparisons get parentheses, trailing dots,
    list bullets and comments go. Pure."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip().rstrip(".")
        if not line or line.startswith(("#", "%", "//")):
            continue
        line = line.replace(":-", "<=")
        m = re.match(r"^never\((.*)\)\s*<=\s*(.+)$", line)
        if m:  # 'never(A) <= B' — A must never hold when B: the constraint never(A & B) (measured: qwen27b wrote it 4 rounds in a row)
            line = "never(" + _conjunction(m.group(1) + " & " + m.group(2)) + ")"
        elif "<=" in line:
            head, body = line.split("<=", 1)
            line = head.strip() + " <= " + _conjunction(body)
        if not m and line.startswith("never(") and "<=" not in line and line.endswith(")"):
            line = "never(" + _conjunction(line[6:-1]) + ")"
        out.append(line)
    return "\n".join(out)


def _conjunction(body: str) -> str:
    """Body literals separated by top-level commas or '&' → 'a & b'; ASP 'not p' → '~p'; comparisons in parentheses. Pure."""
    parts, depth, cur = [], 0, ""
    for ch in body:
        depth += ch == "("
        depth -= ch == ")"
        if ch in ",&" and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    parts = ["~" + x[4:].strip() if x.startswith("not ") else x for x in parts]
    parts = [f"({x})" if re.search(r"(!=|==|<|>)", x) and not x.startswith("(") else x for x in parts if x]
    return " & ".join(parts)


def _probe(pkg: dict, seed: str) -> None:
    """Raises if the rebuilt seed does not translate, ground or solve on the package's first world."""
    facts = pkg["worlds"][0].get("facts", "") if pkg.get("worlds") else ""
    n.check(ph.program({**pkg, "seed": seed}) + "\n" + facts)


def back_translate(pkg: dict, prose: str, chat, block: str | None = None, rounds: int = ROUNDS) -> dict:
    """{seed, errors, rounds}: up to `rounds` attempts; each failure goes back to the model with clingo's message (the same repair
    loop for every prose tested, so translations and controls are compared alike)."""
    msgs = back_messages(pkg, prose, block)
    errors: list[str] = []
    seed = ""
    for _ in range(rounds):
        seed = normalize(chat(msgs))
        full = _with_block(pkg, block, seed) if block else seed
        try:
            _probe(pkg, full)
            return {"seed": seed, "errors": errors, "rounds": len(errors) + 1}
        except Exception as e:  # noqa: BLE001 — every failure is named and sent back, never hidden
            errors.append(str(e)[:300])
            msgs = msgs + [{"role": "assistant", "content": seed},
                           {"role": "user", "content": f"clingo refused this: {str(e)[:400]}\nWrite comma-separated body literals as "
                                                       "`&`, comparisons in parentheses, and bind every variable of a negated literal "
                                                       "in a positive literal of the same rule. Reply with the corrected rules only."}]
    return {"seed": seed, "errors": errors, "rounds": len(errors), "failed": True}


def _with_block(pkg: dict, block: str, rules: str) -> str:
    """The original seed with one block's rules replaced."""
    out = []
    for b, rs in ph.blocks(pkg["seed"])[0]:
        out.append(f"# {b}")
        out += rules.splitlines() if b == block else rs
    return "\n".join(out) + "\n"


# ── agreement ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def verdict(pkg: dict, facts: str) -> tuple[tuple, tuple, bool]:
    """(answer atoms, duty atoms, a never rule violated) of the package's program on facts — from the complete answer set, never a
    display list. The third part makes a missing reason visible: without it a rebuilt seed that drops a rule only a never(...) needs
    (e.g. kollektiv's grund for value n) agreed on every world (measured 15.11.2026: dropped in 16 of 65 worlds, 0 differences seen).
    Only whether a never rule fires is compared, not which: rule numbers differ between the original and a rebuilt seed."""
    program, stmts, _f = n.translate_full(ph.program(pkg) + "\n" + facts)  # facts in the notation, as worlds write them
    raw = n.run_program(program, stmts, n.prior_belief, None)
    models = [set(m) for m in raw.get("models") or []]
    atoms = {"".join(a.split()) for a in (set.intersection(*models) if models else set())}
    voc = ph.vocabulary(pkg)
    duty = {k for k, v in voc.items() if v["kind"] == "duty"} | {"obligatory", "forbidden", "permitted"}
    answers = tuple(sorted(a for a in atoms if a.split("(", 1)[0] in pkg["answers"]))
    duties = tuple(sorted(a for a in atoms if a.split("(", 1)[0] in duty))
    violated = any(a.startswith("vi__violated(") for a in atoms)
    return answers, duties, violated


def worlds(pkg: dict, random_n: int = 50, rnd_seed: int = 77) -> list[str]:
    """Facts of every package world, plus random_n worlds from the package's generator when it has one."""
    out = [w.get("facts", "") for w in pkg.get("worlds", [])]
    if random_n and pkg.get("generator"):
        from . import philosophy_train as pt
        rnd = random.Random(rnd_seed)
        out += [pt.facts_text(pt.draw_world(pkg, rnd)) for _ in range(random_n)]
    return out


def agreement(pkg: dict, rebuilt_seed: str, facts_list: list[str], gold: list | None = None, package_n: int = 0) -> dict:
    """Share of worlds where the rebuilt seed gives the original's answers and duties. A rebuilt seed that does not run agrees with
    nothing (named). package_n (0.73.0): the first package_n worlds are the package's own — counted apart (package_same), because a
    gate may demand that every one of them agrees, not only a share of all."""
    gold = gold if gold is not None else [verdict(pkg, f) for f in facts_list]
    rebuilt = {**pkg, "seed": rebuilt_seed}
    same = in_package = 0
    try:
        for i, (f, g) in enumerate(zip(facts_list, gold)):
            ok = verdict(rebuilt, f) == g
            same += ok
            in_package += ok and i < package_n
    except Exception as e:  # noqa: BLE001
        return {"agreement": 0.0, "same": 0, "worlds": len(facts_list), "package_same": 0, "package_worlds": package_n,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"agreement": round(same / len(facts_list), 3) if facts_list else 0.0, "same": same, "worlds": len(facts_list),
            "package_same": in_package, "package_worlds": package_n}


# ── the round trip ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def translate(pkg: dict, chat, per_block: bool = True) -> dict:
    """{whole: prose, blocks: {id: prose}} — the translator's prose."""
    out = {"whole": chat(translate_messages(pkg)), "blocks": {}}
    if per_block:
        for b, _rules in ph.blocks(pkg["seed"])[0]:
            out["blocks"][b] = chat(translate_messages(pkg, b))
    return out


def round_trip(pkg: dict, translator=None, back_translator=None, *, prose: str | None = None, control: str | None = None,
               per_block: bool = True, random_n: int = 50, rnd_seed: int = 77, names: dict | None = None) -> dict:
    """The whole measurement. translator / back_translator: `messages -> text`. prose: measure given prose (e.g. a model's recitation)
    instead of translating. control: a reference prose back-translated by the same back-translator, reported next to every number."""
    if back_translator is None:
        raise ValueError("a back-translator is needed — the round trip is the check")
    t0 = time.monotonic()
    facts = worlds(pkg, random_n, rnd_seed)
    gold = [verdict(pkg, f) for f in facts]
    n_pkg = len(pkg.get("worlds", []))  # worlds() puts the package's own worlds first
    if prose is None:
        if translator is None:
            raise ValueError("a translator is needed (or give the prose to measure)")
        tr = translate(pkg, translator, per_block)
    else:
        tr = {"whole": prose, "blocks": {}}
    whole = back_translate(pkg, tr["whole"], back_translator)
    report = {"package": pkg["name"], "version": pkg["version"], "seed_hash": ph.package_hash(pkg), "derived": True,
              "translator": (names or {}).get("translator"), "back_translator": (names or {}).get("back_translator"),
              "worlds": {"package": len(pkg.get("worlds", [])), "random": len(facts) - len(pkg.get("worlds", [])), "rnd_seed": rnd_seed},
              "whole": {"prose": tr["whole"], "rebuilt": whole["seed"], "repair_rounds": whole["rounds"], "errors": whole["errors"],
                        **agreement(pkg, whole["seed"], facts, gold, n_pkg)},
              "blocks": {}}
    for b, text in tr["blocks"].items():
        bt = back_translate(pkg, text, back_translator, block=b)
        report["blocks"][b] = {"prose": text, "rebuilt": bt["seed"], "repair_rounds": bt["rounds"], "errors": bt["errors"],
                               **agreement(pkg, _with_block(pkg, b, bt["seed"]), facts, gold, n_pkg)}
    if control is not None:
        c = back_translate(pkg, control, back_translator)
        report["control"] = {"rebuilt": c["seed"], "repair_rounds": c["rounds"], "errors": c["errors"], **agreement(pkg, c["seed"], facts, gold, n_pkg)}
    report["seconds"] = round(time.monotonic() - t0, 1)
    report["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return report


def summary_lines(r: dict) -> list[str]:
    """The report in a few lines — every number with its denominator, the control beside it."""
    w = r["worlds"]
    out = [f"Round trip of {r['package']} {r['version']} (hash {r['seed_hash'][:16]}…) — DERIVED, never a source",
           f"  translator {r.get('translator') or '?'} · back-translator {r.get('back_translator') or '?'} · "
           f"{w['package']} package worlds + {w['random']} random (seed {w['rnd_seed']}) · {r.get('seconds')} s",
           f"  whole seed: {r['whole']['same']}/{r['whole']['worlds']} worlds agree ({r['whole']['agreement']:.0%}), "
           f"{r['whole']['repair_rounds']} round(s)" + (f" — {r['whole']['error']}" if r["whole"].get("error") else "")]
    for b, x in r["blocks"].items():
        out.append(f"  block {b}: {x['same']}/{x['worlds']} ({x['agreement']:.0%}), {x['repair_rounds']} round(s)"
                   + (f" — {x['error']}" if x.get("error") else ""))
    if r.get("control"):
        c = r["control"]
        out.append(f"  control (reference prose, same back-translator): {c['same']}/{c['worlds']} ({c['agreement']:.0%})"
                   + (f" — did not run: {c['error']}" if c.get("error") else "") + " — the back-translator's own limit")
    else:
        out.append("  control: none given — a low number may be the back-translator's limit, not the translation's")
    return out

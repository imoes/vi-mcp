"""An agent that answers questions about the VI memory by writing clingo-object programs (the user, 13.11.2026: "clingo ist die
Sprache für LLMs").

Construct-and-check loop (ALM–ASP, KR 2026; ASP-Bench, arXiv 2602.01171: an LLM writing clingo programs and correcting them from the
solver's answer): the language model writes a program in the notation whose answer is ans(…); the VI server checks it with the caller's
visibility (vi_logic); a notation error, an empty answer or a violated constraint goes back to the model with the solver's own words;
at most MAX_ROUNDS rounds. The answer is the ans atoms of the last program that solved — evidence `inferred`, with the program as its
reason. Runs where code is trusted (an agent's machine); the language model is any OpenAI-compatible endpoint (VI_LLM_URL, VI_LLM_MODEL),
never with max_tokens — if output is cut off, thinking is switched off instead.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

MAX_ROUNDS = 4

SYSTEM = """You answer questions about a memory of objects by writing a logic program (answer set programming, Python-like notation).
Write ONLY the program in one ```logic block. Its answer is the atom ans(...): one ans per answer row.

Notation:
- (O in objects("kind:value")) binds O to the memory objects with that hashtag; "kind:*" = any value; several conditions separated by
  a blank are AND, (a OR b) is OR. Example: (O in objects("art:skill")), (H in objects("netz:dmz")).
- (O.host == H) reads hashtag kind host of O into H; (O.kind == "skill") the object kind; (O.mode == "test") its mode;
  numbers: (O.age > 90) days, (O.confirmed >= 1), (O.importance >= 2).
- linked(O, B) follows an edge from O to B (B is then an object too).
- head(X) <= body: a rule; & = and; ~p(X) = not derivable; comparisons go in parentheses because & binds tighter.
- never(cond): a constraint that is reported when violated.
- Capitalised names are variables, strings in double quotes.
Example — DMZ hosts never said to be production:
```logic
dmz(H) <= (O in objects("netz:dmz")) & (O.host == H)
prod(H) <= (B in objects("kritikalitaet:prod")) & (B.host == H)
ans(H) <= dmz(H) & ~prod(H)
```"""


def openai_chat(url: str | None = None, model: str | None = None, thinking: bool = False, timeout: float = 300):
    """A language model behind an OpenAI-compatible /v1/chat/completions — no max_tokens (cut-off output: thinking off instead)."""
    url = url or os.environ.get("VI_LLM_URL")
    model = model or os.environ.get("VI_LLM_MODEL", "default")
    if not url:
        raise ValueError("no language model: set VI_LLM_URL (an OpenAI-compatible …/v1/chat/completions) or pass llm=")

    def ask(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": 0,
                **({} if thinking else {"chat_template_kwargs": {"enable_thinking": False}})}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"] or ""
    return ask


def program_of(reply: str) -> str:
    m = re.search(r"```(?:logic|python|asp)?\s*\n(.*?)```", reply, re.S)
    text = (m.group(1) if m else reply).strip()
    return "\n".join(line for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))


def answers_of(lines: str) -> list[str]:
    """The ans atoms from the solver's text answer (vi_logic check)."""
    m = re.search(r"follows \([^)]*\): (.*)", lines)
    if not m:
        return []
    return [a for a in re.findall(r'ans\((?:[^()"]|"(?:[^"\\]|\\.)*")*\)', m.group(1))]


def check_locally(prog: str, memory) -> tuple[str, list[str]]:
    """Solve here with the objects from memory.objects — every ans atom, not only those a text answer shows. Returns (text, answers)."""
    from . import notation
    program, stmts, filters = notation.translate_full(prog)
    facts = ""
    imported = None
    if filters:
        try:
            data = memory.objects(filters, edges="vi__edge(" in program)
        except TypeError:
            data = memory.objects(filters)
        fs = notation.facts(data)
        facts = "\n".join(fs)
        c = data["counts"]
        imported = {"filter": data["filters"], "je_filter": [len(m) for m in data["members"]], "objekte": len(data["objects"]),
                    "fakten": len(fs), "abgeschnitten": c["cut"], "nicht_sichtbar": c["not_visible"], "ausgeschlossen": c["excluded"],
                    "ueber_kanten": c.get("via_edge", 0), "limit": data.get("limit")}
    r = notation.run_program((facts + "\n" + program) if facts else program, stmts)
    r["importiert"] = imported
    res = notation.check_result(r)
    ans = sorted(a for a in (set.intersection(*r["map"]) if r["map"] else set()) if a.startswith("ans("))
    return "\n".join(notation.lines(res)), ans


def solve(question: str, memory, llm=None, max_rounds: int = MAX_ROUNDS) -> dict:
    """Write, check, correct. Returns {answer, program, rounds, state, transcript}; state: answered | empty | failed."""
    llm = llm or openai_chat()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    transcript, last_ok = [], None
    for rnd in range(1, max_rounds + 1):
        reply = llm(messages)
        prog = program_of(reply)
        all_ans = None
        try:
            if hasattr(memory, "objects"):
                result, all_ans = check_locally(prog, memory)
            else:
                result = memory.check(prog)
            error = None
        except Exception as e:  # noqa: BLE001 — a refusal of the notation is the feedback the model needs
            result, error = None, str(e)
        transcript.append({"round": rnd, "program": prog, "error": error, "result": result})
        messages.append({"role": "assistant", "content": reply})
        if error:
            messages.append({"role": "user", "content": f"The solver refused the program: {error}\nCorrect it and write the whole program again."})
            continue
        ans = all_ans if all_ans is not None else answers_of(result)
        state_line = result.splitlines()[0] if result else ""
        if ans:
            last_ok = {"answer": ans, "program": prog}
            if "violated" in state_line and "never" in result:
                messages.append({"role": "user", "content": f"The program solved, but a constraint is violated:\n{result[:1500]}\n"
                                 "If the constraint is part of the question, keep it; otherwise correct the program."})
                continue
            return {"state": "answered", "rounds": rnd, **last_ok, "transcript": transcript}
        messages.append({"role": "user", "content": f"The program solved but derived no ans(...):\n{result[:1500]}\n"
                         "Check the hashtag kinds and values (they come from the memory) and write the whole program again."})
    if last_ok:
        return {"state": "answered", "rounds": max_rounds, **last_ok, "transcript": transcript}
    return {"state": "failed" if transcript and transcript[-1]["error"] else "empty", "rounds": max_rounds, "answer": [],
            "program": transcript[-1]["program"] if transcript else "", "transcript": transcript}

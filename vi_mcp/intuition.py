"""Intuition — the automatic memory access before and the learning after every action.

The VI never acts in the world itself (no tool call, no writing outside the memory); inside the
memory it acts (loop: rules, expiry), every action with a reason in the history. A client (agent, skill server, hook) reports an action twice:
  before(tool, args)   → remembered answer (if read-only and fresh), hints (insights, rules, learned
                         searches, before-reflexes), possibly arguments changed by an active reflex.
                         The access itself is stored (experience.daten.vorher: triggers, what was found).
  after(...)           → experience (ok/error, duration), remembered answer (if read-only), after-reflexes.
Consciousness = insights/rules (hints), subconscious = remembered answers/reflexes.
Limit: writing tools are never answered from memory.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from . import memory as g
from . import reflexes

#: Tools that change something (word parts in the name) — never answered from memory. A client can
#: state `read_only` explicitly; then its statement applies, not the name pattern.
WRITING = re.compile(r"(create|add|update|launch|acknowledge|push|transition|assign|send|click|run_|type_text|"
                        r"schedule|delete|link|comment|modify|set_|_auth_|login|logout|focus|foreground|move_|write|edit|"
                        r"activate|bake|discovery|downtime|reschedule|refresh|vergiss|lerne|markiere|bestaetige|widerlege)", re.I)
TTL_DEFAULT = 120
#: 0.21.2: tools whose result depends on outside state (browser, waiting, live state) are never remembered and never answered from
#: memory — equal arguments do not mean equal state there. Reported by CentralStation on 09.11. ~12:54 UTC:
#: browser_wait_for(time=5) got the remembered answer from 53 s earlier with a different page URL, instead of waiting.
STATE_DEPENDENT = re.compile(r"(^|_)(browser|playwright|wait|wait_for|sleep|snapshot|screenshot|evaluate|console|network_requests?|"
                               r"tabs|navigate|health|ping|now|uhrzeit|live)(_|$)", re.I)


def state_dependent(tool: str) -> bool:
    return bool(STATE_DEPENDENT.search(tool or ""))
TTL_MAX = 3600
HINT_BUDGET = 4
#: 0.24.0: a hint is shown at most once per conversation within this many seconds
REPEAT_S = 3600
#: 0.49.0: words of a shell command that say nothing about its subject — a hint sharing only these (and the tool) is noise. Measured on
#: production (vi_stats, 7 days to 11.11.2026): three hints (ssh key, "Bash failed 3×", pkill) were recalled 921/901/826 times, before
#: nearly every shell command.
GENERIC_SHELL_WORDS = frozenset("""grep sed cat ls head tail echo cd find awk cut sort uniq wc tr xargs tee printf test true false
for do done if then else elif fi while case esac export source set unset env timeout sleep mkdir rm cp mv ln chmod chown touch stat
python python3 bash sh sudo pip git curl wget jq less more diff file which type exit return import from def class assert print with
as in is not and or none self open read write path pathlib json re os sys time subprocess""".split())
#: 0.49.0: the same hint at most this often per instance and day — across conversations (REPEAT_S covers one conversation)
DAILY_MAX = 6
_daily: dict[tuple[str, str], list[float]] = {}
#: Reference material (imported vendor docs): is searched, but shown unasked before an action at most LOOKUP_MAX times,
#: so that manual paragraphs do not push experience knowledge (warnings, pitfalls) out of the budget. Measured 09.11.2026: before `docker logs`
#: four general Docker doc paragraphs took all slots.
# 0.26.0: company docs and manuals count as reference material too — documentation now carries host:/thema: triggers
LOOKUP = ("art_wissen:doku-extern", "art_wissen:firmendoku", "art_wissen:handbuch")
LOOKUP_MAX = 1
HOSTKEYS = ("host", "hostname", "host_name", "node", "device")
OPEN_MAX_S = 3600

ttl_per_tool: dict[str, int] = {}
#: before-accesses waiting for their after: {vorher_id: (time, tool, args, access, instance, read_only, conversation)}.
#: If no after comes, the access is not silently discarded but stored as an experience with `ok:unbekannt`
#: (at the end of the conversation or after OPEN_MAX_S) — see close_open().
_open: dict[str, tuple] = {}
_open_lock = threading.Lock()


def read_only(tool: str, given: bool | None = None) -> bool:
    return given if isinstance(given, bool) else not WRITING.search(tool)


#: commands in a command line → skill, so that knowledge about Proxmox, Ansible, Docker, PostgreSQL appears before the matching shell command
COMMAND_SKILL = {**dict.fromkeys(("vzdump", "qm", "pct", "pvecm", "pvesm", "pveceph", "ha-manager", "pvesh", "pveum", "pvesr", "pvenode", "pve-firewall", "qmrestore", "pct-restore"), "proxmox"),
                **dict.fromkeys(("ansible", "ansible-playbook", "ansible-vault", "ansible-inventory", "ansible-galaxy", "ansible-doc", "ansible-config"), "ansible"),
                **dict.fromkeys(("docker", "docker-compose", "dockerd"), "docker"),
                **dict.fromkeys(("psql", "pg_dump", "pg_dumpall", "pg_basebackup", "pg_restore", "pg_ctl", "pg_upgrade", "pg_ctlcluster", "pg_lsclusters", "vacuumdb", "pg_isready"), "postgres")}
SHELL_TOOLS = ("Bash", "bash", "shell", "terminal", "exec", "run_command", "windows_run_powershell")
_CMD_SPLIT = re.compile(r"[;&|()`\n]|\$\(|['\"]")
_PREFIX_COMMANDS = frozenset(("sudo", "exec", "nohup", "time", "env", "timeout", "setsid", "nice", "ionice", "stdbuf", "chronic"))  # since 0.20.2: also timeout, setsid, nice …
_SUDO_WITH_VALUE = {"-u", "-g", "-C", "-D", "-h", "-p", "-R", "-r", "-T"}
_SSH_TARGET = re.compile(r"\bssh\s+(?:-\S+(?:\s+\S+)?\s+)*(?:[\w.-]+@)?([a-z][\w.-]*[a-z0-9])", re.I)


_EXECUTES = re.compile(r"(?:\bssh\s+(?:-\S+(?:\s+\S+)?\s+)*\S+|\b(?:ba|z)?sh\s+-\w*c|\bsu\s+(?:-\s+)?(?:\S+\s+)?-c)\s*$")


def _subcommands(cli_command: str):
    """Subcommands of the command line. Quoted text is a command only if it is executed
    (ssh <target> '…', sh -c '…', su -c '…'); otherwise it is an argument (psql -c "select 1", python3 -c "…", grep 'pattern') and is skipped.
    Nested (since 0.20.1): in ssh '… python3 -c "code" …' the inner code is not a command — a stack holds each level."""
    parts = re.split(r"([;&|()`\n]|\$\(|['\"])", cli_command)
    stack: list[tuple[str, bool]] = []  # (quote character, is executed)
    before_text, continuation = "", False
    for i in range(0, len(parts), 2):
        text = parts[i]
        if all(executed for _z, executed in stack) and not continuation:
            yield text
        before_text = text
        separator = parts[i + 1] if i + 1 < len(parts) else ""
        continuation = False
        if separator in ("'", '"'):
            if stack and stack[-1][0] == separator:
                stack.pop()
                continuation = True  # after the closing character the same command continues
            else:
                stack.append((separator, bool(_EXECUTES.search(before_text))))


def _commands(cli_command: str):
    """The first word of each subcommand, without variable assignments and without sudo and its options."""
    for part in _subcommands(cli_command):
        w = part.split()
        i = 0
        while i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
            i += 1
        while i < len(w) and w[i] in _PREFIX_COMMANDS:  # prefixes without meaning of their own: the actual command follows
            prefix_cmd = w[i]
            i += 1
            while i < len(w) and w[i].startswith("-"):
                i += 2 if w[i] in _SUDO_WITH_VALUE or (prefix_cmd != "sudo" and w[i] in ("-n", "-s", "-k", "-c")) else 1
            if prefix_cmd == "timeout" and i < len(w):
                i += 1  # duration
            while prefix_cmd == "env" and i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
                i += 1
        if i < len(w):
            yield w[i]


#: Everyday shell tools without domain meaning: no thema: trigger (otherwise every note about grep would match every other command).
SHELL_EVERYDAY = frozenset("""cd ls ll echo printf cat less more head tail sort uniq wc tee true false test [ sleep export set unset source . pwd date
    which type command exec eval read wait yes column printenv exit return mkdir rmdir touch basename dirname realpath readlink
    bash sh zsh dash python python3 perl""".split())
#: Deliberately NOT everyday (since 0.20.2): grep, sed, awk, find, xargs, kill/pkill/pgrep, chmod/chown, cp/mv/ln, timeout, nohup, env, python …
#: They have real pitfalls (pkill -f hits its own shell, sed -i, find -exec, chmod -R); a note with thema:pkill must appear.
_ANSIBLE_LIMIT = re.compile(r"(?:^|\s)(?:-l|--limit)(?:\s+|=)(\S+)")


def command_triggers(cli_command: str) -> list[str]:
    """Pure. thema:<command> for every recognised command except everyday shell (since 0.19.4, before only known ones), skill:<area> for known ones,
    host:<target> for ssh and for host names after ansible -l/--limit."""
    outputs = []
    for b in _commands(cli_command or ""):
        if b in COMMAND_SKILL:
            outputs += [f"skill:{COMMAND_SKILL[b]}", f"thema:{b}"]
        elif b not in SHELL_EVERYDAY and re.fullmatch(r"[a-z][a-z0-9._+-]{1,40}", b):
            outputs.append(f"thema:{b}")
    outputs += [f"host:{h.lower()}" for h in _SSH_TARGET.findall(cli_command or "")]
    for target in _ANSIBLE_LIMIT.findall(cli_command or ""):
        outputs += [f"host:{h.lower()}" for h in re.split(r"[:,]", target.strip("'\"")) if "." in h and not h.startswith(("!", "&", "~"))]
    return outputs


def triggers(tool: str, args: dict, context: list[str] | None = None) -> list[str]:
    """Hint triggers of an action: tool, skill (prefix up to the first _), host from the arguments, for shell tools the
    recognised commands and SSH targets, plus the client's context hashtags (what it is working on, e.g. thema:oom). Invalid hashtags are dropped."""
    r = [f"tool:{tool}", f"skill:{tool.split('_')[0]}"]
    for k, v in (args or {}).items():
        if k in HOSTKEYS and isinstance(v, str) and v.strip():
            r.append(f"host:{v.strip().lower()}")
    if tool in SHELL_TOOLS:
        r += command_triggers(str((args or {}).get("command") or (args or {}).get("cmd") or ""))
    r += [t.strip() for t in (context or []) if isinstance(t, str) and not t.startswith(g.ADMIN_PREFIXES)]
    return list(dict.fromkeys(t for t in r if g.TAG.match(t)))


def error_signature(text: str) -> str:
    return re.sub(r"[0-9a-f]{8,}|\d+", "#", (text or "")[:160])


def _question(tool: str, args: dict) -> str:
    return g.hash_value(tool, json.dumps(args, sort_keys=True, ensure_ascii=False))


def before(tool: str, args: dict, instance: str | None = None, is_read_only: bool | None = None,
           context: list[str] | None = None) -> dict:
    args, hints = reflexes.before(tool, dict(args or {}))
    from . import questions, self_model, session  # late: they use memory like we do
    hints += questions.deliver(instance)
    s = session.current()
    if s is not None:  # repeat the self every REPEAT_PER actions (persona drift, Li et al. 2024)
        s.actions += 1
        if s.actions % self_model.REPEAT_PER == 0:
            hints.append(self_model.hint())
    rz = triggers(tool, args, context)
    from . import learning as _learning
    warn = _learning.warning(rz)  # 0.20.8: router model detects risky situations; only with a counted reason
    if warn:
        hints.append(warn)
    search_triggers = rz
    found, search, from_memory = [], [], []
    # No access() on automatic showing: what is shown would otherwise become more important just by being shown (self-confirmation,
    # Matthew effect). Reinforcement happens in after(), if the action then succeeded — assumption "the hint helped",
    # named in docs/ARCHITECTURE.md; observation point: vi_experience (success with/without hints).
    # Candidates (heuristic: recency + importance + bonus), then possibly the router model (learned lift), then exploration
    from . import bandit, learning
    import random as _random
    cand = [o for _, o, _g in g.recall("(" + " OR ".join(search_triggers) + ")", limit=HINT_BUDGET + 24, kinds=("erkenntnis", "regel", "skill", "bild", "seite"))]
    # 0.21.1: disputed items and unconfirmed language-model hypotheses only on request (vi_recall), not unasked before actions.
    # Measured 09.11.: a disputed sleep hypothesis was the most shown hint with 719 reinforcements and pushed out evidenced knowledge.
    only_on_request = [o for o in cand if o.mode == "strittig" or ("herkunft:schlaf-llm" in o.hashtags and not o.foreign_confirmations())]
    cand = [o for o in cand if o not in only_on_request]
    from . import p2p  # sources that proved harmful are no longer shown
    cand = p2p.without_blocked(cand)
    router = "heuristik"
    m = learning.active()
    if m is not None and cand:
        rank_pos = dict(learning.ranking(m, search_triggers, [o.id for o in cand]))
        cand.sort(key=lambda o: -rank_pos.get(o.id, 0.0))
        router = "modell"
    elif bandit.has_counter(cand):  # stage 2: Thompson sampling as soon as any candidate has been rated
        cand = bandit.arrange(cand)
        router = "bandit"
    # Fit first, then learned usefulness: a new, exactly matching rule has no history yet and would otherwise lose against
    # established general hints. Importance 3 (warning) goes first. Tool triggers of a shell say nothing specific.
    general = ({f"tool:{tool}", f"skill:{tool.split('_')[0]}", "thema:ssh"} | {f"thema:{w}" for w in GENERIC_SHELL_WORDS}) \
        if tool in SHELL_TOOLS else set()  # ssh is only the transport; grep, sed, from, def … say nothing about the subject
    matching = set(search_triggers) - general
    cand.sort(key=lambda o: (-(o.importance >= 3 and bool(matching & set(o.hashtags))), -len(matching & set(o.hashtags))))
    # 0.49.0: before a shell command a hint must share more than the tool and generic words — a host, a program, an error. Counted.
    unspecific = [o for o in cand if general and not (matching & set(o.hashtags))]
    cand = [o for o in cand if o not in unspecific]
    # 0.24.0: a hint already shown in this conversation within REPEAT_S is not shown again. Measured 09.11.: three objects made up
    # ~2,300 of 5,841 shown hints — the same ssh tip appeared before every shell command. Held back with a count, not silently.
    repeated = []
    if s is not None:
        recent = time.monotonic() - REPEAT_S
        repeated = [o for o in cand if s.shown.get(o.id, float("-inf")) > recent]
        cand = [o for o in cand if o not in repeated]
    # 0.49.0: at most DAILY_MAX times a day per instance, across conversations (process memory: a restart resets it). Counted.
    # Only hints without measured benefit: a warning (importance 3) or a hint whose bandit advantage is positive keeps its place —
    # the matched lift (11.11.2026) showed hints helping centralstation `analyse` by about +9 points, every analysis anew.
    capped = []
    if instance:
        from . import bandit
        now_s = time.time()

        def earned(o):
            ja, nein = bandit.counter(o)
            return o.importance >= 3 or ja > nein
        capped = [o for o in cand if not earned(o) and sum(1 for t in _daily.get((instance, o.id), []) if now_s - t < 86400) >= DAILY_MAX]
        cand = [o for o in cand if o not in capped]
    # never show surplus manual paragraphs regularly, only via exploration (so the bandit learns whether they help after all)
    surplus = {o.id for o in [o for o in cand if any(t in o.hashtags for t in LOOKUP)][LOOKUP_MAX:]}
    regular = [o for o in cand if o.id not in surplus]
    shown_obj = regular[:HINT_BUDGET]
    exploration = False
    rest = regular[HINT_BUDGET:] + [o for o in cand if o.id in surplus]
    if rest and _random.random() < learning.EPSILON:  # ε-exploration: one slot for a random candidate from further back
        shown_obj = shown_obj[:-1] + [_random.choice(rest)]
        exploration = True
    if s is not None:
        shown_at = time.monotonic()
        for o in shown_obj:
            s.shown[o.id] = shown_at
    if instance:
        for o in shown_obj:
            _daily.setdefault((instance, o.id), []).append(time.time())
            _daily[(instance, o.id)] = [t for t in _daily[(instance, o.id)] if time.time() - t < 86400]
        if len(_daily) > 50000:
            _daily.clear()
    for i, o in enumerate(shown_obj):
        found.append(o.id)
        provenance = f"from {o.instance}" + (f", confirmed by {o.foreign_confirmations()} independent line(s)" if o.foreign_confirmations() else "")
        ins = " (exploration)" if exploration and i == len(shown_obj) - 1 else ""
        if o.kind == "skill":
            from . import skills
            from_memory.append(f"{skills.line(o)}{ins} [{o.id}]")
            continue
        if o.kind == "bild":  # 0.37.0
            from . import images
            from_memory.append(f"Image{ins} [{o.id}] ({provenance}): {o.text[:300]} — {images.summary(o)}; vi_object {o.id} shows it "
                               f"[Source: {str(o.data.get('quelle', '—'))[:120]}]")
            continue
        if o.kind == "seite":  # 0.41.0: a network wiki page — reviewed, maintained by the network
            from_memory.append(f"Wiki page{ins} [{o.id}] ({provenance}): {o.text[:300]} — vi_page_read shows it "
                               f"[Source: {str(o.data.get('quelle', '—'))[:120]}]")
            continue
        from_memory.append(f"{'Learned' if o.kind == 'erkenntnis' else 'Rule'}{ins} [{o.id}] ({provenance}"
                               + (", DISPUTED — contradicted by another instance" if o.mode == "strittig" else "")
                               + f"; {', '.join(t for t in o.hashtags if t.startswith(('modus:', 'skill:', 'kollektiv:')))[:60]}): "
                               f"{o.text[:300]} [Source: {str(o.data.get('quelle', '—'))[:120]}]"
                               + (f" [complete with code/tables: vi_object {o.id}]" if o.data.get("inhalt") else ""))
    candidate_ids = [o.id for o in cand]
    remaining = len(cand) - len(shown_obj)
    # 1. access to what was learned: searches whose hint triggers match the action run automatically
    for _, su, _g in g.recall("(" + " OR ".join(search_triggers) + ")", limit=3, kinds=("suche",)):
        hits = [o for _, o, _g2 in g.recall(su.data.get("filter", ""), limit=3) if o.id != su.id]
        found += [su.id] + [o.id for o in hits]
        search.append({"suche": su.id, "name": su.data.get("name"), "treffer": [o.id for o in hits]})
        from_memory.append(f"Learned search \"{su.data.get('name')}\" [{su.data.get('filter')}] — {su.text[:120]}: "
                               + ("; ".join(f"[{o.id}] {o.text[:90]}" for o in hits) if hits else "no hits"))
    # working memory: at most HINT_BUDGET hints from memory (Cowan 2001: ~4 chunks); the rest on request
    if len(from_memory) > HINT_BUDGET:
        remaining += len(from_memory) - HINT_BUDGET
        from_memory = from_memory[:HINT_BUDGET]
    if shown_obj and any(not h.startswith("Learned search") for h in from_memory):  # 0.49.0: ask for feedback where it costs least
        from_memory.append("Did one of these help or mislead you? vi_feedback(helped=[ids], wrong=[ids]) — one call, no reason needed")
    if remaining > 0 or only_on_request or repeated or unspecific or capped:
        addendum = f" (of which {len(only_on_request)} disputed or unconfirmed hypothesis, only on request)" if only_on_request else ""
        again = " · ".join(x for x in (f"{len(repeated)} already shown in this conversation within the last hour, not repeated" if repeated else "",
                                        f"{len(unspecific)} share only the tool or generic words, not shown" if unspecific else "",
                                        f"{len(capped)} shown {DAILY_MAX}× today already" if capped else "") if x)
        more = remaining + len(only_on_request)
        from_memory.append((f"… {more} more hits in memory{addendum}" + (f" · {again}" if again else "") if more else f"… {again}")
                           + f" — vi_drilldown(\"{' '.join(search_triggers)}\") shows them")
    hints += from_memory
    from . import archive
    hints += archive.hint(search_triggers)
    answer, age_s, ttl = None, None, None
    from .config import OPEN
    if read_only(tool, is_read_only) and instance != OPEN and not state_dependent(tool):  # without a token all share one instance: no remembered answers
        ttl = min(ttl_per_tool.get(tool, TTL_DEFAULT), TTL_MAX)
        for _, o, _g in g.recall(f"art:antwort cache:{_question(tool, args)}", limit=1, viewer=instance):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(o.ts)).total_seconds()
            if age <= ttl:
                found.append(o.id)
                answer, age_s = o.data.get("ergebnis", ""), int(age)
    access = {"reize": rz, "warnung": bool(warn), "gefunden": found, "gezeigt": [o.id for o in shown_obj], "kandidaten": candidate_ids,
               "router": router, "exploration": exploration, "rest_n": len(rest), "suchen": search, "aus_gedaechtnis": answer is not None,
               "repeat_suppressed": [o.id for o in repeated]}
    before_id = secrets.token_hex(8)
    if answer is not None:
        experience(tool, args, True, 0, None, answer, access, instance, is_read_only)
    else:
        close_open(only_older_than_s=OPEN_MAX_S)
        with _open_lock:
            _open[before_id] = (time.monotonic(), tool, args, access, instance, is_read_only, g.current_conversation.get())
    return {"vorher_id": before_id, "antwort": answer, "antwort_alter_s": age_s, "antwort_ttl_s": ttl,
            "args": args, "hinweise": hints, "zugriff": access}


#: 0.20.9: confirming/refuting a shown hint within this period counts as feedback on the action
FEEDBACK_MIN = 60
WHY_DAYS = 7


def _last_shown(instance: str, hint_id: str) -> tuple[str, str, dict, str] | None:
    """(time, tool, decision, where) of the instance's most recent decision that showed this hint: first the open ones (vi_before
    without vi_after yet — what was just shown), then the stored experiences of the last WHY_DAYS days."""
    with _open_lock:
        pending = [(t, tool, acc) for t, tool, _a, acc, inst, _ro, _c in _open.values() if inst == instance and hint_id in acc.get("gezeigt", [])]
    if pending:
        t, tool, acc = max(pending, key=lambda x: x[0])
        ts = (datetime.now(timezone.utc) - timedelta(seconds=time.monotonic() - t)).isoformat(timespec="seconds")
        return ts, tool, acc, "open action, not reported yet"
    since = (datetime.now(timezone.utc) - timedelta(days=WHY_DAYS)).isoformat(timespec="milliseconds")
    with g.lock:
        rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND instanz = ? AND zeit >= ? AND daten LIKE ? ORDER BY zeit DESC LIMIT 50",
                              (instance, since, f"%{hint_id}%")).fetchall()
    for (eid,) in rows:
        e = g.load(eid)
        if e and hint_id in ((e.data.get("vorher") or {}).get("gezeigt") or []):
            return e.ts, next((t[5:] for t in e.hashtags if t.startswith("tool:")), "?"), e.data["vorher"], f"experience {e.id}"
    return None


def explain(hint: g.MemoryObject, instance: str, triggers: list[str] | None = None) -> str:
    """0.29.0 (vi_why): why this hint was shown — from the stored decision (triggers, router, exploration), not reconstructed.
    With `triggers` it answers for that situation instead. Read only; the weights are read, never written."""
    from . import bandit, learning
    z = []
    e = None if triggers else _last_shown(instance, hint.id)
    ts = e[0] if e is not None else None
    if triggers is None and e is None:
        return (f"{hint.id} was not shown to {instance} in the last {WHY_DAYS} days — pass triggers (e.g. [\"tool:Bash\", \"host:web1\"]) "
                f"to ask for a situation")
    if e is not None:
        _ts, tool, v, where = e
        triggers, router = v.get("reize", []), v.get("router", "—")
        pos = v.get("gezeigt", []).index(hint.id) + 1
        z.append(f"Shown {ts[:16]} before {tool} ({where}), "
                 f"position {pos} of {len(v.get('gezeigt', []))}, router {router}"
                 + (" — this slot was ε-exploration (a random candidate from further back)" if v.get("exploration") and pos == len(v.get("gezeigt", [])) else ""))
    else:
        router = "modell" if learning.active() else "bandit" if bandit.has_counter([hint]) else "heuristik"
        z.append(f"Situation given: {', '.join(triggers)} · router now {router}")
    match = sorted(set(triggers) & set(hint.hashtags))
    z.append(f"  Fit: {len(match)} trigger(s) match the hint's hashtags" + (f" ({', '.join(match)})" if match else " — it came in through search or content, not a hashtag"))
    z.append(f"  Hint: {hint.kind} from {hint.instance}, mode {hint.mode}, importance {hint.importance}, confirmed by {hint.foreign_confirmations()} independent line(s)")
    z.append(f"  Measured usefulness: {bandit.line(hint)}")
    m = learning.model()
    if m is not None and m.data.get("gewichte"):
        w = learning.why(m, hint.id, triggers, ts)
        z.append(f"  Router model ({m.mode}, trained {str(m.data.get('trainiert', '—'))[:16]}; today's weights, the decision may have used an older version): "
                 f"P(ok) without hint {w['p_without'] * 100:.0f} %, with {w['p_with'] * 100:.0f} % → lift {w['lift'] * 100:+.1f} points")
        z.append(f"    what sets this hint apart from the other candidates (decides the order): {w['distinguishing_sum']:+.3f}")
        z += [f"      {k:44} {c:+.3f}" for k, c in w["distinguishing"][:8]] or ["      — none of its features is in the model"]
        z.append(f"    same for every candidate (moves all lifts alike, never the order): hinweis_n:1 − hinweis_n:0 = {w['same_for_all']:+.3f}")
        if w["hint_unknown"]:
            z.append(f"    not in the model (fewer than {learning.MIN_PER_FEATURE} observations): {', '.join(w['hint_unknown'][:6])}")
        if w["situation"]:
            z.append("    situation (raises or lowers P with and without the hint alike): "
                     + ", ".join(f"{k} {c:+.2f}" for k, c in w["situation"][:4]))
    else:
        z.append("  Router model: none yet — order by fit, importance and recency (heuristic) or measured usefulness (bandit)")
    return "\n".join(z)


def opened(instance: str, hint_id: str) -> str | None:
    """0.49.0: the AI opened a shown hint with vi_object — a weak signal of use, kept apart from feedback (not a training label)."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=FEEDBACK_MIN)).isoformat(timespec="milliseconds")
    with g.lock:
        rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND instanz = ? AND zeit >= ? ORDER BY zeit DESC LIMIT 200",
                              (instance, since)).fetchall()
    for (eid,) in rows:
        e = g.load(eid)
        if e and hint_id in ((e.data.get("vorher") or {}).get("gezeigt") or []):
            if not (e.data.get("geoeffnet") or {}).get(hint_id):
                e.data.setdefault("geoeffnet", {})[hint_id] = 1
                g.save(e)
            return eid
    return None


def feedback(instance: str, hint_id: str, value: int) -> str | None:
    """Assigns a vi_confirm (+1) / vi_refute (−1) to this instance's most recent action before which exactly this hint was shown
    (at most FEEDBACK_MIN minutes back). Returns the id of the experience or None (then it stays a normal confirmation)."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=FEEDBACK_MIN)).isoformat(timespec="milliseconds")
    with g.lock:
        rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND instanz = ? AND zeit >= ? ORDER BY zeit DESC LIMIT 200",
                              (instance, since)).fetchall()
    for (eid,) in rows:
        e = g.load(eid)
        if e and hint_id in ((e.data.get("vorher") or {}).get("gezeigt") or []):
            e.data.setdefault("rueckmeldung", {})[hint_id] = 1 if value > 0 else -1
            e.change(f"ki@{instance}", "feedback on the hint", f"{hint_id}: {'helped' if value > 0 else 'was wrong'}")
            g.save(e)
            return eid
    return None


def after(tool: str, args: dict, ok: bool, duration_ms: int, error: str | None, result: str | None,
            before_id: str | None = None, instance: str | None = None, is_read_only: bool | None = None) -> dict:
    with _open_lock:
        open_ = _open.pop(before_id, None) if before_id else None
    access = open_[3] if open_ else {"reize": triggers(tool, args or {}), "gefunden": [], "suchen": [],
                                      "aus_gedaechtnis": False, "ohne_vorher": True}
    o = experience(tool, args or {}, ok, duration_ms, error, result, access, instance, is_read_only)
    from . import bandit
    rated = bandit.book_entry(access.get("gezeigt", []), ok, tool)  # counter pair per shown hint (stage 2)
    reinforced = 0
    if ok:  # hints after which the action succeeded are reinforced (consolidation) — not already when shown
        for oid in access.get("gefunden", []):
            if not oid.startswith("antwort:"):
                h = g.load(oid)
                if h:
                    h.access()
                    reinforced += 1
    hints = reflexes.after(tool, dict(args or {}), result or "") if ok else []
    if ok is not None:  # a rated action is a new observation for router and bandit
        from . import on_demand
        on_demand.nudge("experience")
    return {"erfahrung": o.id, "hinweise": hints, "vorher_gefunden": bool(open_), "verstaerkt": reinforced, "bewertet": rated}


def close_open(conversation: str | None = None, only_older_than_s: float | None = None) -> int:
    """before without after → experience with ok:unbekannt (named state instead of silent vanishing).
    Choice: all of one conversation (at session end) or all older than only_older_than_s."""
    with _open_lock:
        if conversation is not None:
            ids = [k for k, v in _open.items() if v[6] == conversation]
        else:
            bound = time.monotonic() - (only_older_than_s or 0)
            ids = [k for k, v in _open.items() if v[0] < bound]
        cases = [_open.pop(k) for k in ids]
    for _t0, tool, args, access, instance, is_read_only, serial in cases:
        tok = g.current_conversation.set(serial)
        try:
            experience(tool, args, None, 0, None, None, {**access, "ohne_nachher": True}, instance, is_read_only)
        finally:
            g.current_conversation.reset(tok)
    return len(cases)


#: Surprise (prediction error as learning signal, docs/FORSCHUNG.md A7): level → importance. Exhaustive.
SURPRISE = {"neu": 3, "wiederholt": 2, "erholt": 2, "chronisch": 1, "keine": 0, "unbekannt": 0}


def surprise(tool: str, ok: bool | None, error_sig: str | None) -> tuple[str, str]:
    """(level, reason). First error of this kind in 24 h = neu; 2nd–3rd = wiederholt; from the 4th = chronisch;
    success after errors of the same tool = erholt; otherwise keine. Counts across all instances (server view)."""
    if ok is None:
        return "unbekannt", "no result reported"
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with g.lock:
        if not ok and error_sig:
            n = g.db().execute("SELECT COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? "
                               "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = ? WHERE o.art = 'erfahrung' AND o.zeit >= ?",
                               (f"tool:{tool}", f"fehler:{error_sig}", since)).fetchone()[0]
            if n == 0:
                return "neu", "first error of this kind in 24 h"
            if n <= 2:
                return "wiederholt", f"same error #{n + 1} in 24 h"
            return "chronisch", f"same error #{n + 1} in 24 h — known, no longer surprising"
        if ok:
            n = g.db().execute("SELECT COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? "
                               "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = 'ok:nein' WHERE o.art = 'erfahrung' AND o.zeit >= ?",
                               (f"tool:{tool}", since)).fetchone()[0]
            if n:
                return "erholt", f"success after {n} error(s) of the same tool in 24 h"
    return "keine", "expected outcome"


def experience(tool: str, args: dict, ok: bool | None, duration_ms: int, error: str | None, result: str | None,
              access: dict, instance: str | None = None, is_read_only: bool | None = None) -> g.MemoryObject:
    tags = [f"tool:{tool}", f"skill:{tool.split('_')[0]}", f"ok:{'unbekannt' if ok is None else 'ja' if ok else 'nein'}"]
    tags += [t for t in access.get("reize", []) if t.startswith(("host:", "thema:"))]  # context triggers as tags (TRAINING.md 4a)
    sig = None
    if error:
        sig = error_signature(error)[:60].replace(" ", "_").replace("(", "_").replace(")", "_")
        if g.TAG.match(f"fehler:{sig}"):
            tags.append(f"fehler:{sig}")
        else:
            sig = None
    level, reason_u = surprise(tool, ok, sig)  # count BEFORE saving, otherwise the experience counts itself
    tags.append(f"ueberraschung:{level}")
    tags = [t for t in tags if g.TAG.match(t)]
    text = f"{tool}({json.dumps(args, ensure_ascii=False)[:300]}) → " + (f"error: {error[:300]}" if error else "no result reported (vi_after missing)" if ok is None
                                                                       else f"ok, {len(result or '')} chars, {duration_ms} ms")
    o = g.new_object("erfahrung", text, tags, {"args": args, "dauer_ms": duration_ms, "fehler": error, "vorher": access,
                                                  "ueberraschung": {"stufe": level, "grund": reason_u}},
                       importance=SURPRISE[level], reason=f"tool call · surprise {level}: {reason_u}", instance=instance)
    for oid in access.get("gefunden", []):
        o.link(oid, "recalled before the action")
    from .config import OPEN
    if (ok and result is not None and read_only(tool, is_read_only) and not access.get("aus_gedaechtnis") and len(result) <= 200_000
            and instance != OPEN and not state_dependent(tool)):
        fh = _question(tool, args)
        with g.lock:
            # replace only the own remembered answer — the cache is private per instance
            old = [r[0] for r in g.db().execute("SELECT t.objekt_id FROM tag t JOIN objekt o ON o.id = t.objekt_id "
                                                "WHERE t.tag = ? AND o.instanz = ?", (f"cache:{fh}", o.instance))]
        g.delete(old)
        g.new_object("antwort", text, [f"tool:{tool}", f"cache:{fh}"], {"ergebnis": result, "args": args},
                       importance=0, reason="answer remembered", instance=instance)
    from . import session  # late: session does not know intuition
    s = session.current()
    if s:
        s.turn({"zeit": g.now(), "tool": tool, "args": args, "ok": ok, "dauer_ms": duration_ms, "fehler": error,
               "vorher": access, "erfahrung": o.id})
    return o


# ---- 0.44.0: memory for every user prompt (hook UserPromptSubmit in Claude Code, pre_llm_call in Hermes) ----
# Measured 11.11.2026 in CentralStation: the AI searched the VI in 4 of 10 first turns, in 2 of 80 follow-up turns. The tool hook
# searches by the tool, not by the topic of the question; this searches by the question. The prompt is not stored (usage keeps tool,
# outcome, duration and hit count only); hits are not reinforced (an automatic look is no use).
PROMPT_HINTS = 4
PROMPT_KINDS = ("erkenntnis", "regel", "skill", "suche", "bild", "seite")
_STOP = set("""der die das den dem des ein eine einen einem einer und oder aber nicht noch auch nur wie was wer wo wann warum wieso
weshalb ist sind war waren wird werden wurde hat haben hatte kann können konnte muss müssen soll sollen mit ohne für von vom zum zur
bei beim auf aus nach über unter vor hinter neben zwischen durch gegen ich du er sie es wir ihr mich mir dich dir uns euch sich mein
dein sein unser euer ihre ihren ihrem ihres dieser diese dieses jetzt dann schon mal bitte danke gibt geht machen mache macht sag sage
the and or but not also only how what who where when why is are was were will would can could must should with without for from
into onto about over under before after this that these those there here have has had please thanks you your we our they them it
its just then than does did done make made get got let lets""".split())
_WORD = re.compile(r"[\wäöüÄÖÜß][\wäöüÄÖÜß.:/_-]{2,}")


def prompt_words(text: str) -> list[str]:
    """Pure. The words of a prompt worth searching for: no stop words, no pure numbers, at most 20, in order."""
    out, seen = [], set()
    for whole in _WORD.findall(text or ""):
        whole = whole.strip(".:/-_")
        # compounds count whole and in parts: "ssh-Verbindung" also finds "ssh" (measured 11.11.2026 with Claude Code: missed otherwise)
        parts = [whole] + ([p for p in re.split(r"[-/_]", whole) if p] if re.search(r"[-/_]", whole) and not _specific(whole) else [])
        for w in parts:
            lw = w.lower()
            if len(lw) < 3 or lw in _STOP or lw.isdigit() or lw in seen:
                continue
            seen.add(lw)
            out.append(w)
    return out[:20]


def _specific(w: str) -> bool:
    """An identifier rather than a word: a host or file name, an error code with letters and digits."""
    return bool(re.search(r"\d", w) and re.search(r"[a-zA-Z]", w)) or "." in w.strip(".")


def prompt_hints(text: str, instance: str | None, shown: list[str] | None = None) -> dict:
    """Hints for a user prompt: knowledge whose text or hashtags share at least two of its words (one if it has only one)."""
    from . import p2p
    words = prompt_words(text)
    if not words:
        return {"hinweise": [], "woerter": 0}
    need = 2  # an identifier (host name, error code) or a hashtag value counts 2, another shared word 1
    skip = set(shown or [])
    hits = g.recall(" ".join(words), limit=PROMPT_HINTS * 6, kinds=PROMPT_KINDS, viewer=instance, or_fallback=True)
    cand = [o for _s, o, _g in hits if o.id not in skip and o.mode not in ("strittig", "quarantaene", "widerlegt", "archiviert")
            and not ("herkunft:schlaf-llm" in o.hashtags and not o.foreign_confirmations())]
    cand = p2p.without_blocked(cand)
    lw = [w.lower() for w in words]
    scored = []
    for rank, o in enumerate(cand):
        hay = (o.text + " " + " ".join(o.hashtags)).lower()
        values = {t.split(":", 1)[1].lower() for t in o.hashtags if ":" in t}
        score = sum((2 if (_specific(w) or w in values) else 1) for w in lw if w in hay)
        if score >= (1 if len(words) == 1 else need):
            scored.append((-score, rank, o))
    # 0.44.1: most shared words first (measured on production: a note sharing only the host name came before the one that answered
    # "warum stirbt das große Modell auf <host> mit Exit 137"); the full-text rank breaks ties. A host name alone is enough only if
    # nothing shares more.
    best = -min((s for s, _r, _o in scored), default=0)
    out = []
    for s, _rank, o in sorted(scored, key=lambda x: (x[0], x[1])):
        if -s < best and -s <= 2:
            continue
        provenance = f"from {o.instance}" if o.instance else "from the server"
        label = {"regel": "Rule", "skill": "Skill", "bild": "Image", "seite": "Wiki page", "suche": "Search"}.get(o.kind, "Learned")
        out.append({"id": o.id, "zeile": f"{label} [{o.id}] ({provenance}): {o.text[:300]} — vi_object {o.id} for the complete content "
                                         f"[Source: {str(o.data.get('quelle', '—'))[:120]}]"})
        if len(out) >= PROMPT_HINTS:
            break
    return {"hinweise": [h["zeile"] for h in out], "ids": [h["id"] for h in out], "woerter": len(words)}

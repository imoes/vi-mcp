"""Intuition — der automatische Gedächtniszugriff vor und das Lernen nach jeder Handlung.

Die VI handelt nie selbst in der Welt (kein Werkzeugaufruf, kein Schreiben außerhalb des Gedächtnisses); im
Gedächtnis handelt sie (Loop: Regeln, Ablauf), jede Handlung mit Grund in der Geschichte. Ein Client (Agent, Skill-Server, Hook) meldet eine Handlung zweimal:
  vorher(tool, args)   → gemerkte Antwort (wenn lesend und frisch), Hinweise (Erkenntnisse, Regeln, gelernte
                         Suchen, Vorher-Reflexe), evtl. von einem aktiven Reflex geänderte Argumente.
                         Der Zugriff selbst wird gespeichert (Erfahrung.daten.vorher: Reize, Gefundenes).
  nachher(...)         → Erfahrung (ok/Fehler, Dauer), gemerkte Antwort (wenn lesend), Nachher-Reflexe.
Bewusstsein = Erkenntnisse/Regeln (Hinweise), Unterbewusstsein = gemerkte Antworten/Reflexe.
Grenze: schreibende Werkzeuge werden nie aus dem Gedächtnis beantwortet.
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

#: Werkzeuge, die etwas verändern (Wortteile im Namen) — nie aus dem Gedächtnis beantwortet. Ein Client kann
#: `lesend` ausdrücklich angeben; dann gilt seine Angabe, nicht das Namensmuster.
WRITING = re.compile(r"(create|add|update|launch|acknowledge|push|transition|assign|send|click|run_|type_text|"
                        r"schedule|delete|link|comment|modify|set_|_auth_|login|logout|focus|foreground|move_|write|edit|"
                        r"activate|bake|discovery|downtime|reschedule|refresh|vergiss|lerne|markiere|bestaetige|widerlege)", re.I)
TTL_DEFAULT = 120
#: 0.21.2: Werkzeuge, deren Ergebnis vom Zustand außerhalb abhängt (Browser, Warten, Live-Zustand), werden nie gemerkt und nie aus dem
#: Gedächtnis beantwortet — gleiche Argumente heißen dort nicht gleicher Zustand. Gemeldet von CentralStation am 09.11. ~12:54 UTC:
#: browser_wait_for(time=5) bekam die gemerkte Antwort von vor 53 s mit einer anderen Seiten-URL, statt zu warten.
STATE_DEPENDENT = re.compile(r"(^|_)(browser|playwright|wait|wait_for|sleep|snapshot|screenshot|evaluate|console|network_requests?|"
                               r"tabs|navigate|health|ping|now|uhrzeit|live)(_|$)", re.I)


def state_dependent(tool: str) -> bool:
    return bool(STATE_DEPENDENT.search(tool or ""))
TTL_MAX = 3600
HINT_BUDGET = 4
#: Nachschlagewerk (importierte Herstellerdoku): wird gesucht, aber vor einer Handlung höchstens NACHSCHLAG_MAX-mal ungefragt gezeigt,
#: damit Handbuch-Absätze nicht das Erfahrungswissen (Warnungen, Fallstricke) aus dem Budget drängen. Gemessen 09.11.2026: vor `docker logs`
#: belegten vier allgemeine Docker-Doku-Absätze alle Plätze.
LOOKUP = ("art_wissen:doku-extern",)
LOOKUP_MAX = 1
HOSTKEYS = ("host", "hostname", "host_name", "node", "device")
OPEN_MAX_S = 3600

ttl_per_tool: dict[str, int] = {}
#: vorher-Zugriffe, die auf ihr nachher warten: {vorher_id: (zeitpunkt, tool, args, zugriff, instanz, lesend, gespraech)}.
#: Kommt kein nachher, wird der Zugriff nicht still verworfen, sondern als Erfahrung mit `ok:unbekannt` gespeichert
#: (beim Ende des Gesprächs oder nach OFFEN_MAX_S) — siehe offene_abschliessen().
_open: dict[str, tuple] = {}
_open_lock = threading.Lock()


def read_only(tool: str, given: bool | None = None) -> bool:
    return given if isinstance(given, bool) else not WRITING.search(tool)


#: Befehle in einer Kommandozeile → Skill, damit Wissen zu Proxmox, Ansible, Docker, PostgreSQL vor dem passenden Shell-Befehl erscheint
COMMAND_SKILL = {**dict.fromkeys(("vzdump", "qm", "pct", "pvecm", "pvesm", "pveceph", "ha-manager", "pvesh", "pveum", "pvesr", "pvenode", "pve-firewall", "qmrestore", "pct-restore"), "proxmox"),
                **dict.fromkeys(("ansible", "ansible-playbook", "ansible-vault", "ansible-inventory", "ansible-galaxy", "ansible-doc", "ansible-config"), "ansible"),
                **dict.fromkeys(("docker", "docker-compose", "dockerd"), "docker"),
                **dict.fromkeys(("psql", "pg_dump", "pg_dumpall", "pg_basebackup", "pg_restore", "pg_ctl", "pg_upgrade", "pg_ctlcluster", "pg_lsclusters", "vacuumdb", "pg_isready"), "postgres")}
SHELL_TOOLS = ("Bash", "bash", "shell", "terminal", "exec", "run_command", "windows_run_powershell")
_CMD_SPLIT = re.compile(r"[;&|()`\n]|\$\(|['\"]")
_PREFIX_COMMANDS = frozenset(("sudo", "exec", "nohup", "time", "env", "timeout", "setsid", "nice", "ionice", "stdbuf", "chronic"))  # seit 0.20.2: auch timeout, setsid, nice …
_SUDO_WITH_VALUE = {"-u", "-g", "-C", "-D", "-h", "-p", "-R", "-r", "-T"}
_SSH_TARGET = re.compile(r"\bssh\s+(?:-\S+(?:\s+\S+)?\s+)*(?:[\w.-]+@)?([a-z][\w.-]*[a-z0-9])", re.I)


_EXECUTES = re.compile(r"(?:\bssh\s+(?:-\S+(?:\s+\S+)?\s+)*\S+|\b(?:ba|z)?sh\s+-\w*c|\bsu\s+(?:-\s+)?(?:\S+\s+)?-c)\s*$")


def _subcommands(cli_command: str):
    """Teilbefehle der Kommandozeile. Text in Anführungszeichen ist nur dann ein Befehl, wenn er ausgeführt wird
    (ssh <ziel> '…', sh -c '…', su -c '…'); sonst ist er ein Argument (psql -c "select 1", python3 -c "…", grep 'muster') und wird übersprungen.
    Verschachtelt (seit 0.20.1): in ssh '… python3 -c "code" …' ist der innere Code kein Befehl — ein Stapel hält jede Ebene."""
    parts = re.split(r"([;&|()`\n]|\$\(|['\"])", cli_command)
    stack: list[tuple[str, bool]] = []  # (Anführungszeichen, wird ausgeführt)
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
                continuation = True  # nach dem schließenden Zeichen geht dasselbe Kommando weiter
            else:
                stack.append((separator, bool(_EXECUTES.search(before_text))))


def _commands(cli_command: str):
    """Das erste Wort jedes Teilbefehls, ohne Variablenzuweisungen und ohne sudo samt Optionen."""
    for part in _subcommands(cli_command):
        w = part.split()
        i = 0
        while i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
            i += 1
        while i < len(w) and w[i] in _PREFIX_COMMANDS:  # Vorsätze ohne eigene Aussage: der eigentliche Befehl steht dahinter
            prefix_cmd = w[i]
            i += 1
            while i < len(w) and w[i].startswith("-"):
                i += 2 if w[i] in _SUDO_WITH_VALUE or (prefix_cmd != "sudo" and w[i] in ("-n", "-s", "-k", "-c")) else 1
            if prefix_cmd == "timeout" and i < len(w):
                i += 1  # Dauer
            while prefix_cmd == "env" and i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
                i += 1
        if i < len(w):
            yield w[i]


#: Shell-Handwerkszeug ohne fachliche Aussage: wird kein thema:-Reiz (sonst passte jede Notiz über grep zu jedem zweiten Befehl).
SHELL_EVERYDAY = frozenset("""cd ls ll echo printf cat less more head tail sort uniq wc tee true false test [ sleep export set unset source . pwd date
    which type command exec eval read wait yes column printenv exit return mkdir rmdir touch basename dirname realpath readlink
    bash sh zsh dash python python3 perl""".split())
#: Bewusst NICHT im Alltag (seit 0.20.2): grep, sed, awk, find, xargs, kill/pkill/pgrep, chmod/chown, cp/mv/ln, timeout, nohup, env, python …
#: Zu ihnen gibt es echte Fallstricke (pkill -f trifft die eigene Shell, sed -i, find -exec, chmod -R); eine Notiz mit thema:pkill muss erscheinen.
_ANSIBLE_LIMIT = re.compile(r"(?:^|\s)(?:-l|--limit)(?:\s+|=)(\S+)")


def command_triggers(cli_command: str) -> list[str]:
    """Rein. thema:<befehl> für jeden erkannten Befehl außer Shell-Alltag (seit 0.19.4, vorher nur bekannte), skill:<bereich> für bekannte,
    host:<ziel> für ssh und für Hostnamen hinter ansible -l/--limit."""
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
    """Hinweisreize einer Handlung: Werkzeug, Skill (Präfix bis zum ersten _), Host aus den Argumenten, bei Shell-Werkzeugen die
    erkannten Befehle und SSH-Ziele, dazu die Kontext-Hashtags des Clients (woran er gerade arbeitet, z. B. thema:oom). Ungültige Hashtags fallen weg."""
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
    from . import questions, self_model, session  # spät: nutzen gedaechtnis wie wir
    hints += questions.deliver(instance)
    s = session.current()
    if s is not None:  # Selbst alle WIEDERHOLUNG_JE Handlungen wiederholen (Persona-Drift, Li et al. 2024)
        s.actions += 1
        if s.actions % self_model.REPEAT_PER == 0:
            hints.append(self_model.hint())
    rz = triggers(tool, args, context)
    from . import learning as _learning
    warn = _learning.warning(rz)  # 0.20.8: Router-Modell erkennt riskante Lagen; nur mit gezählter Begründung
    if warn:
        hints.append(warn)
    search_triggers = rz
    found, search, from_memory = [], [], []
    # Kein zugriff() beim automatischen Zeigen: Gezeigtes würde sonst allein durchs Zeigen wichtiger (Selbstbestätigung,
    # Matthäus-Effekt). Verstärkt wird in nachher(), wenn die Handlung danach gelang — Annahme „der Hinweis hat genützt“,
    # benannt in docs/ARCHITEKTUR.md; Beobachtungspunkt: vi_erfahrung (Erfolg mit/ohne Hinweise).
    # Kandidaten (Heuristik: Aktualität + Wichtigkeit + Bonus), dann ggf. Router-Modell (gelernter Lift), dann Erkundung
    from . import bandit, learning
    import random as _random
    cand = [o for _, o, _g in g.recall("(" + " OR ".join(search_triggers) + ")", limit=HINT_BUDGET + 24, kinds=("erkenntnis", "regel", "skill"))]
    # 0.21.1: Strittiges und unbestätigte Sprachmodell-Hypothesen nur auf Nachfrage (vi_erinnere), nicht ungefragt vor Handlungen.
    # Gemessen 09.11.: eine strittige Schlaf-Hypothese war mit 719 Verstärkungen der meistgezeigte Hinweis und verdrängte belegtes Wissen.
    only_on_request = [o for o in cand if o.mode == "strittig" or ("herkunft:schlaf-llm" in o.hashtags and not o.foreign_confirmations())]
    cand = [o for o in cand if o not in only_on_request]
    from . import p2p  # Quellen, die sich als schädlich erwiesen haben, werden nicht mehr gezeigt
    cand = p2p.without_blocked(cand)
    router = "heuristik"
    m = learning.active()
    if m is not None and cand:
        rank_pos = dict(learning.ranking(m, search_triggers, [o.id for o in cand]))
        cand.sort(key=lambda o: -rank_pos.get(o.id, 0.0))
        router = "modell"
    elif bandit.has_counter(cand):  # Stufe 2: Thompson Sampling, sobald irgendein Kandidat bewertet wurde
        cand = bandit.arrange(cand)
        router = "bandit"
    # Erst Passung, dann gelernter Nutzen: Eine neue, genau passende Regel hat noch keine Geschichte und verlöre sonst gegen
    # eingespielte allgemeine Hinweise. Wichtigkeit 3 (Warnung) geht vor. Werkzeug-Reize einer Shell sagen nichts Spezifisches.
    general = {f"tool:{tool}", f"skill:{tool.split('_')[0]}", "thema:ssh"} if tool in SHELL_TOOLS else set()  # ssh ist nur der Transport
    matching = set(search_triggers) - general
    cand.sort(key=lambda o: (-(o.importance >= 3 and bool(matching & set(o.hashtags))), -len(matching & set(o.hashtags))))
    # Überzählige Handbuch-Absätze nie regulär zeigen, nur über die Erkundung (so lernt der Bandit, ob sie doch helfen)
    surplus = {o.id for o in [o for o in cand if any(t in o.hashtags for t in LOOKUP)][LOOKUP_MAX:]}
    regular = [o for o in cand if o.id not in surplus]
    shown_obj = regular[:HINT_BUDGET]
    exploration = False
    rest = regular[HINT_BUDGET:] + [o for o in cand if o.id in surplus]
    if rest and _random.random() < learning.EPSILON:  # ε-Erkundung: ein Platz für einen zufälligen Kandidaten von weiter hinten
        shown_obj = shown_obj[:-1] + [_random.choice(rest)]
        exploration = True
    for i, o in enumerate(shown_obj):
        found.append(o.id)
        provenance = f"von {o.instance}" + (f", bestätigt von {o.foreign_confirmations()} weiteren Instanz(en)" if o.foreign_confirmations() else "")
        ins = " (Erkundung)" if exploration and i == len(shown_obj) - 1 else ""
        if o.kind == "skill":
            from . import skills
            from_memory.append(f"{skills.line(o)}{ins} [{o.id}]")
            continue
        from_memory.append(f"{'Gelernt' if o.kind == 'erkenntnis' else 'Regel'}{ins} [{o.id}] ({provenance}"
                               + (", STRITTIG — von einer anderen Instanz widersprochen" if o.mode == "strittig" else "")
                               + f"; {', '.join(t for t in o.hashtags if t.startswith(('modus:', 'skill:', 'kollektiv:')))[:60]}): "
                               f"{o.text[:300]} [Quelle: {str(o.data.get('quelle', '—'))[:120]}]"
                               + (f" [vollständig mit Code/Tabellen: vi_objekt {o.id}]" if o.data.get("inhalt") else ""))
    candidate_ids = [o.id for o in cand]
    remaining = len(cand) - len(shown_obj)
    # 1. Zugriff auf Gelerntes: Suchen, deren Hinweisreize zur Handlung passen, laufen automatisch
    for _, su, _g in g.recall("(" + " OR ".join(search_triggers) + ")", limit=3, kinds=("suche",)):
        hits = [o for _, o, _g2 in g.recall(su.data.get("filter", ""), limit=3) if o.id != su.id]
        found += [su.id] + [o.id for o in hits]
        search.append({"suche": su.id, "name": su.data.get("name"), "treffer": [o.id for o in hits]})
        from_memory.append(f"Gelernte Suche „{su.data.get('name')}“ [{su.data.get('filter')}] — {su.text[:120]}: "
                               + ("; ".join(f"[{o.id}] {o.text[:90]}" for o in hits) if hits else "keine Treffer"))
    # Arbeitsgedächtnis: höchstens HINWEIS_BUDGET Hinweise aus dem Gedächtnis (Cowan 2001: ~4 Chunks); der Rest auf Abruf
    if len(from_memory) > HINT_BUDGET:
        remaining += len(from_memory) - HINT_BUDGET
        from_memory = from_memory[:HINT_BUDGET]
    if remaining > 0 or only_on_request:
        addendum = f" (davon {len(only_on_request)} strittig oder unbestätigte Hypothese, nur auf Nachfrage)" if only_on_request else ""
        from_memory.append(f"… {remaining + len(only_on_request)} weitere Treffer im Gedächtnis{addendum} — vi_vertiefe(\"{' '.join(search_triggers)}\") zeigt sie")
    hints += from_memory
    from . import archive
    hints += archive.hint(search_triggers)
    answer, age_s, ttl = None, None, None
    from .config import OPEN
    if read_only(tool, is_read_only) and instance != OPEN and not state_dependent(tool):  # ohne Token teilen sich alle eine Instanz: keine gemerkten Antworten
        ttl = min(ttl_per_tool.get(tool, TTL_DEFAULT), TTL_MAX)
        for _, o, _g in g.recall(f"art:antwort cache:{_question(tool, args)}", limit=1, viewer=instance):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(o.ts)).total_seconds()
            if age <= ttl:
                found.append(o.id)
                answer, age_s = o.data.get("ergebnis", ""), int(age)
    access = {"reize": rz, "warnung": bool(warn), "gefunden": found, "gezeigt": [o.id for o in shown_obj], "kandidaten": candidate_ids,
               "router": router, "exploration": exploration, "suchen": search, "aus_gedaechtnis": answer is not None}
    before_id = secrets.token_hex(8)
    if answer is not None:
        experience(tool, args, True, 0, None, answer, access, instance, is_read_only)
    else:
        close_open(only_older_than_s=OPEN_MAX_S)
        with _open_lock:
            _open[before_id] = (time.monotonic(), tool, args, access, instance, is_read_only, g.current_conversation.get())
    return {"vorher_id": before_id, "antwort": answer, "antwort_alter_s": age_s, "antwort_ttl_s": ttl,
            "args": args, "hinweise": hints, "zugriff": access}


#: 0.20.9: Bestätigen/Widerlegen eines gezeigten Hinweises innerhalb dieses Zeitraums zählt als Rückmeldung zu der Handlung
FEEDBACK_MIN = 60


def feedback(instance: str, hint_id: str, value: int) -> str | None:
    """Ordnet ein vi_bestaetige (+1) / vi_widerlege (−1) der jüngsten Handlung dieser Instanz zu, vor der genau dieser Hinweis gezeigt
    wurde (höchstens RUECKMELDUNG_MIN Minuten zurück). Liefert die Id der Erfahrung oder None (dann bleibt es eine normale Bestätigung)."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=FEEDBACK_MIN)).isoformat(timespec="milliseconds")
    with g.lock:
        rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND instanz = ? AND zeit >= ? ORDER BY zeit DESC LIMIT 200",
                              (instance, since)).fetchall()
    for (eid,) in rows:
        e = g.load(eid)
        if e and hint_id in ((e.data.get("vorher") or {}).get("gezeigt") or []):
            e.data.setdefault("rueckmeldung", {})[hint_id] = 1 if value > 0 else -1
            e.change(f"ki@{instance}", "Rückmeldung zum Hinweis", f"{hint_id}: {'half' if value > 0 else 'war falsch'}")
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
    rated = bandit.book_entry(access.get("gezeigt", []), ok, tool)  # Zählerpaar je gezeigtem Hinweis (Stufe 2)
    reinforced = 0
    if ok:  # Hinweise, nach denen die Handlung gelang, werden verstärkt (Konsolidierung) — nicht schon beim Zeigen
        for oid in access.get("gefunden", []):
            if not oid.startswith("antwort:"):
                h = g.load(oid)
                if h:
                    h.access()
                    reinforced += 1
    hints = reflexes.after(tool, dict(args or {}), result or "") if ok else []
    if ok is not None:  # eine bewertete Handlung ist eine neue Beobachtung für Router und Bandit
        from . import on_demand
        on_demand.nudge("Erfahrung")
    return {"erfahrung": o.id, "hinweise": hints, "vorher_gefunden": bool(open_), "verstaerkt": reinforced, "bewertet": rated}


def close_open(conversation: str | None = None, only_older_than_s: float | None = None) -> int:
    """vorher ohne nachher → Erfahrung mit ok:unbekannt (benannter Zustand statt stillem Verschwinden).
    Wahl: alle eines Gesprächs (beim Sitzungsende) oder alle älter als nur_aelter_als_s."""
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


#: Überraschung (Vorhersagefehler als Lernsignal, docs/FORSCHUNG.md A7): Stufe → Wichtigkeit. Erschöpfend.
SURPRISE = {"neu": 3, "wiederholt": 2, "erholt": 2, "chronisch": 1, "keine": 0, "unbekannt": 0}


def surprise(tool: str, ok: bool | None, error_sig: str | None) -> tuple[str, str]:
    """(Stufe, Grund). Erster Fehler dieser Art in 24 h = neu; 2.–3. = wiederholt; ab dem 4. = chronisch;
    Erfolg nach Fehlern desselben Werkzeugs = erholt; sonst keine. Zählt über alle Instanzen (Server-Sicht)."""
    if ok is None:
        return "unbekannt", "kein Ergebnis gemeldet"
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with g.lock:
        if not ok and error_sig:
            n = g.db().execute("SELECT COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? "
                               "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = ? WHERE o.art = 'erfahrung' AND o.zeit >= ?",
                               (f"tool:{tool}", f"fehler:{error_sig}", since)).fetchone()[0]
            if n == 0:
                return "neu", "erster Fehler dieser Art in 24 h"
            if n <= 2:
                return "wiederholt", f"{n + 1}. gleicher Fehler in 24 h"
            return "chronisch", f"{n + 1}. gleicher Fehler in 24 h — bekannt, nicht mehr überraschend"
        if ok:
            n = g.db().execute("SELECT COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? "
                               "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = 'ok:nein' WHERE o.art = 'erfahrung' AND o.zeit >= ?",
                               (f"tool:{tool}", since)).fetchone()[0]
            if n:
                return "erholt", f"Erfolg nach {n} Fehler(n) desselben Werkzeugs in 24 h"
    return "keine", "erwarteter Ausgang"


def experience(tool: str, args: dict, ok: bool | None, duration_ms: int, error: str | None, result: str | None,
              access: dict, instance: str | None = None, is_read_only: bool | None = None) -> g.MemoryObject:
    tags = [f"tool:{tool}", f"skill:{tool.split('_')[0]}", f"ok:{'unbekannt' if ok is None else 'ja' if ok else 'nein'}"]
    tags += [t for t in access.get("reize", []) if t.startswith(("host:", "thema:"))]  # Kontext-Reize als Tags (TRAINING.md 4a)
    sig = None
    if error:
        sig = error_signature(error)[:60].replace(" ", "_").replace("(", "_").replace(")", "_")
        if g.TAG.match(f"fehler:{sig}"):
            tags.append(f"fehler:{sig}")
        else:
            sig = None
    level, reason_u = surprise(tool, ok, sig)  # VOR dem Speichern zählen, sonst zählt sich die Erfahrung selbst mit
    tags.append(f"ueberraschung:{level}")
    tags = [t for t in tags if g.TAG.match(t)]
    text = f"{tool}({json.dumps(args, ensure_ascii=False)[:300]}) → " + (f"Fehler: {error[:300]}" if error else "kein Ergebnis gemeldet (vi_nachher fehlt)" if ok is None
                                                                       else f"ok, {len(result or '')} Zeichen, {duration_ms} ms")
    o = g.new_object("erfahrung", text, tags, {"args": args, "dauer_ms": duration_ms, "fehler": error, "vorher": access,
                                                  "ueberraschung": {"stufe": level, "grund": reason_u}},
                       importance=SURPRISE[level], reason=f"Werkzeugaufruf · Überraschung {level}: {reason_u}", instance=instance)
    for oid in access.get("gefunden", []):
        o.link(oid, "vor der Handlung erinnert")
    from .config import OPEN
    if (ok and result is not None and read_only(tool, is_read_only) and not access.get("aus_gedaechtnis") and len(result) <= 200_000
            and instance != OPEN and not state_dependent(tool)):
        fh = _question(tool, args)
        with g.lock:
            # nur die eigene gemerkte Antwort ersetzen — der Cache ist privat je Instanz
            old = [r[0] for r in g.db().execute("SELECT t.objekt_id FROM tag t JOIN objekt o ON o.id = t.objekt_id "
                                                "WHERE t.tag = ? AND o.instanz = ?", (f"cache:{fh}", o.instance))]
        g.delete(old)
        g.new_object("antwort", text, [f"tool:{tool}", f"cache:{fh}"], {"ergebnis": result, "args": args},
                       importance=0, reason="Antwort gemerkt", instance=instance)
    from . import session  # spät: sitzung kennt intuition nicht
    s = session.current()
    if s:
        s.turn({"zeit": g.now(), "tool": tool, "args": args, "ok": ok, "dauer_ms": duration_ms, "fehler": error,
               "vorher": access, "erfahrung": o.id})
    return o

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

from . import gedaechtnis as g
from . import reflexe

#: Werkzeuge, die etwas verändern (Wortteile im Namen) — nie aus dem Gedächtnis beantwortet. Ein Client kann
#: `lesend` ausdrücklich angeben; dann gilt seine Angabe, nicht das Namensmuster.
SCHREIBEND = re.compile(r"(create|add|update|launch|acknowledge|push|transition|assign|send|click|run_|type_text|"
                        r"schedule|delete|link|comment|modify|set_|_auth_|login|logout|focus|foreground|move_|write|edit|"
                        r"activate|bake|discovery|downtime|reschedule|refresh|vergiss|lerne|markiere|bestaetige|widerlege)", re.I)
TTL_STANDARD = 120
TTL_MAX = 3600
HINWEIS_BUDGET = 4
#: Nachschlagewerk (importierte Herstellerdoku): wird gesucht, aber vor einer Handlung höchstens NACHSCHLAG_MAX-mal ungefragt gezeigt,
#: damit Handbuch-Absätze nicht das Erfahrungswissen (Warnungen, Fallstricke) aus dem Budget drängen. Gemessen 09.11.2026: vor `docker logs`
#: belegten vier allgemeine Docker-Doku-Absätze alle Plätze.
NACHSCHLAG = ("art_wissen:doku-extern",)
NACHSCHLAG_MAX = 1
HOSTKEYS = ("host", "hostname", "host_name", "node", "device")
OFFEN_MAX_S = 3600

ttl_je_werkzeug: dict[str, int] = {}
#: vorher-Zugriffe, die auf ihr nachher warten: {vorher_id: (zeitpunkt, tool, args, zugriff, instanz, lesend, gespraech)}.
#: Kommt kein nachher, wird der Zugriff nicht still verworfen, sondern als Erfahrung mit `ok:unbekannt` gespeichert
#: (beim Ende des Gesprächs oder nach OFFEN_MAX_S) — siehe offene_abschliessen().
_offen: dict[str, tuple] = {}
_offen_sperre = threading.Lock()


def lesend(tool: str, angabe: bool | None = None) -> bool:
    return angabe if isinstance(angabe, bool) else not SCHREIBEND.search(tool)


#: Befehle in einer Kommandozeile → Skill, damit Wissen zu Proxmox, Ansible, Docker, PostgreSQL vor dem passenden Shell-Befehl erscheint
BEFEHL_SKILL = {**dict.fromkeys(("vzdump", "qm", "pct", "pvecm", "pvesm", "pveceph", "ha-manager", "pvesh", "pveum", "pvesr", "pvenode", "pve-firewall", "qmrestore", "pct-restore"), "proxmox"),
                **dict.fromkeys(("ansible", "ansible-playbook", "ansible-vault", "ansible-inventory", "ansible-galaxy", "ansible-doc", "ansible-config"), "ansible"),
                **dict.fromkeys(("docker", "docker-compose", "dockerd"), "docker"),
                **dict.fromkeys(("psql", "pg_dump", "pg_dumpall", "pg_basebackup", "pg_restore", "pg_ctl", "pg_upgrade", "pg_ctlcluster", "pg_lsclusters", "vacuumdb", "pg_isready"), "postgres")}
SHELL_WERKZEUGE = ("Bash", "bash", "shell", "terminal", "exec", "run_command", "windows_run_powershell")
_TRENNUNG = re.compile(r"[;&|()`\n]|\$\(|['\"]")
_VORSAETZE = frozenset(("sudo", "exec", "nohup", "time", "env", "timeout", "setsid", "nice", "ionice", "stdbuf", "chronic"))  # seit 0.20.2: auch timeout, setsid, nice …
_SUDO_MIT_WERT = {"-u", "-g", "-C", "-D", "-h", "-p", "-R", "-r", "-T"}
_SSH_ZIEL = re.compile(r"\bssh\s+(?:-\S+(?:\s+\S+)?\s+)*(?:[\w.-]+@)?([a-z][\w.-]*[a-z0-9])", re.I)


_FUEHRT_AUS = re.compile(r"(?:\bssh\s+(?:-\S+(?:\s+\S+)?\s+)*\S+|\b(?:ba|z)?sh\s+-\w*c|\bsu\s+(?:-\s+)?(?:\S+\s+)?-c)\s*$")


def _teilbefehle(kommando: str):
    """Teilbefehle der Kommandozeile. Text in Anführungszeichen ist nur dann ein Befehl, wenn er ausgeführt wird
    (ssh <ziel> '…', sh -c '…', su -c '…'); sonst ist er ein Argument (psql -c "select 1", python3 -c "…", grep 'muster') und wird übersprungen.
    Verschachtelt (seit 0.20.1): in ssh '… python3 -c "code" …' ist der innere Code kein Befehl — ein Stapel hält jede Ebene."""
    teile = re.split(r"([;&|()`\n]|\$\(|['\"])", kommando)
    stapel: list[tuple[str, bool]] = []  # (Anführungszeichen, wird ausgeführt)
    vorher_text, fortsetzung = "", False
    for i in range(0, len(teile), 2):
        text = teile[i]
        if all(ausf for _z, ausf in stapel) and not fortsetzung:
            yield text
        vorher_text = text
        trenner = teile[i + 1] if i + 1 < len(teile) else ""
        fortsetzung = False
        if trenner in ("'", '"'):
            if stapel and stapel[-1][0] == trenner:
                stapel.pop()
                fortsetzung = True  # nach dem schließenden Zeichen geht dasselbe Kommando weiter
            else:
                stapel.append((trenner, bool(_FUEHRT_AUS.search(vorher_text))))


def _befehle(kommando: str):
    """Das erste Wort jedes Teilbefehls, ohne Variablenzuweisungen und ohne sudo samt Optionen."""
    for teil in _teilbefehle(kommando):
        w = teil.split()
        i = 0
        while i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
            i += 1
        while i < len(w) and w[i] in _VORSAETZE:  # Vorsätze ohne eigene Aussage: der eigentliche Befehl steht dahinter
            vorsatz = w[i]
            i += 1
            while i < len(w) and w[i].startswith("-"):
                i += 2 if w[i] in _SUDO_MIT_WERT or (vorsatz != "sudo" and w[i] in ("-n", "-s", "-k", "-c")) else 1
            if vorsatz == "timeout" and i < len(w):
                i += 1  # Dauer
            while vorsatz == "env" and i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
                i += 1
        if i < len(w):
            yield w[i]


#: Shell-Handwerkszeug ohne fachliche Aussage: wird kein thema:-Reiz (sonst passte jede Notiz über grep zu jedem zweiten Befehl).
SHELL_ALLTAG = frozenset("""cd ls ll echo printf cat less more head tail sort uniq wc tee true false test [ sleep export set unset source . pwd date
    which type command exec eval read wait yes column printenv exit return mkdir rmdir touch basename dirname realpath readlink
    bash sh zsh dash python python3 perl""".split())
#: Bewusst NICHT im Alltag (seit 0.20.2): grep, sed, awk, find, xargs, kill/pkill/pgrep, chmod/chown, cp/mv/ln, timeout, nohup, env, python …
#: Zu ihnen gibt es echte Fallstricke (pkill -f trifft die eigene Shell, sed -i, find -exec, chmod -R); eine Notiz mit thema:pkill muss erscheinen.
_ANSIBLE_LIMIT = re.compile(r"(?:^|\s)(?:-l|--limit)(?:\s+|=)(\S+)")


def befehls_reize(kommando: str) -> list[str]:
    """Rein. thema:<befehl> für jeden erkannten Befehl außer Shell-Alltag (seit 0.19.4, vorher nur bekannte), skill:<bereich> für bekannte,
    host:<ziel> für ssh und für Hostnamen hinter ansible -l/--limit."""
    aus = []
    for b in _befehle(kommando or ""):
        if b in BEFEHL_SKILL:
            aus += [f"skill:{BEFEHL_SKILL[b]}", f"thema:{b}"]
        elif b not in SHELL_ALLTAG and re.fullmatch(r"[a-z][a-z0-9._+-]{1,40}", b):
            aus.append(f"thema:{b}")
    aus += [f"host:{h.lower()}" for h in _SSH_ZIEL.findall(kommando or "")]
    for ziel in _ANSIBLE_LIMIT.findall(kommando or ""):
        aus += [f"host:{h.lower()}" for h in re.split(r"[:,]", ziel.strip("'\"")) if "." in h and not h.startswith(("!", "&", "~"))]
    return aus


def reize(tool: str, args: dict, kontext: list[str] | None = None) -> list[str]:
    """Hinweisreize einer Handlung: Werkzeug, Skill (Präfix bis zum ersten _), Host aus den Argumenten, bei Shell-Werkzeugen die
    erkannten Befehle und SSH-Ziele, dazu die Kontext-Hashtags des Clients (woran er gerade arbeitet, z. B. thema:oom). Ungültige Hashtags fallen weg."""
    r = [f"tool:{tool}", f"skill:{tool.split('_')[0]}"]
    for k, v in (args or {}).items():
        if k in HOSTKEYS and isinstance(v, str) and v.strip():
            r.append(f"host:{v.strip().lower()}")
    if tool in SHELL_WERKZEUGE:
        r += befehls_reize(str((args or {}).get("command") or (args or {}).get("cmd") or ""))
    r += [t.strip() for t in (kontext or []) if isinstance(t, str) and not t.startswith(g.VERWALTUNG)]
    return list(dict.fromkeys(t for t in r if g.TAG.match(t)))


def fehler_signatur(text: str) -> str:
    return re.sub(r"[0-9a-f]{8,}|\d+", "#", (text or "")[:160])


def _frage(tool: str, args: dict) -> str:
    return g.hashwert(tool, json.dumps(args, sort_keys=True, ensure_ascii=False))


def vorher(tool: str, args: dict, instanz: str | None = None, ist_lesend: bool | None = None,
           kontext: list[str] | None = None) -> dict:
    args, hinweise = reflexe.vorher(tool, dict(args or {}))
    from . import fragen, selbst, sitzung  # spät: nutzen gedaechtnis wie wir
    hinweise += fragen.zustellen(instanz)
    s = sitzung.aktuelle()
    if s is not None:  # Selbst alle WIEDERHOLUNG_JE Handlungen wiederholen (Persona-Drift, Li et al. 2024)
        s.handlungen += 1
        if s.handlungen % selbst.WIEDERHOLUNG_JE == 0:
            hinweise.append(selbst.hinweis())
    rz = reize(tool, args, kontext)
    from . import lernen as _lernen
    warn = _lernen.warnung(rz)  # 0.20.8: Router-Modell erkennt riskante Lagen; nur mit gezählter Begründung
    if warn:
        hinweise.append(warn)
    such_reize = rz
    gefunden, suchen, aus_gedaechtnis = [], [], []
    # Kein zugriff() beim automatischen Zeigen: Gezeigtes würde sonst allein durchs Zeigen wichtiger (Selbstbestätigung,
    # Matthäus-Effekt). Verstärkt wird in nachher(), wenn die Handlung danach gelang — Annahme „der Hinweis hat genützt“,
    # benannt in docs/ARCHITEKTUR.md; Beobachtungspunkt: vi_erfahrung (Erfolg mit/ohne Hinweise).
    # Kandidaten (Heuristik: Aktualität + Wichtigkeit + Bonus), dann ggf. Router-Modell (gelernter Lift), dann Erkundung
    from . import bandit, lernen
    import random as _random
    kand = [o for _, o, _g in g.erinnere("(" + " OR ".join(such_reize) + ")", limit=HINWEIS_BUDGET + 24, arten=("erkenntnis", "regel", "skill"))]
    # 0.21.1: Strittiges und unbestätigte Sprachmodell-Hypothesen nur auf Nachfrage (vi_erinnere), nicht ungefragt vor Handlungen.
    # Gemessen 09.11.: eine strittige Schlaf-Hypothese war mit 719 Verstärkungen der meistgezeigte Hinweis und verdrängte belegtes Wissen.
    nur_auf_nachfrage = [o for o in kand if o.modus == "strittig" or ("herkunft:schlaf-llm" in o.hashtags and not o.fremde_bestaetigungen())]
    kand = [o for o in kand if o not in nur_auf_nachfrage]
    from . import p2p  # Quellen, die sich als schädlich erwiesen haben, werden nicht mehr gezeigt
    kand = p2p.ohne_gesperrte(kand)
    router = "heuristik"
    m = lernen.aktiv()
    if m is not None and kand:
        rang = dict(lernen.rangfolge(m, such_reize, [o.id for o in kand]))
        kand.sort(key=lambda o: -rang.get(o.id, 0.0))
        router = "modell"
    elif bandit.hat_zaehler(kand):  # Stufe 2: Thompson Sampling, sobald irgendein Kandidat bewertet wurde
        kand = bandit.ordne(kand)
        router = "bandit"
    # Erst Passung, dann gelernter Nutzen: Eine neue, genau passende Regel hat noch keine Geschichte und verlöre sonst gegen
    # eingespielte allgemeine Hinweise. Wichtigkeit 3 (Warnung) geht vor. Werkzeug-Reize einer Shell sagen nichts Spezifisches.
    allgemein = {f"tool:{tool}", f"skill:{tool.split('_')[0]}", "thema:ssh"} if tool in SHELL_WERKZEUGE else set()  # ssh ist nur der Transport
    passend = set(such_reize) - allgemein
    kand.sort(key=lambda o: (-(o.wichtigkeit >= 3 and bool(passend & set(o.hashtags))), -len(passend & set(o.hashtags))))
    # Überzählige Handbuch-Absätze nie regulär zeigen, nur über die Erkundung (so lernt der Bandit, ob sie doch helfen)
    ueberzaehlig = {o.id for o in [o for o in kand if any(t in o.hashtags for t in NACHSCHLAG)][NACHSCHLAG_MAX:]}
    regulaer = [o for o in kand if o.id not in ueberzaehlig]
    gezeigt_obj = regulaer[:HINWEIS_BUDGET]
    exploration = False
    rest = regulaer[HINWEIS_BUDGET:] + [o for o in kand if o.id in ueberzaehlig]
    if rest and _random.random() < lernen.EPSILON:  # ε-Erkundung: ein Platz für einen zufälligen Kandidaten von weiter hinten
        gezeigt_obj = gezeigt_obj[:-1] + [_random.choice(rest)]
        exploration = True
    for i, o in enumerate(gezeigt_obj):
        gefunden.append(o.id)
        herkunft = f"von {o.instanz}" + (f", bestätigt von {o.fremde_bestaetigungen()} weiteren Instanz(en)" if o.fremde_bestaetigungen() else "")
        erk = " (Erkundung)" if exploration and i == len(gezeigt_obj) - 1 else ""
        if o.art == "skill":
            from . import skills
            aus_gedaechtnis.append(f"{skills.zeile(o)}{erk} [{o.id}]")
            continue
        aus_gedaechtnis.append(f"{'Gelernt' if o.art == 'erkenntnis' else 'Regel'}{erk} [{o.id}] ({herkunft}"
                               + (", STRITTIG — von einer anderen Instanz widersprochen" if o.modus == "strittig" else "")
                               + f"; {', '.join(t for t in o.hashtags if t.startswith(('modus:', 'skill:', 'kollektiv:')))[:60]}): "
                               f"{o.text[:300]} [Quelle: {str(o.daten.get('quelle', '—'))[:120]}]"
                               + (f" [vollständig mit Code/Tabellen: vi_objekt {o.id}]" if o.daten.get("inhalt") else ""))
    kandidaten_ids = [o.id for o in kand]
    uebrig = len(kand) - len(gezeigt_obj)
    # 1. Zugriff auf Gelerntes: Suchen, deren Hinweisreize zur Handlung passen, laufen automatisch
    for _, su, _g in g.erinnere("(" + " OR ".join(such_reize) + ")", limit=3, arten=("suche",)):
        treffer = [o for _, o, _g2 in g.erinnere(su.daten.get("filter", ""), limit=3) if o.id != su.id]
        gefunden += [su.id] + [o.id for o in treffer]
        suchen.append({"suche": su.id, "name": su.daten.get("name"), "treffer": [o.id for o in treffer]})
        aus_gedaechtnis.append(f"Gelernte Suche „{su.daten.get('name')}“ [{su.daten.get('filter')}] — {su.text[:120]}: "
                               + ("; ".join(f"[{o.id}] {o.text[:90]}" for o in treffer) if treffer else "keine Treffer"))
    # Arbeitsgedächtnis: höchstens HINWEIS_BUDGET Hinweise aus dem Gedächtnis (Cowan 2001: ~4 Chunks); der Rest auf Abruf
    if len(aus_gedaechtnis) > HINWEIS_BUDGET:
        uebrig += len(aus_gedaechtnis) - HINWEIS_BUDGET
        aus_gedaechtnis = aus_gedaechtnis[:HINWEIS_BUDGET]
    if uebrig > 0 or nur_auf_nachfrage:
        zusatz = f" (davon {len(nur_auf_nachfrage)} strittig oder unbestätigte Hypothese, nur auf Nachfrage)" if nur_auf_nachfrage else ""
        aus_gedaechtnis.append(f"… {uebrig + len(nur_auf_nachfrage)} weitere Treffer im Gedächtnis{zusatz} — vi_vertiefe(\"{' '.join(such_reize)}\") zeigt sie")
    hinweise += aus_gedaechtnis
    from . import lager
    hinweise += lager.hinweis(such_reize)
    antwort, alter_s, ttl = None, None, None
    from .konfig import OFFEN
    if lesend(tool, ist_lesend) and instanz != OFFEN:  # ohne Token teilen sich alle eine Instanz: keine gemerkten Antworten
        ttl = min(ttl_je_werkzeug.get(tool, TTL_STANDARD), TTL_MAX)
        for _, o, _g in g.erinnere(f"art:antwort cache:{_frage(tool, args)}", limit=1, betrachter=instanz):
            alter = (datetime.now(timezone.utc) - datetime.fromisoformat(o.zeit)).total_seconds()
            if alter <= ttl:
                gefunden.append(o.id)
                antwort, alter_s = o.daten.get("ergebnis", ""), int(alter)
    zugriff = {"reize": rz, "warnung": bool(warn), "gefunden": gefunden, "gezeigt": [o.id for o in gezeigt_obj], "kandidaten": kandidaten_ids,
               "router": router, "exploration": exploration, "suchen": suchen, "aus_gedaechtnis": antwort is not None}
    vorher_id = secrets.token_hex(8)
    if antwort is not None:
        erfahrung(tool, args, True, 0, None, antwort, zugriff, instanz, ist_lesend)
    else:
        offene_abschliessen(nur_aelter_als_s=OFFEN_MAX_S)
        with _offen_sperre:
            _offen[vorher_id] = (time.monotonic(), tool, args, zugriff, instanz, ist_lesend, g.aktuelles_gespraech.get())
    return {"vorher_id": vorher_id, "antwort": antwort, "antwort_alter_s": alter_s, "antwort_ttl_s": ttl,
            "args": args, "hinweise": hinweise, "zugriff": zugriff}


#: 0.20.9: Bestätigen/Widerlegen eines gezeigten Hinweises innerhalb dieses Zeitraums zählt als Rückmeldung zu der Handlung
RUECKMELDUNG_MIN = 60


def rueckmeldung(instanz: str, hinweis_id: str, wert: int) -> str | None:
    """Ordnet ein vi_bestaetige (+1) / vi_widerlege (−1) der jüngsten Handlung dieser Instanz zu, vor der genau dieser Hinweis gezeigt
    wurde (höchstens RUECKMELDUNG_MIN Minuten zurück). Liefert die Id der Erfahrung oder None (dann bleibt es eine normale Bestätigung)."""
    seit = (datetime.now(timezone.utc) - timedelta(minutes=RUECKMELDUNG_MIN)).isoformat(timespec="milliseconds")
    with g.sperre:
        rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND instanz = ? AND zeit >= ? ORDER BY zeit DESC LIMIT 200",
                              (instanz, seit)).fetchall()
    for (eid,) in rows:
        e = g.lade(eid)
        if e and hinweis_id in ((e.daten.get("vorher") or {}).get("gezeigt") or []):
            e.daten.setdefault("rueckmeldung", {})[hinweis_id] = 1 if wert > 0 else -1
            e.aendere(f"ki@{instanz}", "Rückmeldung zum Hinweis", f"{hinweis_id}: {'half' if wert > 0 else 'war falsch'}")
            g.speichere(e)
            return eid
    return None


def nachher(tool: str, args: dict, ok: bool, dauer_ms: int, fehler: str | None, ergebnis: str | None,
            vorher_id: str | None = None, instanz: str | None = None, ist_lesend: bool | None = None) -> dict:
    with _offen_sperre:
        offen = _offen.pop(vorher_id, None) if vorher_id else None
    zugriff = offen[3] if offen else {"reize": reize(tool, args or {}), "gefunden": [], "suchen": [],
                                      "aus_gedaechtnis": False, "ohne_vorher": True}
    o = erfahrung(tool, args or {}, ok, dauer_ms, fehler, ergebnis, zugriff, instanz, ist_lesend)
    from . import bandit
    bewertet = bandit.verbuche(zugriff.get("gezeigt", []), ok, tool)  # Zählerpaar je gezeigtem Hinweis (Stufe 2)
    verstaerkt = 0
    if ok:  # Hinweise, nach denen die Handlung gelang, werden verstärkt (Konsolidierung) — nicht schon beim Zeigen
        for oid in zugriff.get("gefunden", []):
            if not oid.startswith("antwort:"):
                h = g.lade(oid)
                if h:
                    h.zugriff()
                    verstaerkt += 1
    hinweise = reflexe.nachher(tool, dict(args or {}), ergebnis or "") if ok else []
    if ok is not None:  # eine bewertete Handlung ist eine neue Beobachtung für Router und Bandit
        from . import bedarf
        bedarf.anstossen("Erfahrung")
    return {"erfahrung": o.id, "hinweise": hinweise, "vorher_gefunden": bool(offen), "verstaerkt": verstaerkt, "bewertet": bewertet}


def offene_abschliessen(gespraech: str | None = None, nur_aelter_als_s: float | None = None) -> int:
    """vorher ohne nachher → Erfahrung mit ok:unbekannt (benannter Zustand statt stillem Verschwinden).
    Wahl: alle eines Gesprächs (beim Sitzungsende) oder alle älter als nur_aelter_als_s."""
    with _offen_sperre:
        if gespraech is not None:
            ids = [k for k, v in _offen.items() if v[6] == gespraech]
        else:
            grenze = time.monotonic() - (nur_aelter_als_s or 0)
            ids = [k for k, v in _offen.items() if v[0] < grenze]
        faelle = [_offen.pop(k) for k in ids]
    for _t0, tool, args, zugriff, instanz, ist_lesend, serial in faelle:
        tok = g.aktuelles_gespraech.set(serial)
        try:
            erfahrung(tool, args, None, 0, None, None, {**zugriff, "ohne_nachher": True}, instanz, ist_lesend)
        finally:
            g.aktuelles_gespraech.reset(tok)
    return len(faelle)


#: Überraschung (Vorhersagefehler als Lernsignal, docs/FORSCHUNG.md A7): Stufe → Wichtigkeit. Erschöpfend.
UEBERRASCHUNG = {"neu": 3, "wiederholt": 2, "erholt": 2, "chronisch": 1, "keine": 0, "unbekannt": 0}


def ueberraschung(tool: str, ok: bool | None, fehler_sig: str | None) -> tuple[str, str]:
    """(Stufe, Grund). Erster Fehler dieser Art in 24 h = neu; 2.–3. = wiederholt; ab dem 4. = chronisch;
    Erfolg nach Fehlern desselben Werkzeugs = erholt; sonst keine. Zählt über alle Instanzen (Server-Sicht)."""
    if ok is None:
        return "unbekannt", "kein Ergebnis gemeldet"
    seit = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with g.sperre:
        if not ok and fehler_sig:
            n = g.db().execute("SELECT COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? "
                               "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = ? WHERE o.art = 'erfahrung' AND o.zeit >= ?",
                               (f"tool:{tool}", f"fehler:{fehler_sig}", seit)).fetchone()[0]
            if n == 0:
                return "neu", "erster Fehler dieser Art in 24 h"
            if n <= 2:
                return "wiederholt", f"{n + 1}. gleicher Fehler in 24 h"
            return "chronisch", f"{n + 1}. gleicher Fehler in 24 h — bekannt, nicht mehr überraschend"
        if ok:
            n = g.db().execute("SELECT COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? "
                               "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = 'ok:nein' WHERE o.art = 'erfahrung' AND o.zeit >= ?",
                               (f"tool:{tool}", seit)).fetchone()[0]
            if n:
                return "erholt", f"Erfolg nach {n} Fehler(n) desselben Werkzeugs in 24 h"
    return "keine", "erwarteter Ausgang"


def erfahrung(tool: str, args: dict, ok: bool | None, dauer_ms: int, fehler: str | None, ergebnis: str | None,
              zugriff: dict, instanz: str | None = None, ist_lesend: bool | None = None) -> g.Objekt:
    tags = [f"tool:{tool}", f"skill:{tool.split('_')[0]}", f"ok:{'unbekannt' if ok is None else 'ja' if ok else 'nein'}"]
    tags += [t for t in zugriff.get("reize", []) if t.startswith(("host:", "thema:"))]  # Kontext-Reize als Tags (TRAINING.md 4a)
    sig = None
    if fehler:
        sig = fehler_signatur(fehler)[:60].replace(" ", "_").replace("(", "_").replace(")", "_")
        if g.TAG.match(f"fehler:{sig}"):
            tags.append(f"fehler:{sig}")
        else:
            sig = None
    stufe, grund_u = ueberraschung(tool, ok, sig)  # VOR dem Speichern zählen, sonst zählt sich die Erfahrung selbst mit
    tags.append(f"ueberraschung:{stufe}")
    tags = [t for t in tags if g.TAG.match(t)]
    text = f"{tool}({json.dumps(args, ensure_ascii=False)[:300]}) → " + (f"Fehler: {fehler[:300]}" if fehler else "kein Ergebnis gemeldet (vi_nachher fehlt)" if ok is None
                                                                       else f"ok, {len(ergebnis or '')} Zeichen, {dauer_ms} ms")
    o = g.neues_objekt("erfahrung", text, tags, {"args": args, "dauer_ms": dauer_ms, "fehler": fehler, "vorher": zugriff,
                                                  "ueberraschung": {"stufe": stufe, "grund": grund_u}},
                       wichtigkeit=UEBERRASCHUNG[stufe], grund=f"Werkzeugaufruf · Überraschung {stufe}: {grund_u}", instanz=instanz)
    for oid in zugriff.get("gefunden", []):
        o.verknuepfe(oid, "vor der Handlung erinnert")
    from .konfig import OFFEN
    if ok and ergebnis is not None and lesend(tool, ist_lesend) and not zugriff.get("aus_gedaechtnis") and len(ergebnis) <= 200_000 and instanz != OFFEN:
        fh = _frage(tool, args)
        with g.sperre:
            # nur die eigene gemerkte Antwort ersetzen — der Cache ist privat je Instanz
            alt = [r[0] for r in g.db().execute("SELECT t.objekt_id FROM tag t JOIN objekt o ON o.id = t.objekt_id "
                                                "WHERE t.tag = ? AND o.instanz = ?", (f"cache:{fh}", o.instanz))]
        g.loesche(alt)
        g.neues_objekt("antwort", text, [f"tool:{tool}", f"cache:{fh}"], {"ergebnis": ergebnis, "args": args},
                       wichtigkeit=0, grund="Antwort gemerkt", instanz=instanz)
    from . import sitzung  # spät: sitzung kennt intuition nicht
    s = sitzung.aktuelle()
    if s:
        s.zug({"zeit": g.jetzt(), "tool": tool, "args": args, "ok": ok, "dauer_ms": dauer_ms, "fehler": fehler,
               "vorher": zugriff, "erfahrung": o.id})
    return o

"""Anonymisierung — was das Netz verlässt oder aus ihm kommt, trägt keine IPs, internen Namen, Zugangsdaten, Nutzernamen, Proxy-Angaben.

Zwei Richtungen, eine Musterliste: Der Export ersetzt Fundstellen durch Platzhalter und prüft das Ergebnis erneut; bleibt etwas
hängen, geht das Objekt nicht hinaus. Der Import lehnt jedes Objekt mit Fundstelle ab. Berichte nennen nur die Klasse, nie den Wert.

Domains gelten als intern, solange sie nicht auf der Liste öffentlicher Domains stehen. Muster kennen keine Bedeutung: Frei stehende
Eigennamen findet nur die Liste bekannter Namen, die der Export aus dem eigenen Gedächtnis und dem System zusammenstellt.
"""
from __future__ import annotations

import ipaddress
import math
import re
import socket
from collections import Counter
from pathlib import Path

PLATZHALTER = {"geheimnis": "<geheimnis>", "proxy": "<proxy>", "email": "<nutzer>", "nutzer": "<nutzer>", "ip": "<ip>", "mac": "<ip>", "domain": "<host>", "host": "<host>", "name": "<host>"}
OEFFENTLICH = ("python.org", "github.com", "githubusercontent.com", "gitlab.com", "debian.org", "ubuntu.com", "kernel.org", "man7.org", "wikipedia.org", "readthedocs.io",
               "stackoverflow.com", "ietf.org", "rfc-editor.org", "w3.org", "mozilla.org", "apache.org", "nginx.org", "postgresql.org", "sqlite.org", "docker.com", "redhat.com",
               "fedoraproject.org", "microsoft.com", "openai.com", "anthropic.com", "scikit-learn.org", "numpy.org", "pytorch.org", "arxiv.org", "doi.org",
               "example.com", "example.org", "example.net", "modelcontextprotocol.io", "claude.com")
#: Datei-Endungen, die wie Länderkürzel aussehen: `start.sh` ist kein Host, `a.b.sh` könnte einer sein
DATEI = {"py", "md", "sh", "pl", "rs", "cc", "mk", "ps", "so", "am", "ai", "app"}
TLD = set("""com org net de at ch eu io co uk fr it nl be es pl se no dk fi cz us ca au jp cn ru br in ch li lu ie pt gr hu ro
             info biz name pro media cloud dev app ai tech online site store xyz top club live news shop group agency digital network systems solutions
             local lan internal intranet corp home localdomain intern priv private test invalid""".split())
GENERISCH = {"root", "admin", "administrator", "test", "nutzer", "user", "vi", "claude", "codex", "hermes", "claude-code", "ubuntu", "debian", "fedora", "centos", "nobody", "www-data",
             "postgres", "mysql", "nginx", "docker", "vi-mcp", "localhost", "server", "host", "client", "default"}
_NAME_ERLAUBT = re.compile(r"^(sha|rfc|iso|ieee|pep|bep|cwe|cve|md|utf|ipv|x)\d+$", re.I)

_GEHEIM_KONTEXT = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\b(?:authorization\s*[:=]\s*)?bearer\s+[\w.~+/=-]{8,}", re.I),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
    re.compile(r"\b(?:eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[\w-]{16,}|xox[abprs]-[\w-]{10,}|sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"(?<![\w-])(?:[\w-]*(?:pass(?:wort|word|wd|phrase)?|pwd|kennwort|secret|geheimnis|token|api[_-]?key|credentials?)[\w-]*)[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+)", re.I),
    re.compile(r"\b(?:sshpass\s+-p\s*|mysql\s+\S*\s*-p)\S+"),
]
_PROXY = [
    re.compile(r"\b(?:https?|ftp|all|no|socks)_proxy\s*[=:]\s*\S+", re.I),
    re.compile(r"--(?:no)?proxy[= ]\s*\S+", re.I),
    re.compile(r"\bproxy(?:[_ -]?(?:server|host|url|adresse|address|port))?\s*[:=]\s*\S+", re.I),
    re.compile(r"\bproxy\s+[\w.-]+:\d{2,5}\b", re.I),
    re.compile(r"\b[\w-]*proxy[\w-]*(?:\.[\w-]+)+(?::\d{2,5})?", re.I),
]
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_NUTZER = [
    re.compile(r"(?<=/home/)[\w.-]+"), re.compile(r"(?<=/Users/)[\w.-]+"), re.compile(r"(?<=\\Users\\)[\w.-]+"),
    re.compile(r"\b[a-z_][\w.-]*(?=@[\w.-]+)", re.I),
    re.compile(r"(?<![\w-])(?:user(?:name)?|benutzer(?:name)?|nutzername|login|account|owner)\s*[:=]\s*[\"']?\S+", re.I),
    re.compile(r"\bals\s+(?:user|nutzer|benutzer)\s+[a-z_][\w.-]{2,}", re.I),
    re.compile(r"(?<=\s-u\s)[a-z_][\w.-]{1,}", re.I),
]
_IP4 = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?(?![\w.]*\d)")
_IP6 = re.compile(r"(?<![\w:.])(?=[0-9a-f:]*:[0-9a-f:]*:)[0-9a-f:]{2,39}(?![\w:])", re.I)
_MAC = re.compile(r"(?<![\w:-])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![\w:-])", re.I)
_URL_HOST = re.compile(r"(?<=://)[^/\s:@?#<>\"']+")
_FQDN = re.compile(r"(?<![\w@./-])[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+\.?(?![\w-])", re.I)
_NUMMERNHOST = re.compile(r"\b[a-z]{2,10}\d{3,5}\b", re.I)
_WORT = re.compile(r"(?<![\w<])[^\s<>\"'`=:,;()\[\]{}]{8,}")
#: `dvxhMSsqSC][`: Sonderzeichen am Ende trennen `_WORT`; eine Variable mit Index (`werte[i]`) hat keinen Großbuchstaben
_KLAMMERWORT = re.compile(r"(?<![\w<])[A-Za-z0-9]{6,}[\]\[!$%&*#]{1,3}(?![\w\]\[])")
_MCP = re.compile(r"mcp__[\w-]+?__")
#: Hashtags, deren Wert immer den Standort oder eine Person beschreibt
ORTSBEZUG = ("host:", "ort:", "standort:", "site:", "kunde:", "nutzer:", "user:", "ip:", "gespraech:", "dublette:", "suche:")
ZUGANG = re.compile(r"passwor|kennwort|zugangsdaten|anmeldedaten|credential", re.I)
PRIVAT_ZUSATZ: tuple[str, ...] = ()
ZUSATZ_NAMEN: tuple[str, ...] = ()


def setze(p2p: dict | None) -> None:
    """Aus der Konfiguration: öffentliche Domains (p2p.oeffentliche_domains), eigene Namen (p2p.interne_namen)."""
    global PRIVAT_ZUSATZ, ZUSATZ_NAMEN
    PRIVAT_ZUSATZ = tuple(x.lower() for x in (p2p or {}).get("oeffentliche_domains", []))
    ZUSATZ_NAMEN = tuple((p2p or {}).get("interne_namen", []))


def _oeffentlich(host: str) -> bool:
    h = host.lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in OEFFENTLICH + PRIVAT_ZUSATZ)


def _gemischt(w: str) -> bool:
    """Sieht ein Wort wie ein Kennwort oder Schlüssel aus? Fehlalarme kosten nur einen Platzhalter, Treffer verhindern ein Leck."""
    w = w.strip(".")
    if "/" in w or len(w) < 8 or w.startswith(("http", "mcp__")):
        return False
    gr, kl, zi = any(c.isupper() for c in w), any(c.islower() for c in w), any(c.isdigit() for c in w)
    if len(w) >= 24:
        verteilung = Counter(w)
        entropie = -sum(n / len(w) * math.log2(n / len(w)) for n in verteilung.values())
        if entropie >= 3.5 and sum((gr, kl, zi)) >= 2 and "_" not in w:
            return True
    if re.fullmatch(r"[0-9a-f]{32,}", w, re.I):
        return True
    if not (kl and (gr or zi)):
        return False
    return (gr and kl and zi and bool(re.fullmatch(r"[\w!$%&*+\]\[#-]+", w)) and "_" not in w) or bool(re.search(r"[a-zA-Z0-9][\]\[!$%&*#][a-zA-Z0-9\]\[]|[\]\[]{2}$", w))


def _tld_passt(kand: str) -> bool:
    teile = kand.lower().rstrip(".").split(".")
    if teile[-1] not in TLD or all(t.isdigit() for t in teile):
        return False
    return not (len(teile) == 2 and teile[-1] in DATEI)


def befunde(text: str, bekannte: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, int, int]]:
    """(klasse, anfang, ende), sortiert, ohne Überlappung. Rein. Früher genannte Klassen haben Vorrang."""
    if not text:
        return []
    roh: list[tuple[str, int, int]] = []
    def alle(klasse, muster):
        roh.extend((klasse, m.start(), m.end()) for m in muster.finditer(text))
    for m in _GEHEIM_KONTEXT:
        alle("geheimnis", m)
    for m in _PROXY:
        alle("proxy", m)
    alle("email", _EMAIL)
    alle("mac", _MAC)
    for m in _IP4.finditer(text):
        try:
            ipaddress.ip_network(m.group(0), strict=False)
            roh.append(("ip", m.start(), m.end()))
        except ValueError:
            pass
    for m in _IP6.finditer(text):
        try:
            if ipaddress.ip_address(m.group(0)).version == 6:
                roh.append(("ip", m.start(), m.end()))
        except ValueError:
            pass
    for m in _URL_HOST.finditer(text):
        if not _oeffentlich(m.group(0)):
            roh.append(("domain", m.start(), m.end()))
    for m in _NUTZER:
        alle("nutzer", m)
    for m in _FQDN.finditer(text):
        if _tld_passt(m.group(0)) and not _oeffentlich(m.group(0)):
            roh.append(("domain", m.start(), m.end()))
    for m in _NUMMERNHOST.finditer(text):
        if not _NAME_ERLAUBT.match(m.group(0)):
            roh.append(("host", m.start(), m.end()))
    for n in bekannte:
        roh.extend(("name", m.start(), m.end()) for m in re.finditer(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text, re.I))
    for m in _WORT.finditer(text):
        if _gemischt(m.group(0)):
            roh.append(("geheimnis", m.start(), m.end()))
    for m in _KLAMMERWORT.finditer(text):
        wort = m.group(0)
        if any(c.isupper() for c in wort) and any(c.islower() for c in wort):
            roh.append(("geheimnis", m.start(), m.end()))
    aus, belegt = [], []
    for k, a, b in sorted(roh, key=lambda x: (x[1], -(x[2] - x[1]))):
        if not any(a < e and s < b for s, e in belegt):
            aus.append((k, a, b))
            belegt.append((a, b))
    return aus


#: `token = lese_token()` oder `password: ${PW}` im Codebeispiel ist Wissen, kein Geheimnis
_AUSDRUCK = re.compile(r"[(${%<]|environ")


def _lokal_ersatz(m: re.Match) -> str:
    teile = re.split(r"[:=]", m.group(0), maxsplit=1)
    return m.group(0) if len(teile) == 2 and _AUSDRUCK.search(teile[1]) else "<geheimnis>"


def ohne_geheimnisse(wert):
    """Für alles, was lokal gespeichert wird: Zugangsdaten eindeutiger Form fallen weg, rekursiv. Host-Angaben bleiben, der Router braucht sie."""
    if isinstance(wert, str):
        for m in _GEHEIM_KONTEXT:
            wert = m.sub(_lokal_ersatz, wert)
        return wert
    if isinstance(wert, list):
        return [ohne_geheimnisse(x) for x in wert]
    if isinstance(wert, dict):
        return {k: (v if k == "code" else ohne_geheimnisse(v)) for k, v in wert.items()}
    return wert


def klassen(text: str, bekannte=frozenset()) -> list[str]:
    return sorted({k for k, _, _ in befunde(text, bekannte)})


def ersetze(text: str, bekannte=frozenset()) -> str:
    """Rein. MCP-Servernamen sind standortspezifisch und fallen weg."""
    text = _MCP.sub("", text or "")
    for k, a, b in reversed(befunde(text, bekannte)):
        text = text[:a] + PLATZHALTER[k] + text[b:]
    return text


def werkzeug(name: str) -> str:
    return _MCP.sub("", name)


def system_namen() -> set[str]:
    """Hostname und Konten des Rechners (uid ≥ 1000), dazu die Konfiguration. Generische Wörter tragen keine Identität."""
    aus = set(ZUSATZ_NAMEN)
    for voll in (socket.gethostname(), socket.getfqdn()):
        aus.add(voll)
        aus.add(voll.split(".")[0])
    try:
        for z in Path("/etc/passwd").read_text().splitlines():
            t = z.split(":")
            if len(t) > 3 and t[2].isdigit() and 1000 <= int(t[2]) < 65534:
                aus.add(t[0])
    except OSError:
        pass
    return {n for n in aus if len(n) >= 3 and n.lower() not in GENERISCH}

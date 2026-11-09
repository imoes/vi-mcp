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

PLACEHOLDERS = {"firma": "<firma>", "pfad": "<pfad>", "geheimnis": "<geheimnis>", "proxy": "<proxy>", "email": "<nutzer>", "nutzer": "<nutzer>", "ip": "<ip>", "mac": "<ip>", "domain": "<host>", "host": "<host>", "name": "<host>"}
PUBLIC = ("python.org", "github.com", "githubusercontent.com", "gitlab.com", "debian.org", "ubuntu.com", "kernel.org", "man7.org", "wikipedia.org", "readthedocs.io",
               "stackoverflow.com", "ietf.org", "rfc-editor.org", "w3.org", "mozilla.org", "apache.org", "nginx.org", "postgresql.org", "sqlite.org", "docker.com", "redhat.com",
               "fedoraproject.org", "microsoft.com", "openai.com", "anthropic.com", "scikit-learn.org", "numpy.org", "pytorch.org", "arxiv.org", "doi.org",
               "example.com", "example.org", "example.net", "modelcontextprotocol.io", "claude.com")
#: Datei-Endungen, die wie Länderkürzel aussehen: `start.sh` ist kein Host, `a.b.sh` könnte einer sein
FILE_EXTENSIONS = {"py", "md", "sh", "pl", "rs", "cc", "mk", "ps", "so", "am", "ai", "app"}
TLD = set("""com org net de at ch eu io co uk fr it nl be es pl se no dk fi cz us ca au jp cn ru br in ch li lu ie pt gr hu ro
             info biz name pro media cloud dev app ai tech online site store xyz top club live news shop group agency digital network systems solutions
             local lan internal intranet corp home localdomain intern priv private test invalid""".split())
GENERIC = {"root", "admin", "administrator", "test", "nutzer", "user", "vi", "claude", "codex", "hermes", "claude-code", "ubuntu", "debian", "fedora", "centos", "nobody", "www-data",
             "postgres", "mysql", "nginx", "docker", "vi-mcp", "localhost", "server", "host", "client", "default"}
#: Bezeichnungen, die wie Name+Nummer aussehen, aber keine Rechner sind. Im Zweifel wird ersetzt: ein Fehlalarm kostet nur ein Wort.
_NAME_ALLOWED = re.compile(r"^(sha|rfc|iso|ieee|pep|bep|cwe|cve|md|utf|ipv|x|win|windows|server|debian|ubuntu|rhel|el|centos|fedora|alma|almalinux|python|py|node|java|jdk|php|es|ecmascript|http|tls|ssl|h|"
                           r"gpt|qwen|llama|bge|top|cp|iso|port|ip|ipv|ec|aes|des|rsa|ed|curve|base|int|uint|float|bit|kb|mb|gb|tb|ms|hz|ghz|mhz|nr|nummer|version|v|kw|q|c|cpp|cxx|net|dotnet|ie|vs|office|excel|word|ansible|bep|nis|tcp|udp|dns|ms|ldap)-?\d+$", re.I)

_SECRET_CONTEXT = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\b(?:authorization\s*[:=]\s*)?bearer\s+[\w.~+/=-]{8,}", re.I),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
    re.compile(r"\b(?:eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[\w-]{16,}|xox[abprs]-[\w-]{10,}|sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"(?<![\w-])(?:[\w-]*(?:pass(?:wort|word|wd|phrase)?|pwd|kennwort|secret|geheimnis|token|api[_-]?key|credentials?)[\w-]*)[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+)", re.I),
    re.compile(r"\b(?:sshpass\s+-p\s*|mysql\s+\S*\s*-p)\S+"),
]
#: Index des groben Musters „Schlüsselwort = Wert“ in _GEHEIM_KONTEXT
_CONTEXT_KEYS = 4
_PROXY = [
    re.compile(r"\b(?:https?|ftp|all|no|socks)_proxy\s*[=:]\s*\S+", re.I),
    re.compile(r"--(?:no)?proxy[= ]\s*\S+", re.I),
    re.compile(r"\bproxy(?:[_ -]?(?:server|host|url|adresse|address|port))?\s*[:=]\s*\S+", re.I),
    re.compile(r"\bproxy\s+[\w.-]+:\d{2,5}\b", re.I),
    re.compile(r"\b[\w-]*proxy[\w-]*(?:\.[\w-]+)+(?::\d{2,5})?", re.I),
]
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_USER = [
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
#: Hostnamen nach Schema Name+Nummer: app0815, dbtest01, web-01, db-test-02 (gefunden am 08.11.2026: dbtest01 ging durch)
_NUMBERED_HOST = re.compile(r"\b[a-z]{2,12}(?:-[a-z]{2,12})*-?\d{2,5}\b", re.I)
_WORD = re.compile(r"(?<![\w<])[^\s<>\"'`=:,;()\[\]{}]{8,}")
#: `dvxhMSsqSC][`: Sonderzeichen am Ende trennen `_WORT`; eine Variable mit Index (`werte[i]`) hat keinen Großbuchstaben
_BRACKET_WORD = re.compile(r"(?<![\w<])[A-Za-z0-9]{6,}[\]\[!$%&*#]{1,3}(?![\w\]\[])")
_MCP = re.compile(r"mcp__[\w-]+?__")
#: Hashtags, deren Wert immer den Standort oder eine Person beschreibt
LOCATION_REF = ("host:", "ort:", "standort:", "site:", "kunde:", "nutzer:", "user:", "ip:", "gespraech:", "dublette:", "suche:")
CREDENTIAL_WORDS = re.compile(r"passwor|kennwort|zugangsdaten|anmeldedaten|credential", re.I)
PRIVATE_EXTRA: tuple[str, ...] = ()
EXTRA_NAMES: tuple[str, ...] = ()


def configure(p2p: dict | None) -> None:
    """Aus der Konfiguration: öffentliche Domains (p2p.oeffentliche_domains), eigene Namen (p2p.interne_namen)."""
    global PRIVATE_EXTRA, EXTRA_NAMES
    PRIVATE_EXTRA = tuple(x.lower() for x in (p2p or {}).get("oeffentliche_domains", []))
    EXTRA_NAMES = tuple((p2p or {}).get("interne_namen", []))


def _public(host: str) -> bool:
    h = host.lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in PUBLIC + PRIVATE_EXTRA)


def _mixed(w: str) -> bool:
    """Sieht ein Wort wie ein Kennwort oder Schlüssel aus? Fehlalarme kosten nur einen Platzhalter, Treffer verhindern ein Leck."""
    w = w.strip(".")
    if "/" in w or len(w) < 8 or w.startswith(("http", "mcp__")):
        return False
    gr, kl, zi = any(c.isupper() for c in w), any(c.islower() for c in w), any(c.isdigit() for c in w)
    if len(w) >= 24:
        distribution = Counter(w)
        entropy = -sum(n / len(w) * math.log2(n / len(w)) for n in distribution.values())
        if entropy >= 3.5 and sum((gr, kl, zi)) >= 2 and "_" not in w:
            return True
    if re.fullmatch(r"[0-9a-f]{32,}", w, re.I):
        return True
    if not (kl and (gr or zi)):
        return False
    return (gr and kl and zi and bool(re.fullmatch(r"[\w!$%&*+\]\[#-]+", w)) and "_" not in w) or bool(re.search(r"[a-zA-Z0-9][\]\[!$%&*#][a-zA-Z0-9\]\[]|[\]\[]{2}$", w))


def _tld_matches(cand: str) -> bool:
    parts = cand.lower().rstrip(".").split(".")
    if parts[-1] not in TLD or all(t.isdigit() for t in parts):
        return False
    return not (len(parts) == 2 and parts[-1] in FILE_EXTENSIONS)


#: 0.20.10: absolute Pfade außerhalb der Standardverzeichnisse verraten den Aufbau eines Standorts (z. B. /intern/ansible/prod, /daten2/…).
#: Nicht nach einem Host (URL-Pfad) und nicht /etc, /usr, /var … — die sind überall gleich und Wissen.
_DEFAULT_PATHS = ("etc", "usr", "var", "opt", "home", "tmp", "proc", "sys", "dev", "bin", "sbin", "lib", "lib64", "run", "srv", "mnt",
                   "media", "root", "boot", "snap")
_PATH = re.compile(rf"(?<![\w.~/:@-])/(?!(?:{'|'.join(_DEFAULT_PATHS)})(?:/|\b))[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.*-]+)+/?")


def companies(known_names) -> set[str]:
    """0.20.10: Organisationsnamen aus den Domains bekannter Hosts (*.firma.tld → firma), auch in Zusammensetzungen wie firma-skills.
    Rein. Öffentliche Domains und generische Wörter zählen nicht."""
    outputs = set()
    for n in known_names:
        n = str(n).lower()
        # nur echte Hostnamen: Zeichen eines DNS-Namens und eine passende Top-Level-Domain (nicht CHANGELOG.md, felder.py, app/x)
        if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", n) or not _tld_matches(n):
            continue
        parts = n.split(".")
        if not _public(".".join(parts[-2:])):
            f = parts[-2]
            if len(f) >= 4 and f not in GENERIC and not f.isdigit():
                outputs.add(f)
    return outputs


def findings(text: str, known_names: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, int, int]]:
    """(klasse, anfang, ende), sortiert, ohne Überlappung. Rein. Früher genannte Klassen haben Vorrang."""
    if not text:
        return []
    raw: list[tuple[str, int, int]] = []
    def all_(category, pattern):
        raw.extend((category, m.start(), m.end()) for m in pattern.finditer(text))
    for m in _SECRET_CONTEXT:
        all_("geheimnis", m)
    for m in _PROXY:
        all_("proxy", m)
    all_("email", _EMAIL)
    all_("mac", _MAC)
    for m in _IP4.finditer(text):
        try:
            ipaddress.ip_network(m.group(0), strict=False)
            raw.append(("ip", m.start(), m.end()))
        except ValueError:
            pass
    for m in _IP6.finditer(text):
        try:
            if ipaddress.ip_address(m.group(0)).version == 6:
                raw.append(("ip", m.start(), m.end()))
        except ValueError:
            pass
    for m in _URL_HOST.finditer(text):
        if not _public(m.group(0)):
            raw.append(("domain", m.start(), m.end()))
    for m in _USER:
        all_("nutzer", m)
    for m in _FQDN.finditer(text):
        if _tld_matches(m.group(0)) and not _public(m.group(0)):
            raw.append(("domain", m.start(), m.end()))
    for m in _NUMBERED_HOST.finditer(text):
        if not _NAME_ALLOWED.match(m.group(0)):
            raw.append(("host", m.start(), m.end()))
    for n in known_names:
        raw.extend(("name", m.start(), m.end()) for m in re.finditer(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text, re.I))
    for f in companies(known_names) | {z.lower() for z in EXTRA_NAMES if "." not in z and len(z) >= 4}:
        raw.extend(("firma", m.start(), m.end()) for m in re.finditer(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", text, re.I))
    all_("pfad", _PATH)
    for m in _WORD.finditer(text):
        if _mixed(m.group(0)):
            raw.append(("geheimnis", m.start(), m.end()))
    for m in _BRACKET_WORD.finditer(text):
        word = m.group(0)
        if any(c.isupper() for c in word) and any(c.islower() for c in word):
            raw.append(("geheimnis", m.start(), m.end()))
    outputs, evidenced = [], []
    for k, a, b in sorted(raw, key=lambda x: (x[1], -(x[2] - x[1]))):
        if not any(a < e and s < b for s, e in evidenced):
            outputs.append((k, a, b))
            evidenced.append((a, b))
    return outputs


#: `token = lese_token()` oder `password: ${PW}` im Codebeispiel ist Wissen, kein Geheimnis
_EXPRESSION = re.compile(r"[(${%<]|environ")


def _local_replacement(m: re.Match) -> str:
    parts = re.split(r"[:=]", m.group(0), maxsplit=1)
    return m.group(0) if len(parts) == 2 and _EXPRESSION.search(parts[1]) else "<geheimnis>"


#: Wörter, nach denen ein geheimer Wert folgt. „pw“ und „pin“ nur als ganzes Wort.
_SECRET_KEY_WORDS = re.compile(r"(passw(?:or)?[td]s?|kennw(?:ort|örter)|pass(?:phrase|code)|\bpwd?\b|\bpin\b|zugangsdaten|anmeldedaten|credentials?|"
                         r"\bsecret\b|geheimnis|\btoken\b|api[ _-]?key|client[ _-]?secret|shared[ _-]?key|psk\b|community[ _-]?string)", re.I)
_SEPARATOR = re.compile(r"\s*(?::|=|\||->|=>|\bist\b|\blautet\b|\bwar\b|\bauf\b|\bwird\b)\s*", re.I)
#: Was nach einem Passwort-Wort steht, aber kein Wert ist: Verweise, Platzhalter, Anweisungen
_NO_VALUE = re.compile(r"^(<[^>]*>|\$\{|\$[A-Z_]|\{\{|\*{2,}|x{3,}|\.{3}|…|siehe|s\.|im\b|in\b|aus\b|vom\b|von\b|der\b|die\b|das\b|des\b|dem\b|den\b|ein\w*\b|kein\w*\b|nicht\b|"
                       r"bitte|wird|ist\b|sind\b|password[ -]?depot|pwdepot|keepass|passwortsafe|tresor|vault|bekannt|vorhanden|leer|none|null|n/?a\b|-+$|ja\b|nein\b|"
                       r"ändern|aendern|setzen|eingeben|vergeben|zurücksetzen|abfragen|prompt|erforderlich|benötigt|nötig|optional|identisch|gleich|wie\b|per\b|über\b|mit\b|für\b|und\b|oder\b|"
                       r"neu\b|alt\b|eigen\w*|persönlich\w*|aktuell\w*|standard\w*|default|policy|richtlinie|ablauf|änderung|reset|hash|feld|spalte|beim\b|bei\b|nach\b|zum\b|zur\b)", re.I)
_VALUE = re.compile(r"[\"'`„“]?([^\s\"'`„“|,;]{3,80})")


def _value_after(line: str, m: re.Match) -> tuple[int, int] | None:
    rest = line[m.end():]
    t = _SEPARATOR.match(rest)
    if not t:
        return None
    w = _VALUE.match(rest, t.end())
    if not w or _NO_VALUE.match(w.group(1)) or _EXPRESSION.search(w.group(1)):
        return None
    return m.end() + w.start(1), m.end() + w.end(1)


def strip_credentials(text: str) -> tuple[str, int]:
    """Für Wissen aus Dokumenten und Verläufen: Werte hinter Passwort-Wörtern, Passwort-Spalten in Tabellen und der Wert in der Zeile
    nach „Passwort:“ werden zu <geheimnis>. Liefert (Text, Anzahl). Rein. Code-Ausdrücke wie `lese_token()` oder ${PW} bleiben."""
    text, n = text or "", 0
    for i, pattern in enumerate(_SECRET_CONTEXT):
        if i != _CONTEXT_KEYS:  # das grobe Schlüsselwort-Muster ersetzt auch Verweise; hier entscheidet _wert_hinter genauer
            text, k = pattern.subn("<geheimnis>", text)
            n += k
    lines, column, upcoming = text.split("\n"), None, False
    for i, z in enumerate(lines):
        cells = z.split("|") if z.count("|") >= 2 else None
        if cells and column is None and any(_SECRET_KEY_WORDS.search(c) for c in cells) and not any(_SEPARATOR.fullmatch(c.strip() or "x") for c in cells):
            column = next(j for j, c in enumerate(cells) if _SECRET_KEY_WORDS.search(c))
            continue
        if cells is None:
            column = None
        elif column is not None and column < len(cells) and not re.fullmatch(r"\s*:?-{2,}:?\s*", cells[column]):
            value = cells[column].strip()
            if value and not _NO_VALUE.match(value) and value != "<geheimnis>":
                cells[column] = cells[column].replace(value, "<geheimnis>")
                z, n = "|".join(cells), n + 1
        if upcoming and z.strip():
            w = z.strip()
            if " " not in w and 4 <= len(w) <= 80 and not _NO_VALUE.match(w) and not _EXPRESSION.search(w) and w != "<geheimnis>":
                z, n = z.replace(w, "<geheimnis>"), n + 1
            upcoming = False
        for m in reversed(list(_SECRET_KEY_WORDS.finditer(z))):
            if (pos := _value_after(z, m)):
                z, n = z[:pos[0]] + "<geheimnis>" + z[pos[1]:], n + 1
        if re.search(_SECRET_KEY_WORDS.pattern + r"\s*:?\s*$", z, re.I):
            upcoming = True
        lines[i] = z
    return "\n".join(lines), n


def without_secrets(value):
    """Für alles, was lokal gespeichert wird: Zugangsdaten eindeutiger Form fallen weg, rekursiv. Host-Angaben bleiben, der Router braucht sie."""
    if isinstance(value, str):
        for m in _SECRET_CONTEXT:
            value = m.sub(_local_replacement, value)
        return value
    if isinstance(value, list):
        return [without_secrets(x) for x in value]
    if isinstance(value, dict):
        return {k: (v if k == "code" else without_secrets(v)) for k, v in value.items()}
    return value


def categories(text: str, known_names=frozenset()) -> list[str]:
    return sorted({k for k, _, _ in findings(text, known_names)})


def replace(text: str, known_names=frozenset()) -> str:
    """Rein. MCP-Servernamen sind standortspezifisch und fallen weg."""
    text = _MCP.sub("", text or "")
    for k, a, b in reversed(findings(text, known_names)):
        text = text[:a] + PLACEHOLDERS[k] + text[b:]
    return text


def tool_parts(name: str) -> str:
    return _MCP.sub("", name)


def system_names() -> set[str]:
    """Hostname und Konten des Rechners (uid ≥ 1000), dazu die Konfiguration. Generische Wörter tragen keine Identität."""
    outputs = set(EXTRA_NAMES)
    for full in (socket.gethostname(), socket.getfqdn()):
        outputs.add(full)
        outputs.add(full.split(".")[0])
    try:
        for z in Path("/etc/passwd").read_text().splitlines():
            t = z.split(":")
            if len(t) > 3 and t[2].isdigit() and 1000 <= int(t[2]) < 65534:
                outputs.add(t[0])
    except OSError:
        pass
    return {n for n in outputs if len(n) >= 3 and n.lower() not in GENERIC}

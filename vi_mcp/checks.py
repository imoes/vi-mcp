"""Deterministische Prüfung fremder Inhalte — läuft immer zuerst, nur sie darf endgültig ablehnen.

Ein Modell lässt sich durch den geprüften Text selbst täuschen, eine Regel nicht. Deshalb gilt für jeden Import:
Regeln → Sprachmodell (pruefer.py, kann nur verschärfen) → Quarantäne → Freigabe.
`anweisungen()` ist die einzige Musterliste für „Anweisung statt Wissen“; die Reflexion im Schlaf benutzt dieselbe.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

from . import anonymize
from . import memory as g

KINDS_IMPORT = ("erkenntnis", "regel", "suche", "skill", "reflex")
TEXT_MIN, TEXT_MAX = 10, 1000
SOURCE_MIN, SOURCE_MAX = 8, 500
CODE_MAX = 20_000
CONTENT_MAX = 50_000
_REASON = {"art", "text", "hashtags", "quelle", "wichtigkeit", "zeit", "netz_id", "loesch_hash", "inhalt"}
FIELDS = {
    "erkenntnis": _REASON | {"ausgang"},
    "regel": _REASON,
    "suche": _REASON | {"name", "filter", "reize"},
    "skill": _REASON | {"name", "reize", "schritte"},
    "reflex": _REASON | {"name", "reflexart", "code"},
}
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
FIXED_HASHTAGS = g.ADMIN_PREFIXES + ("herausgeber:", "pruefer:", "sicht:")

_INSTRUCTION = [
    ("direktive", re.compile(r"ignor\w*\s+(alle\w*\s+|all\s+|die\s+|the\s+)*(vorherig\w*|bisherig\w*|previous|prior)|du bist (jetzt|ab sofort)|you are now|"
                             r"system ?prompt|\bkanarie\b|\bpr(ü|ue)fer\b|\burteil\s*[:=]?\s*zulassen\b|^\s*(system|assistant|user)\s*:|<\|im_start\|>|\[INST\]|#+\s*(instruction|anweisung)|</?objekt\b", re.I | re.M)),
    # Sätze, die dem Leser eine KI-Rolle zuweisen: das echte Modell ließ so einen Satz passieren (gemessen 08.11.2026)
    ("adressat", re.compile(r"\b(assistent\w*|sprachmodell\w*|ki[- ]?(agent\w*|system\w*|instanz\w*)|agent\w*|instanzen)\b.{0,80}\b(muss|müssen|muessen|soll\w*|darf|dürfen|duerfen|haben\s+zu)\b|"
                            r"\b(als\s+)?(bestätigt|bestaetigt|widerlegt|freigegeben)\s+(markieren|setzen|melden)\b", re.I | re.S)),
    ("befehl", re.compile(r"\b(führe|fuehre)\b.*\baus\b|\bexecute\b|\brun\b\s+\S|\brm\s+-rf\b|\bdrop\s+table\b|\bdd\s+if=|\bsudo\b|\bchmod\b|\bchown\b|"
                          r"\bcurl\b|\bwget\b|\bssh\s+\S+@", re.I)),
    ("aendern", re.compile(r"\b(lösche|loesche|delete|überschreibe|ueberschreibe)\b|\b(schreibe|write)\b.*\b(datei|file)\b", re.I)),
    ("gedaechtnis", re.compile(r"\bvi_(lerne|reflex_lerne|reflex_schalte|suche_lerne|widerlege|bestaetige|vergiss|loesche_gespraech|geloest|freigabe|netz_vergiss|netz_token)\b", re.I)),
    ("geheimnis", re.compile(r"passwor|\btoken\b|\bapi[_-]?key\b|\bsecret\b", re.I)),
    ("kodiert", re.compile(r"\bbase64\b|<script|<!--|\{\{|\$\{", re.I)),
]
_URL = re.compile(r"(https?|ftp|file)://|\\\\[\w.]+\\", re.I)
_BLOCK = re.compile(r"[A-Za-z0-9+/=]{40,}")
_INVISIBLE = re.compile("[​-‏‪-‮⁦-⁩\U000e0000-\U000e007f\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_DANGEROUS_BUILTIN = {"bash", "write", "edit", "notebookedit", "powershell"}


def directives(text: str) -> list[str]:
    """Treffer der Form `name:fundstelle`. Rein."""
    return [f"{name}:{m.group(0)[:40]}" for name, pattern in _INSTRUCTION if (m := pattern.search(text or ""))]


def _binary(blob: str) -> bool:
    try:
        d = base64.b64decode(blob + "=" * (-len(blob) % 4))
    except ValueError:
        return False
    return d[:4] in (b"PK\x03\x04", b"\x7fELF") or d[:2] == b"MZ" or d[2:4] == b"\r\n"


def writing(tool_parts: str) -> bool:
    from . import intuition
    return tool_parts.lower() in _DANGEROUS_BUILTIN or bool(intuition.WRITING.search(tool_parts))


@dataclass
class Finding:
    verdict: str = "quarantaene"  # „quarantaene“ oder „ablehnen“ — „zulassen“ gibt es hier nicht
    reasons: list = field(default_factory=list)
    mem_object: dict = field(default_factory=dict)

    def reject(self, reason: str) -> "Befund":
        self.verdict = "ablehnen"
        self.reasons.append(reason)
        return self


def _contents(raw: dict, o: dict):
    """Jedes Textfeld, das gespeichert würde. Auch verworfene Hashtags und Reize zählen: ihr Inhalt verrät genauso."""
    for field_name in ("text", "inhalt", "quelle", "filter", "name", "code"):
        if isinstance(o.get(field_name), str):
            yield field_name, o[field_name]
    for field_name in ("hashtags", "reize", "schritte"):
        for t in raw.get(field_name) or []:
            if isinstance(t, str):
                yield field_name, t.split(":", 1)[-1]


def _check_text(b: Finding, name: str, text: str, url_allowed: bool = False) -> None:
    if _INVISIBLE.search(text):
        b.reject(f"{name}: unsichtbare oder steuernde Zeichen")
    for blob in _BLOCK.findall(text):
        if _binary(blob):
            b.reject(f"{name}: kodierter Binärinhalt (nur Quelltext ist erlaubt)")
        else:
            b.reasons.append(f"{name}: langer kodierter Block")
    b.reasons += [f"{name}: {t}" for t in directives(text)]
    if not url_allowed and _URL.search(text):
        b.reasons.append(f"{name}: URL im Text")


def check(raw, may_reflex: bool = False) -> Finding:
    """Ein Objekt gegen die festen Regeln. Unbekannte Felder (Zähler, Modus, Bestätigungen) werden verworfen."""
    b = Finding()
    if not isinstance(raw, dict):
        return b.reject("Objekt ist kein JSON-Objekt")
    kind = raw.get("art")
    if kind not in KINDS_IMPORT:
        return b.reject(f"Art {kind!r} wird nicht importiert")
    o = {k: v for k, v in raw.items() if k in FIELDS[kind]}
    if not _HEX32.match(str(o.get("netz_id"))) or not _HEX64.match(str(o.get("loesch_hash"))):
        return b.reject("netz_id oder loesch_hash fehlen: ohne sie wäre das Objekt nie wieder löschbar")
    if isinstance(o.get("hashtags"), list) and any(isinstance(t, str) and t.startswith(anonymize.LOCATION_REF[:-3]) for t in o["hashtags"]):
        return b.reject("interna in hashtags: Standort, Host oder Person")
    text, source = o.get("text"), o.get("quelle")
    if not isinstance(text, str) or not TEXT_MIN <= len(text.strip()) <= TEXT_MAX:
        return b.reject(f"text muss {TEXT_MIN}–{TEXT_MAX} Zeichen haben")
    if not isinstance(source, str) or not SOURCE_MIN <= len(source.strip()) <= SOURCE_MAX:
        return b.reject(f"quelle muss {SOURCE_MIN}–{SOURCE_MAX} Zeichen haben")
    w = o.get("wichtigkeit", 1)
    o["wichtigkeit"] = w if isinstance(w, int) and not isinstance(w, bool) and 0 <= w <= 3 else 1
    if kind == "erkenntnis" and o.get("ausgang") not in (None, "gut", "schlecht"):
        return b.reject("ausgang muss gut oder schlecht sein")
    tags = o.get("hashtags")
    if not isinstance(tags, list):
        return b.reject("hashtags fehlen")
    good = [t.strip() for t in tags if isinstance(t, str) and g.TAG.match(t.strip()) and not t.strip().startswith(FIXED_HASHTAGS)]
    if len(good) != len(tags):
        b.reasons.append(f"{len(tags) - len(good)} Hashtags entfernt (Form oder fest vergeben)")
    o["hashtags"] = sorted(set(good))[:20]
    if not o["hashtags"]:
        return b.reject("kein gültiger inhaltlicher Hashtag")
    _check_text(b, "text", text)
    _check_text(b, "quelle", source, url_allowed=True)
    if "inhalt" in o:
        if not isinstance(o["inhalt"], str) or len(o["inhalt"]) > CONTENT_MAX:
            return b.reject(f"inhalt muss Text bis {CONTENT_MAX} Zeichen sein")
        _check_text(b, "inhalt", o["inhalt"], url_allowed=True)

    if kind in ("suche", "skill"):
        name, triggers = o.get("name"), o.get("reize")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9 _-]{2,40}", name):
            return b.reject("name: 2–40 Zeichen a-z, 0-9, Leerzeichen, - _")
        if not isinstance(triggers, list):
            return b.reject("reize fehlen")
        o["reize"] = sorted({t for t in triggers if isinstance(t, str) and g.TAG.match(t) and not t.startswith(FIXED_HASHTAGS)})[:20]
        if not o["reize"]:
            return b.reject("kein gültiger Reiz")
    if kind == "suche":
        f = o.get("filter")
        if not isinstance(f, str) or not f.strip() or len(f) > 300:
            return b.reject("filter fehlt oder ist zu lang")
        if re.search(r"modus:|sicht:|instanz:", f):
            return b.reject("filter darf modus:, sicht: und instanz: nicht ansprechen")
        _check_text(b, "filter", f)
    if kind == "skill":
        st = o.get("schritte")
        if not isinstance(st, list) or not st or len(st) > 20 or not all(isinstance(s, str) and _TOOL.match(s) for s in st):
            return b.reject("schritte: 1–20 Werkzeugnamen")
        for s in st:
            if writing(s):
                b.reasons.append(f"schreibendes_werkzeug: {s}")
    if kind == "reflex":
        if not may_reflex:
            return b.reject("dieser Herausgeber darf keine Reflexe liefern")
        if o.get("reflexart") != "vorher":
            return b.reject("importiert werden nur Reflexe der Art vorher")
        if not isinstance(o.get("name"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", o["name"]):
            return b.reject("name muss a-z, 0-9, _ sein")
        code = o.get("code")
        if not isinstance(code, str) or not code.strip() or len(code) > CODE_MAX:
            return b.reject(f"code fehlt oder ist länger als {CODE_MAX} Zeichen")
        if _INVISIBLE.search(code):
            b.reject("code: unsichtbare oder steuernde Zeichen")
        b.reasons.append("reflex: Quelltext muss von einem Menschen freigegeben werden")
    for field_name, value in _contents(raw, o):
        if hits := anonymize.categories(value):
            return b.reject(f"interna in {field_name}: {', '.join(hits)}")
    b.mem_object = o
    return b

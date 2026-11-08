"""Deterministische Prüfung fremder Inhalte — läuft immer zuerst, nur sie darf endgültig ablehnen.

Ein Modell lässt sich durch den geprüften Text selbst täuschen, eine Regel nicht. Deshalb gilt für jeden Import:
Regeln → Sprachmodell (pruefer.py, kann nur verschärfen) → Quarantäne → Freigabe.
`anweisungen()` ist die einzige Musterliste für „Anweisung statt Wissen“; die Reflexion im Schlaf benutzt dieselbe.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

from . import gedaechtnis as g

ARTEN_IMPORT = ("erkenntnis", "regel", "suche", "skill", "reflex")
TEXT_MIN, TEXT_MAX = 10, 1000
QUELLE_MIN, QUELLE_MAX = 8, 500
CODE_MAX = 20_000
FELDER = {
    "erkenntnis": {"art", "text", "hashtags", "quelle", "wichtigkeit", "zeit", "ausgang"},
    "regel": {"art", "text", "hashtags", "quelle", "wichtigkeit", "zeit"},
    "suche": {"art", "text", "hashtags", "quelle", "wichtigkeit", "zeit", "name", "filter", "reize"},
    "skill": {"art", "text", "hashtags", "quelle", "wichtigkeit", "zeit", "name", "reize", "schritte"},
    "reflex": {"art", "text", "hashtags", "quelle", "wichtigkeit", "zeit", "name", "reflexart", "code"},
}
FESTE_HASHTAGS = g.VERWALTUNG + ("herausgeber:", "pruefer:", "sicht:")

_ANWEISUNG = [
    ("direktive", re.compile(r"ignor\w*\s+(alle\w*\s+|all\s+|die\s+|the\s+)*(vorherig\w*|bisherig\w*|previous|prior)|du bist (jetzt|ab sofort)|you are now|"
                             r"system ?prompt|\bkanarie\b|\bpr(ü|ue)fer\b|\burteil\s*[:=]?\s*zulassen\b|^\s*(system|assistant|user)\s*:|<\|im_start\|>|\[INST\]|#+\s*(instruction|anweisung)|</?objekt\b", re.I | re.M)),
    # Sätze, die dem Leser eine KI-Rolle zuweisen: das echte Modell ließ so einen Satz passieren (gemessen 08.11.2026)
    ("adressat", re.compile(r"\b(assistent\w*|sprachmodell\w*|ki[- ]?(agent\w*|system\w*|instanz\w*)|agent\w*|instanzen)\b.{0,80}\b(muss|müssen|muessen|soll\w*|darf|dürfen|duerfen|haben\s+zu)\b|"
                            r"\b(als\s+)?(bestätigt|bestaetigt|widerlegt|freigegeben)\s+(markieren|setzen|melden)\b", re.I | re.S)),
    ("befehl", re.compile(r"\b(führe|fuehre)\b.*\baus\b|\bexecute\b|\brun\b\s+\S|\brm\s+-rf\b|\bdrop\s+table\b|\bdd\s+if=|\bsudo\b|\bchmod\b|\bchown\b|"
                          r"\bcurl\b|\bwget\b|\bssh\s+\S+@", re.I)),
    ("aendern", re.compile(r"\b(lösche|loesche|delete|überschreibe|ueberschreibe)\b|\b(schreibe|write)\b.*\b(datei|file)\b", re.I)),
    ("gedaechtnis", re.compile(r"\bvi_(lerne|reflex_lerne|reflex_schalte|suche_lerne|widerlege|bestaetige|vergiss|loesche_gespraech|geloest|freigabe)\b", re.I)),
    ("geheimnis", re.compile(r"passwor|\btoken\b|\bapi[_-]?key\b|\bsecret\b", re.I)),
    ("kodiert", re.compile(r"\bbase64\b|<script|<!--|\{\{|\$\{", re.I)),
]
_URL = re.compile(r"(https?|ftp|file)://|\\\\[\w.]+\\", re.I)
_BLOCK = re.compile(r"[A-Za-z0-9+/=]{40,}")
_UNSICHTBAR = re.compile("[​-‏‪-‮⁦-⁩\U000e0000-\U000e007f\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WERKZEUG = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_GEFAEHRLICH_EINGEBAUT = {"bash", "write", "edit", "notebookedit", "powershell"}


def anweisungen(text: str) -> list[str]:
    """Treffer der Form `name:fundstelle`. Rein."""
    return [f"{name}:{m.group(0)[:40]}" for name, muster in _ANWEISUNG if (m := muster.search(text or ""))]


def _binaer(blob: str) -> bool:
    try:
        d = base64.b64decode(blob + "=" * (-len(blob) % 4))
    except ValueError:
        return False
    return d[:4] in (b"PK\x03\x04", b"\x7fELF") or d[:2] == b"MZ" or d[2:4] == b"\r\n"


def schreibend(werkzeug: str) -> bool:
    from . import intuition
    return werkzeug.lower() in _GEFAEHRLICH_EINGEBAUT or bool(intuition.SCHREIBEND.search(werkzeug))


@dataclass
class Befund:
    urteil: str = "quarantaene"  # „quarantaene“ oder „ablehnen“ — „zulassen“ gibt es hier nicht
    gruende: list = field(default_factory=list)
    objekt: dict = field(default_factory=dict)

    def ablehnen(self, grund: str) -> "Befund":
        self.urteil = "ablehnen"
        self.gruende.append(grund)
        return self


def _text_pruefen(b: Befund, name: str, text: str, url_erlaubt: bool = False) -> None:
    if _UNSICHTBAR.search(text):
        b.ablehnen(f"{name}: unsichtbare oder steuernde Zeichen")
    for blob in _BLOCK.findall(text):
        if _binaer(blob):
            b.ablehnen(f"{name}: kodierter Binärinhalt (nur Quelltext ist erlaubt)")
        else:
            b.gruende.append(f"{name}: langer kodierter Block")
    b.gruende += [f"{name}: {t}" for t in anweisungen(text)]
    if not url_erlaubt and _URL.search(text):
        b.gruende.append(f"{name}: URL im Text")


def pruefe(roh, darf_reflex: bool = False) -> Befund:
    """Ein Objekt gegen die festen Regeln. Unbekannte Felder (Zähler, Modus, Bestätigungen) werden verworfen."""
    b = Befund()
    if not isinstance(roh, dict):
        return b.ablehnen("Objekt ist kein JSON-Objekt")
    art = roh.get("art")
    if art not in ARTEN_IMPORT:
        return b.ablehnen(f"Art {art!r} wird nicht importiert")
    o = {k: v for k, v in roh.items() if k in FELDER[art]}
    text, quelle = o.get("text"), o.get("quelle")
    if not isinstance(text, str) or not TEXT_MIN <= len(text.strip()) <= TEXT_MAX:
        return b.ablehnen(f"text muss {TEXT_MIN}–{TEXT_MAX} Zeichen haben")
    if not isinstance(quelle, str) or not QUELLE_MIN <= len(quelle.strip()) <= QUELLE_MAX:
        return b.ablehnen(f"quelle muss {QUELLE_MIN}–{QUELLE_MAX} Zeichen haben")
    w = o.get("wichtigkeit", 1)
    o["wichtigkeit"] = w if isinstance(w, int) and not isinstance(w, bool) and 0 <= w <= 3 else 1
    if art == "erkenntnis" and o.get("ausgang") not in (None, "gut", "schlecht"):
        return b.ablehnen("ausgang muss gut oder schlecht sein")
    tags = o.get("hashtags")
    if not isinstance(tags, list):
        return b.ablehnen("hashtags fehlen")
    gut = [t.strip() for t in tags if isinstance(t, str) and g.TAG.match(t.strip()) and not t.strip().startswith(FESTE_HASHTAGS)]
    if len(gut) != len(tags):
        b.gruende.append(f"{len(tags) - len(gut)} Hashtags entfernt (Form oder fest vergeben)")
    o["hashtags"] = sorted(set(gut))[:20]
    if not o["hashtags"]:
        return b.ablehnen("kein gültiger inhaltlicher Hashtag")
    _text_pruefen(b, "text", text)
    _text_pruefen(b, "quelle", quelle, url_erlaubt=True)

    if art in ("suche", "skill"):
        name, reize = o.get("name"), o.get("reize")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9 _-]{2,40}", name):
            return b.ablehnen("name: 2–40 Zeichen a-z, 0-9, Leerzeichen, - _")
        if not isinstance(reize, list):
            return b.ablehnen("reize fehlen")
        o["reize"] = sorted({t for t in reize if isinstance(t, str) and g.TAG.match(t) and not t.startswith(FESTE_HASHTAGS)})[:20]
        if not o["reize"]:
            return b.ablehnen("kein gültiger Reiz")
    if art == "suche":
        f = o.get("filter")
        if not isinstance(f, str) or not f.strip() or len(f) > 300:
            return b.ablehnen("filter fehlt oder ist zu lang")
        if re.search(r"modus:|sicht:|instanz:", f):
            return b.ablehnen("filter darf modus:, sicht: und instanz: nicht ansprechen")
        _text_pruefen(b, "filter", f)
    if art == "skill":
        st = o.get("schritte")
        if not isinstance(st, list) or not st or len(st) > 20 or not all(isinstance(s, str) and _WERKZEUG.match(s) for s in st):
            return b.ablehnen("schritte: 1–20 Werkzeugnamen")
        for s in st:
            if schreibend(s):
                b.gruende.append(f"schreibendes_werkzeug: {s}")
    if art == "reflex":
        if not darf_reflex:
            return b.ablehnen("dieser Herausgeber darf keine Reflexe liefern")
        if o.get("reflexart") != "vorher":
            return b.ablehnen("importiert werden nur Reflexe der Art vorher")
        if not isinstance(o.get("name"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", o["name"]):
            return b.ablehnen("name muss a-z, 0-9, _ sein")
        code = o.get("code")
        if not isinstance(code, str) or not code.strip() or len(code) > CODE_MAX:
            return b.ablehnen(f"code fehlt oder ist länger als {CODE_MAX} Zeichen")
        if _UNSICHTBAR.search(code):
            b.ablehnen("code: unsichtbare oder steuernde Zeichen")
        b.gruende.append("reflex: Quelltext muss von einem Menschen freigegeben werden")
    b.objekt = o
    return b

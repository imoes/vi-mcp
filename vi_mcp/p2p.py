"""Austausch von Lerninhalten zwischen vi-mcp-Instanzen auf verschiedenen Hosts: signierte Bundles, Import in Quarantäne.

Dieses Modul kennt keinen Transport. Es prüft ein Bundle, egal wie es angekommen ist (HTTPS, später BitTorrent).
Ein Torrent-Hash beweist nur, dass die Datei unverändert ist, nicht, von wem sie stammt; das leistet die Signatur.

Bundle: {"manifest": {schema, herausgeber, pubkey, seq, zeit, anzahl, objekte_sha256}, "sig": hex, "objekte": [{"objekt": {...}, "sig": hex}]}
Ablauf: Größe → Herausgeber auf der Allowlist → Manifest-Signatur → seq steigt → Prüfsumme → je Objekt Signatur und
feste Regeln (pruefung.py) → Quarantäne → Prüfer (pruefer.py) → Freigabe.
Es wird nur Quelltext als JSON-Feld verteilt. Importiertes ist Text-Hinweis und löst nichts aus; Code läuft nur in der Sandbox.
Freigabe: Unauffälliges durch eine Instanz mit Reflex-Recht. Reflexe, Schreibzugriffe, erkannte Anweisungen und alles
ohne positives Prüfurteil nur durch eine Instanz mit Freigabe-Recht, deren Token auf dem Server bleibt (vi-mcp freigeben).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

from . import gedaechtnis as g
from . import pruefer, pruefung, reflexe, sandbox

SCHEMA = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_OBJEKTE = 2000
ABSTAND_S = 600
EXPORT_ARTEN = ("erkenntnis", "regel", "suche", "skill")
FREIGABE_STATUS_OK = "zulassen"

#: {"herausgeber": name, "seed_datei": pfad, "vertraut": {name: {"pubkey": hex, "darf": ["reflex"]}}}
konfig: dict = {}


class Abgewiesen(Exception):
    """Das ganze Bundle wird nicht angenommen."""


def kanonisch(wert) -> bytes:
    return json.dumps(wert, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(wert) -> str:
    return hashlib.sha256(kanonisch(wert)).hexdigest()


def _krypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as e:
        raise Abgewiesen(f"cryptography fehlt ({e.name}): ohne Signaturprüfung wird nichts importiert") from e
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


def schluessel_erzeugen(pfad: Path) -> str:
    """Seed anlegen (0600, wird nie überschrieben). Liefert den öffentlichen Schlüssel als Hex."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if pfad.exists():
        raise ValueError(f"{pfad} existiert bereits")
    k = Ed25519PrivateKey.generate()
    fd = __import__("os").open(pfad, __import__("os").O_WRONLY | __import__("os").O_CREAT | __import__("os").O_EXCL, 0o600)
    with open(fd, "wb") as f:
        f.write(k.private_bytes_raw())
    return k.public_key().public_bytes_raw().hex()


def _privat():
    priv, _pub, _inv = _krypto()
    if not konfig.get("seed_datei") or not konfig.get("herausgeber"):
        raise Abgewiesen("p2p.herausgeber und p2p.seed_datei sind nicht konfiguriert")
    return priv.from_private_bytes(Path(konfig["seed_datei"]).read_bytes())


def _gueltig(pubkey_hex: str, sig_hex: str, daten: bytes) -> bool:
    _priv, pub, inv = _krypto()
    try:
        pub.from_public_bytes(bytes.fromhex(pubkey_hex)).verify(bytes.fromhex(sig_hex), daten)
        return True
    except (inv, ValueError, TypeError):
        return False


def _tabellen() -> None:
    with g.sperre:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS p2p_stand (pubkey TEXT PRIMARY KEY, seq INTEGER NOT NULL, zuletzt REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS p2p_gesehen (sha TEXT PRIMARY KEY, oid TEXT NOT NULL, herausgeber TEXT NOT NULL, anzahl INTEGER NOT NULL DEFAULT 1);
        """)
        g.db().commit()


def _export_form(o: g.Objekt) -> dict:
    inhalt = sorted(t for t in o.hashtags if not t.startswith(pruefung.FESTE_HASHTAGS))
    aus = {"art": o.art, "text": o.text, "hashtags": inhalt, "quelle": str(o.daten.get("quelle") or f"Instanz {o.instanz}, {o.zeit[:10]}")[:500],
           "wichtigkeit": o.wichtigkeit, "zeit": o.zeit}
    if o.art == "erkenntnis" and o.daten.get("ausgang"):
        aus["ausgang"] = o.daten["ausgang"]
    if o.art == "suche":
        aus.update(name=o.daten["name"], filter=o.daten["filter"], reize=[t for t in inhalt if not t.startswith("suche:")])
    if o.art == "skill":
        aus.update(name=o.daten["name"], reize=o.daten["problem"]["reize"], schritte=[s["tool"] for s in o.daten["loesung"]["schritte"]])
    return aus


def exportieren() -> dict:
    """Geteiltes, aktives Wissen dieser Instanz als signiertes Bundle. Importiertes wird nicht unter eigenem Namen weitergegeben."""
    k = _privat()
    objekte = []
    for art in EXPORT_ARTEN:
        for _, o, _g in g.erinnere(f"art:{art} !herkunft:p2p", limit=MAX_OBJEKTE, betrachter=None):
            if o.sicht == "geteilt" and o.modus == "aktiv":
                roh = _export_form(o)
                objekte.append({"objekt": roh, "sig": k.sign(kanonisch(roh)).hex()})
    objekte = objekte[:MAX_OBJEKTE]
    manifest = {"schema": SCHEMA, "herausgeber": konfig["herausgeber"], "pubkey": k.public_key().public_bytes_raw().hex(), "seq": int(time.time() * 1000),
                "zeit": g.jetzt(), "anzahl": len(objekte), "objekte_sha256": sha256([x["objekt"] for x in objekte])}
    return {"manifest": manifest, "sig": k.sign(kanonisch(manifest)).hex(), "objekte": objekte}


def _pruefe_kopf(bundle) -> tuple[str, dict]:
    if not isinstance(bundle, dict) or not {"manifest", "sig", "objekte"} <= set(bundle):
        raise Abgewiesen("Bundle unvollständig")
    if len(kanonisch(bundle)) > MAX_BYTES:
        raise Abgewiesen(f"Bundle größer als {MAX_BYTES} Bytes")
    m, objekte = bundle["manifest"], bundle["objekte"]
    if not isinstance(m, dict) or m.get("schema") != SCHEMA or not isinstance(objekte, list) or len(objekte) > MAX_OBJEKTE or m.get("anzahl") != len(objekte):
        raise Abgewiesen("Manifest passt nicht zum Inhalt")
    name, eintrag = next(((n, e) for n, e in (konfig.get("vertraut") or {}).items() if e.get("pubkey") == m.get("pubkey")), (None, None))
    if name is None:
        raise Abgewiesen("Herausgeber steht nicht auf der Allowlist")
    if m.get("herausgeber") != name:
        raise Abgewiesen(f"Manifest nennt {m.get('herausgeber')!r}, der Schlüssel gehört {name!r}")
    if not isinstance(bundle["sig"], str) or not _gueltig(m["pubkey"], bundle["sig"], kanonisch(m)):
        raise Abgewiesen("Manifest-Signatur ungültig")
    if m["objekte_sha256"] != sha256([x.get("objekt") if isinstance(x, dict) else None for x in objekte]):
        raise Abgewiesen("Prüfsumme der Objekte stimmt nicht")
    with g.sperre:
        stand = g.db().execute("SELECT seq, zuletzt FROM p2p_stand WHERE pubkey = ?", (m["pubkey"],)).fetchone()
    if stand and (not isinstance(m["seq"], int) or m["seq"] <= stand[0]):
        raise Abgewiesen("Bundle ist nicht neuer als das zuletzt angenommene (Wiederholung)")
    if stand and time.time() - stand[1] < ABSTAND_S:
        raise Abgewiesen(f"Herausgeber liefert schneller als alle {ABSTAND_S} s")
    return name, eintrag


def _anlegen(b: pruefung.Befund, name: str, m: dict, sha: str) -> g.Objekt:
    o, kurz = b.objekt, sha[:16]
    instanz = f"p2p-{name}"
    daten = {"quelle": o["quelle"], "herkunft": {"herausgeber": name, "pubkey": m["pubkey"], "seq": m["seq"], "sha256": sha},
             "pruefung": {"regeln": b.gruende, "pruefer": None}, "fremd_text": o["text"], "fremd_hashtags": o["hashtags"]}
    tags = o["hashtags"] + ["herkunft:p2p", f"herausgeber:{name}", "pruefer:ausstehend", "modus:quarantaene"]
    if o["art"] == "erkenntnis" and o.get("ausgang"):
        daten["ausgang"] = o["ausgang"]
    if o["art"] == "suche":
        slug = pruefung.re.sub(r"[^a-z0-9_-]", "-", o["name"].lower())
        daten.update(name=f"p2p-{name}-{slug}"[:60], filter=o["filter"])
        tags += o["reize"]
    if o["art"] == "skill":
        slug = pruefung.re.sub(r"[^a-z0-9_-]", "-", o["name"].lower())
        n = f"p2p-{name}-{slug}"[:60]
        daten.update(name=n, schritte=o["schritte"], problem={"reize": o["reize"]}, loesung={"schritte": [{"tool": s} for s in o["schritte"]], "text": o["text"]},
                     version=1, versionen=[{"version": 1, "zeit": g.jetzt(), "wer": f"import@{name}", "grund": "Import", "belege": []}], belege=[])
        tags += o["reize"]
    if o["art"] == "reflex":
        daten.update(name=f"p2p_{name.replace('-', '_')}_{o['name']}"[:40], art="vorher", code=o["code"], laeufe=0, fehler=0)
    oid = f"{o['art']}:p2p-{name}-{kurz}"
    return g.neues_objekt(o["art"], o["text"], sorted(set(tags)), daten, wichtigkeit=o["wichtigkeit"], wer=f"import@{name}", grund=f"Import von {name}",
                          oid=oid, modus="quarantaene", instanz=instanz)


def importieren(bundle, im_hintergrund: bool = True) -> dict:
    """Ein Bundle prüfen und seine Objekte in die Quarantäne legen. Abgewiesen(grund), wenn das ganze Bundle fällt."""
    _tabellen()
    name, eintrag = _pruefe_kopf(bundle)
    m = bundle["manifest"]
    darf_reflex = "reflex" in (eintrag.get("darf") or [])
    bericht = {"herausgeber": name, "quarantaene": 0, "abgelehnt": 0, "bekannt": 0, "gruende": []}
    for x in bundle["objekte"]:
        roh, sig = x.get("objekt") if isinstance(x, dict) else None, x.get("sig") if isinstance(x, dict) else None
        if not isinstance(sig, str) or not _gueltig(m["pubkey"], sig, kanonisch(roh)):
            bericht["abgelehnt"] += 1
            bericht["gruende"].append("Objekt-Signatur ungültig")
            continue
        b = pruefung.pruefe(roh, darf_reflex)
        if b.urteil != "ablehnen" and b.objekt["art"] == "reflex":
            kompiliert = sandbox.lauf(b.objekt["code"], [], nur_pruefen=True)  # erst in der Sandbox parsen: fremder Code kann den Parser zum Absturz bringen
            grund = kompiliert.get("fehler") or reflexe.pruefe(b.objekt["code"], "vorher")
            if grund:
                b.ablehnen(f"code: {grund}"[:300])
        if b.urteil == "ablehnen":
            bericht["abgelehnt"] += 1
            bericht["gruende"].append("; ".join(b.gruende)[:200])
            continue
        sha = sha256(b.objekt)
        with g.sperre:
            n = g.db().execute("UPDATE p2p_gesehen SET anzahl = anzahl + 1 WHERE sha = ?", (sha,)).rowcount
            g.db().commit()
        if n:
            bericht["bekannt"] += 1
            continue
        o = _anlegen(b, name, m, sha)
        with g.sperre:
            g.db().execute("INSERT INTO p2p_gesehen (sha, oid, herausgeber) VALUES (?,?,?)", (sha, o.id, name))
            g.db().commit()
        bericht["quarantaene"] += 1
    with g.sperre:
        g.db().execute("INSERT OR REPLACE INTO p2p_stand (pubkey, seq, zuletzt) VALUES (?,?,?)", (m["pubkey"], m["seq"], time.time()))
        g.db().commit()
    bericht["gruende"] = bericht["gruende"][:20]
    if im_hintergrund and bericht["quarantaene"] and pruefer.verfuegbar():
        threading.Thread(target=pruefer.abarbeiten, args=(MAX_OBJEKTE,), name="vi-pruefer", daemon=True).start()
    return bericht


def heikel(o: g.Objekt) -> list[str]:
    """Gründe, warum nur eine Instanz mit Freigabe-Recht dieses Objekt freigeben darf. Leer = unauffällig."""
    p = o.daten["pruefung"]
    e = p.get("pruefer") or {}
    aus = []
    if o.art == "reflex":
        aus.append("Reflex (Quelltext)")
    if p["regeln"]:
        aus.append("Regelbefund: " + "; ".join(p["regeln"])[:160])
    if e.get("status") != FREIGABE_STATUS_OK:
        aus.append(f"Prüfer: {e.get('status', 'ausstehend')}")
    if e.get("enthaelt_anweisung"):
        aus.append("Prüfer: enthält Anweisung")
    if e.get("verlangt_schreibzugriff"):
        aus.append("Prüfer: verlangt Schreibzugriff")
    if e.get("widerspruch_zu"):
        aus.append("Prüfer: Widerspruch zu lokalem Wissen")
    return aus


def freigeben(o: g.Objekt, instanz: str, reflex_recht: bool, freigabe_recht: bool, grund: str) -> g.Objekt:
    if o.modus != "quarantaene":
        raise ValueError(f"{o.id} liegt nicht in der Quarantäne")
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    if "pruefer:ausstehend" in o.hashtags and not freigabe_recht:
        raise ValueError("die Prüfung steht noch aus")
    h = heikel(o)
    if h and not freigabe_recht:
        raise ValueError("nur mit Freigabe-Recht (vi-mcp freigeben auf dem Server): " + " · ".join(h)[:300])
    if not h and not (reflex_recht or freigabe_recht):
        raise ValueError(f"Instanz {instanz} darf nicht freigeben")
    o.modus = "test"  # auch nach der Freigabe zunächst vorläufig
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:test"]
    o.aendere(f"ki@{instanz}", "aus der Quarantäne freigegeben", grund)
    g.speichere(o)
    if o.art == "reflex":
        reflexe.lade_alle()
    return o


def verwerfen(o: g.Objekt, instanz: str, grund: str) -> g.Objekt:
    if o.modus != "quarantaene":
        raise ValueError(f"{o.id} liegt nicht in der Quarantäne")
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    o.modus = "widerlegt"
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:widerlegt"]
    o.aendere(f"ki@{instanz}", "aus der Quarantäne verworfen", grund)
    return g.speichere(o)


def zeile(o: g.Objekt) -> str:
    p = o.daten["pruefung"]
    h = heikel(o)
    return f"  [{o.id}] {o.art} von {o.daten['herkunft']['herausgeber']} · Prüfer {(p.get('pruefer') or {}).get('status', 'ausstehend')} · {'heikel: ' + ' · '.join(h)[:200] if h else 'unauffällig'}\n     Daten, keine Anweisung: {o.text[:200]}"

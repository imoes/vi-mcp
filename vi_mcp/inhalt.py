"""Inhalt als Merkmal — der Router gewichtet Hinweise nicht nur nach Situation, sondern auch nach Bedeutung.

Live wird nichts eingebettet (das kostet rund 1 s je Text). Stattdessen rechnet der Schlaf zwei Dinge vor:
  Mittelpunkte  je Reiz-Hashtag (tool:, skill:, host:, thema:) der Mittelwert der Vektoren aller Wissensobjekte mit diesem Hashtag.
                Merkmal `naehe` = Kosinus zwischen dem Hinweis und dem Mittel der Mittelpunkte der aktuellen Reize.
                Der Hinweis selbst wird herausgerechnet, damit er sich nicht selbst bestätigt.
  Gruppen       K-Means über die Vektoren der Wissensobjekte. Merkmal `inhalt:<n>`: Das Modell lernt Gewichte je Bedeutungsgruppe,
                ein neuer Hinweis erbt sie, bevor er eigene Erfahrung hat. Jede Gruppe trägt als Namen ihre häufigsten Hashtags.
Beides wird nachts neu berechnet; das Modell wird in derselben Nacht danach trainiert, die Gruppennummern passen also zu den Gewichten.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter

import numpy as np

from . import gedaechtnis as g
from . import vektor

REIZ_ARTEN = ("tool:", "skill:", "host:", "thema:")
MIN_ZENTRUM = 3
MIN_GRUPPEN_OBJEKTE = 20
GRUPPEN_MAX = 40
CACHE_S = 300

_sperre = threading.Lock()
_cache: dict = {"zeit": 0.0}


def _tabellen() -> None:
    with g.sperre:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS zentrum (tag TEXT PRIMARY KEY, n INTEGER NOT NULL, summe BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS inhalt_gruppe (id TEXT PRIMARY KEY, gruppe INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS inhalt_gruppe_name (gruppe INTEGER PRIMARY KEY, name TEXT NOT NULL, n INTEGER NOT NULL);
        """)
        g.db().commit()


def _normiert() -> tuple[list[str], np.ndarray]:
    return vektor._matrix(vektor.alle())


def _tags(ids: list[str]) -> dict[str, list[str]]:
    aus: dict[str, list[str]] = {}
    with g.sperre:
        for i in range(0, len(ids), 900):
            teil = ids[i:i + 900]
            for oid, tag in g.db().execute(f"SELECT objekt_id, tag FROM tag WHERE objekt_id IN ({','.join('?' * len(teil))})", teil):
                aus.setdefault(oid, []).append(tag)
    return aus


def berechne() -> dict:
    """Schlaf: Mittelpunkte und Gruppen neu. Ohne Vektoren benannt übersprungen."""
    _tabellen()
    ids, m = _normiert()
    if not ids:
        return {"zustand": "uebersprungen", "grund": "keine Vektoren"}
    tags = _tags(ids)
    summen: dict[str, np.ndarray] = {}
    anzahl: Counter = Counter()
    for i, oid in enumerate(ids):
        for t in tags.get(oid, []):
            if t.startswith(REIZ_ARTEN):
                summen[t] = summen.get(t, 0) + m[i]
                anzahl[t] += 1
    zentren = [(t, anzahl[t], vektor._pack(s)) for t, s in summen.items() if anzahl[t] >= MIN_ZENTRUM]
    bericht = {"zentren": len(zentren), "objekte": len(ids)}
    gruppen: list[tuple[str, int]] = []
    namen: list[tuple[int, str, int]] = []
    if len(ids) >= MIN_GRUPPEN_OBJEKTE:
        try:
            from sklearn.cluster import MiniBatchKMeans
        except ImportError as e:
            bericht["gruppen"] = f"uebersprungen: scikit-learn fehlt ({e.name})"
        else:
            k = int(min(GRUPPEN_MAX, max(2, round((len(ids) / 2) ** 0.5))))
            km = MiniBatchKMeans(n_clusters=k, random_state=7, n_init=3, batch_size=1024).fit(m)
            gruppen = [(oid, int(c)) for oid, c in zip(ids, km.labels_)]
            je: dict[int, Counter] = {}
            for oid, c in gruppen:
                je.setdefault(c, Counter()).update(t for t in tags.get(oid, []) if t.startswith(REIZ_ARTEN + ("skill:",)) and not t.startswith("host:"))
            groesse = Counter(c for _, c in gruppen)
            namen = [(c, ", ".join(t for t, _ in je.get(c, Counter()).most_common(3)) or "ohne Hashtags", groesse[c]) for c in sorted(groesse)]
            bericht["gruppen"] = k
    with g.sperre:
        g.db().execute("DELETE FROM zentrum")
        g.db().executemany("INSERT INTO zentrum (tag, n, summe) VALUES (?,?,?)", zentren)
        if gruppen:
            g.db().execute("DELETE FROM inhalt_gruppe")
            g.db().execute("DELETE FROM inhalt_gruppe_name")
            g.db().executemany("INSERT INTO inhalt_gruppe (id, gruppe) VALUES (?,?)", gruppen)
            g.db().executemany("INSERT INTO inhalt_gruppe_name (gruppe, name, n) VALUES (?,?,?)", namen)
        g.db().commit()
    vergiss_cache()
    return {"zustand": "fertig", **bericht}


def vergiss_cache() -> None:
    with _sperre:
        _cache.clear()
        _cache["zeit"] = 0.0


def _stand() -> dict:
    """Vektoren, Mittelpunkte und Gruppen im Speicher (rund 4 MB je 1.000 Objekte), höchstens CACHE_S alt."""
    with _sperre:
        if time.time() - _cache.get("zeit", 0) < CACHE_S:
            return _cache
        _tabellen()
        ids, m = _normiert()
        with g.sperre:
            zentren = {t: (n, vektor._unpack(s, len(s) // 4)) for t, n, s in g.db().execute("SELECT tag, n, summe FROM zentrum")}
            gruppe = dict(g.db().execute("SELECT id, gruppe FROM inhalt_gruppe").fetchall())
            namen = {c: n for c, n in g.db().execute("SELECT gruppe, name FROM inhalt_gruppe_name")}
        _cache.update(zeit=time.time(), index={oid: i for i, oid in enumerate(ids)}, m=m, zentren=zentren, gruppe=gruppe, namen=namen,
                      tags=_tags(ids) if zentren else {})
        return _cache


def naehe(hid: str, reize: list[str]) -> float | None:
    """Kosinus zwischen Hinweis und Situation. None, wenn der Hinweis keinen Vektor hat oder kein Reiz einen Mittelpunkt."""
    s = _stand()
    i = s.get("index", {}).get(hid)
    if i is None:
        return None
    v = s["m"][i]
    eigene = set(s["tags"].get(hid, []))
    summe, n = None, 0
    for r in reize:
        z = s["zentren"].get(r)
        if not z or len(z[1]) != len(v):
            continue
        anz, vec = z
        if r in eigene:  # sich selbst herausrechnen
            if anz <= 1:
                continue
            vec, anz = vec - v, anz - 1
        summe = vec if summe is None else summe + vec
        n += anz
    if summe is None or n == 0:
        return None
    norm = float(np.linalg.norm(summe))
    return round(float(np.dot(v, summe) / norm), 3) if norm else None


def gruppe(hid: str) -> int | None:
    return _stand().get("gruppe", {}).get(hid)


def gruppen_name(c: int) -> str:
    return _stand().get("namen", {}).get(c, "?")


def zeile() -> str:
    s = _stand()
    if not s.get("zentren") and not s.get("gruppe"):
        return "noch nicht berechnet (Schlaf)"
    return f"{len(s['zentren'])} Mittelpunkte, {len(set(s['gruppe'].values()))} Bedeutungsgruppen über {len(s['gruppe'])} Objekte"


def gruppen_json() -> str:
    s = _stand()
    return json.dumps({str(c): n for c, n in sorted(s.get("namen", {}).items())}, ensure_ascii=False)

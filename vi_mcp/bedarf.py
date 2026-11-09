"""Training bei Bedarf (seit 0.20.0) — statt erst im nächtlichen Schlaf.

Gemessen am 09.11.2026 auf einer Kopie der Produktivdaten (5.118 Objekte, 1.310 Beobachtungen): Router-Training
(LogisticRegression) 68 ms, Bandit-Zähler 30 ms, KMeans-Inhaltsgruppen 2,4 s. Das ist schnell genug, um nach jeder neuen
Erfahrung zu lernen. Ein Hintergrund-Thread läuft, sobald `anstossen()` gerufen wurde, frühestens ABSTAND_S nach dem
letzten Lauf (mehrere Erfahrungen in einer Minute ergeben einen Lauf). Reihenfolge:

  1. fehlende Vektoren einbetten (höchstens VEKTOR_MAX_S je Lauf; bleibt ein Rest, folgt sofort der nächste Lauf)
  2. Nähe-Kanten für die neuen Vektoren (inkrementell, vektor.naehe_kanten)
  3. Inhaltsgruppen (KMeans) neu, wenn seit dem letzten Mal KMEANS_AB_NEU Vektoren dazukamen
  4. Bandit-Zähler neu (bandit.neu_berechnen)
  5. Router neu trainieren (lernen.trainiere)

Der Schlaf behält, was ein Sprachmodell braucht oder Erfahrungen verdichtet (Reflexion, Abstraktion, Skills, Scorer, Lager).
Training und Schlaf teilen sich TRAINING, damit nie zwei Läufe gleichzeitig dasselbe Modell schreiben.
"""
from __future__ import annotations

import threading
import time

from . import gedaechtnis as g
from .protokoll import log

ABSTAND_S = 60
VEKTOR_MAX_S = 120
KMEANS_AB_NEU = 200
TRAINING = threading.Lock()

stand: dict = {"laeufe": 0, "zuletzt": None, "grund": None, "dauer_ms": None, "schritte": {}, "fehler": None, "angestossen": 0,
               "vektoren_seit_kmeans": 0}
_ereignis = threading.Event()
_halt = threading.Event()
_gruende: list[str] = []
_thread: threading.Thread | None = None


def anstossen(grund: str) -> None:
    """Neue Daten sind da (Erfahrung gemeldet, Wissen gelernt). Ohne laufenden Thread (Tests, Werkzeuge) nur gezählt."""
    stand["angestossen"] += 1
    if len(_gruende) < 50:
        _gruende.append(grund)
    _ereignis.set()


def lauf(grund: str = "von Hand") -> dict:
    """Ein Trainingslauf, synchron. Liefert die Schritte mit Dauer; Fehler eines Schritts werden benannt, die übrigen laufen weiter."""
    from . import bandit, inhalt, lernen, vektor
    schritte: dict = {}
    t_ges = time.monotonic()

    def schritt(name, fn):
        t0 = time.monotonic()
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001 — benannt im Stand
            r = {"zustand": "fehler", "grund": f"{type(exc).__name__}: {exc}"[:200]}
            log(f"Training bei Bedarf: {name} scheiterte: {exc}")
        kurz = {k: v for k, v in (r or {}).items() if k in ("zustand", "neu", "offen", "kanten_neu", "neu_verglichen", "gruppen", "hinweise",
                                                              "n", "merkmale", "auc_holdout", "grund")} if isinstance(r, dict) else {}
        schritte[name] = {**kurz, "ms": int((time.monotonic() - t0) * 1000)}
        return r

    rest = 0
    with TRAINING:
        if vektor.verfuegbar():
            v = schritt("vektoren", lambda: vektor.nachziehen(max_s=VEKTOR_MAX_S))
            rest = int((v or {}).get("offen") or 0)
            stand["vektoren_seit_kmeans"] += int((v or {}).get("neu") or 0)
            schritt("naehe", vektor.naehe_kanten)
            if stand["vektoren_seit_kmeans"] >= KMEANS_AB_NEU:
                schritt("inhalt", inhalt.berechne)
                stand["vektoren_seit_kmeans"] = 0
        schritt("hinweise", bandit.neu_berechnen)
        schritt("lernen", lambda: lernen.trainiere(f"Bedarf: {grund}"))
    dauer = int((time.monotonic() - t_ges) * 1000)
    stand.update({"laeufe": stand["laeufe"] + 1, "zuletzt": g.jetzt(), "grund": grund, "dauer_ms": dauer, "schritte": schritte,
                  "fehler": next((f"{k}: {s['grund']}" for k, s in schritte.items() if s.get("zustand") == "fehler"), None)})
    if rest:  # Rückstand an Vektoren: gleich weiter, nicht erst bei der nächsten Erfahrung
        _ereignis.set()
    return {"grund": grund, "dauer_ms": dauer, "schritte": schritte, "vektoren_offen": rest}


def _schleife() -> None:
    letzter = 0.0
    while not _halt.is_set():
        if not _ereignis.wait(timeout=5):
            continue
        warte = ABSTAND_S - (time.monotonic() - letzter)
        if warte > 0 and _halt.wait(warte):
            return
        _ereignis.clear()
        grund = ", ".join(sorted(set(_gruende)))[:200] or "angestoßen"
        _gruende.clear()
        try:
            lauf(grund)
        except Exception as exc:  # noqa: BLE001 — Thread darf nicht sterben
            stand["fehler"] = f"{type(exc).__name__}: {exc}"[:300]
            log(f"Training bei Bedarf scheiterte: {exc}")
        letzter = time.monotonic()


def starte() -> threading.Thread:
    global _thread
    _halt.clear()
    _thread = threading.Thread(target=_schleife, name="vi-bedarf", daemon=True)
    _thread.start()
    return _thread


def halte() -> None:
    _halt.set()
    _ereignis.set()


def zeile() -> str:
    if not stand["laeufe"]:
        return f"Training bei Bedarf: noch kein Lauf ({stand['angestossen']}× angestoßen)"
    s = stand["schritte"]
    teile = [f"{k} {v['ms']} ms" for k, v in s.items()]
    return (f"Training bei Bedarf: {stand['laeufe']} Läufe, zuletzt {str(stand['zuletzt'])[:16]} UTC ({stand['grund']}), {stand['dauer_ms']} ms: "
            + ", ".join(teile) + (f" · Fehler: {stand['fehler']}" if stand["fehler"] else ""))

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

from . import memory as g
from .log_output import log

INTERVAL_S = 60
VECTOR_MAX_S = 120
KMEANS_MIN_NEW = 200
TRAINING = threading.Lock()

progress: dict = {"laeufe": 0, "zuletzt": None, "grund": None, "dauer_ms": None, "schritte": {}, "fehler": None, "angestossen": 0,
               "vektoren_seit_kmeans": 0}
_event = threading.Event()
_halt = threading.Event()
_reasons: list[str] = []
_thread: threading.Thread | None = None


def nudge(reason: str) -> None:
    """Neue Daten sind da (Erfahrung gemeldet, Wissen gelernt). Ohne laufenden Thread (Tests, Werkzeuge) nur gezählt."""
    progress["angestossen"] += 1
    if len(_reasons) < 50:
        _reasons.append(reason)
    _event.set()


def run(reason: str = "von Hand") -> dict:
    """Ein Trainingslauf, synchron. Liefert die Schritte mit Dauer; Fehler eines Schritts werden benannt, die übrigen laufen weiter."""
    from . import bandit, content, learning, vector
    steps: dict = {}
    t_total = time.monotonic()

    def step(name, fn):
        t0 = time.monotonic()
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001 — benannt im Stand
            r = {"zustand": "fehler", "grund": f"{type(exc).__name__}: {exc}"[:200]}
            log(f"Training bei Bedarf: {name} scheiterte: {exc}")
        short = {k: v for k, v in (r or {}).items() if k in ("zustand", "neu", "offen", "kanten_neu", "neu_verglichen", "gruppen", "hinweise",
                                                              "n", "merkmale", "auc_holdout", "grund", "pause_s", "gekappt")} if isinstance(r, dict) else {}
        steps[name] = {**short, "ms": int((time.monotonic() - t0) * 1000)}
        return r

    rest = 0
    with TRAINING:
        if vector.available():
            v = step("vektoren", lambda: vector.catch_up(max_s=VECTOR_MAX_S))
            rest = int((v or {}).get("offen") or 0)
            progress["vektoren_seit_kmeans"] += int((v or {}).get("neu") or 0)
            step("naehe", vector.proximity_edges)
            if progress["vektoren_seit_kmeans"] >= KMEANS_MIN_NEW:
                step("inhalt", content.compute)
                progress["vektoren_seit_kmeans"] = 0
        step("hinweise", bandit.recompute)
        step("lernen", lambda: learning.train(f"Bedarf: {reason}"))
    duration = int((time.monotonic() - t_total) * 1000)
    progress.update({"laeufe": progress["laeufe"] + 1, "zuletzt": g.now(), "grund": reason, "dauer_ms": duration, "schritte": steps,
                  "fehler": next((f"{k}: {s['grund']}" for k, s in steps.items() if s.get("zustand") == "fehler"), None)})
    if rest:  # Rückstand an Vektoren: gleich weiter, nicht erst bei der nächsten Erfahrung
        _event.set()
    return {"grund": reason, "dauer_ms": duration, "schritte": steps, "vektoren_offen": rest}


def _main_loop() -> None:
    last = 0.0
    while not _halt.is_set():
        if not _event.wait(timeout=5):
            continue
        wait = INTERVAL_S - (time.monotonic() - last)
        if wait > 0 and _halt.wait(wait):
            return
        _event.clear()
        reason = ", ".join(sorted(set(_reasons)))[:200] or "angestoßen"
        _reasons.clear()
        try:
            run(reason)
        except Exception as exc:  # noqa: BLE001 — Thread darf nicht sterben
            progress["fehler"] = f"{type(exc).__name__}: {exc}"[:300]
            log(f"Training bei Bedarf scheiterte: {exc}")
        last = time.monotonic()


def launch() -> threading.Thread:
    global _thread
    _halt.clear()
    _thread = threading.Thread(target=_main_loop, name="vi-bedarf", daemon=True)
    _thread.start()
    return _thread


def stop_background() -> None:
    _halt.set()
    _event.set()


def line() -> str:
    if not progress["laeufe"]:
        return f"Training bei Bedarf: noch kein Lauf ({progress['angestossen']}× angestoßen)"
    s = progress["schritte"]
    parts = [f"{k} {v['ms']} ms" for k, v in s.items()]
    return (f"Training bei Bedarf: {progress['laeufe']} Läufe, zuletzt {str(progress['zuletzt'])[:16]} UTC ({progress['grund']}), {progress['dauer_ms']} ms: "
            + ", ".join(parts) + (f" · Fehler: {progress['fehler']}" if progress["fehler"] else ""))

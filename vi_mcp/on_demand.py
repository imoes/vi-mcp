"""Training on demand (since 0.20.0) — instead of only in the nightly sleep.

Measured on 09.11.2026 on a copy of the production data (5,118 objects, 1,310 observations): router training
(LogisticRegression) 68 ms, bandit counters 30 ms, KMeans content groups 2.4 s. That is fast enough to learn after every new
experience. A background thread runs as soon as `nudge()` was called, at the earliest INTERVAL_S after the
last run (several experiences within a minute result in one run). Order:

  1. embed missing vectors (at most VECTOR_MAX_S per run; if a rest remains, the next run follows immediately)
  2. proximity edges for the new vectors (incremental, vector.proximity_edges)
  3. recompute content groups (KMeans) if KMEANS_MIN_NEW vectors were added since the last time
  4. recompute bandit counters (bandit.recompute)
  5. retrain the router (learning.train)

Sleep keeps what needs a language model or condenses experiences (reflection, abstraction, skills, scorer, archive).
Training and sleep share TRAINING so that two runs never write the same model at the same time.
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
    """New data has arrived (experience reported, knowledge learned). Without a running thread (tests, tools) only counted."""
    progress["angestossen"] += 1
    if len(_reasons) < 50:
        _reasons.append(reason)
    _event.set()


def run(reason: str = "by hand") -> dict:
    """One training run, synchronous. Returns the steps with duration; an error in one step is named, the others continue."""
    from . import bandit, content, learning, vector
    steps: dict = {}
    t_total = time.monotonic()

    def step(name, fn):
        t0 = time.monotonic()
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001 — named in the progress state
            r = {"zustand": "fehler", "grund": f"{type(exc).__name__}: {exc}"[:200]}
            log(f"Training on demand: {name} failed: {exc}")
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
        step("lernen", lambda: learning.train(f"on demand: {reason}"))
    duration = int((time.monotonic() - t_total) * 1000)
    progress.update({"laeufe": progress["laeufe"] + 1, "zuletzt": g.now(), "grund": reason, "dauer_ms": duration, "schritte": steps,
                  "fehler": next((f"{k}: {s['grund']}" for k, s in steps.items() if s.get("zustand") == "fehler"), None)})
    if rest:  # backlog of vectors: continue right away, not only at the next experience
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
        reason = ", ".join(sorted(set(_reasons)))[:200] or "nudged"
        _reasons.clear()
        try:
            run(reason)
        except Exception as exc:  # noqa: BLE001 — the thread must not die
            progress["fehler"] = f"{type(exc).__name__}: {exc}"[:300]
            log(f"Training on demand failed: {exc}")
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
        return f"Training on demand: no run yet (nudged {progress['angestossen']}×)"
    s = progress["schritte"]
    parts = [f"{k} {v['ms']} ms" for k, v in s.items()]
    return (f"Training on demand: {progress['laeufe']} runs, last {str(progress['zuletzt'])[:16]} UTC ({progress['grund']}), {progress['dauer_ms']} ms: "
            + ", ".join(parts) + (f" · error: {progress['fehler']}" if progress["fehler"] else ""))

"""The incubator (0.62.0): a VI matures in operation until measured criteria say it is ready to fine-tune an AI.

The user (13.11.2026): "Wenn eine VI aus dem Inkubator kommt, soll man damit dann eine KI fine-tunen." — decided: a maturity phase
with measurement. A VI (the whole memory or one index, a project or special VI) stays in the incubator while it learns; `vi-mcp incubator
status` shows every criterion with its threshold, its measured value and its state; when all required criteria are met it is ready to
hatch: the training data (dataset.py) is exported, and with it an AI can be fine-tuned.

States of a criterion (exhaustive): erfuellt (met) · offen (measured, not yet met) · nicht_gemessen (no measurement yet — named, never
counted as met). The VI is `reif` only when every required criterion is erfuellt; otherwise `im_inkubator`, with the open ones listed.

Criteria (thresholds overridable in config `incubator`, e.g. {"min_knowledge": 1000}):
  knowledge         shared or internal knowledge objects (erkenntnis, regel, skill) in the VI
  checked           share of them with measured use (rated after being shown) or confirmed by an instance — the epistemic basis:
                    knowledge that was put to the test, not only stated
  refuted_handled   refuted knowledge is marked, not deleted: at least one correction exists or none was needed (informative)
  search            hybrid MRR of the daily fixed question set (evaluation.py)
  router            the hint model is active with a holdout AUC (learning.py; an index uses its own model if it has one)
  hints_no_harm     the randomized hold-back does not show that hints lower success (metrics.holdback_effect)
  labels            share of knowledge classified for the AI language (classify.py), and the student active
  training_data     question → answer examples the dataset export would write (dataset.py), with the evaluation held out
"""
from __future__ import annotations

import json

from . import memory as g

DEFAULTS = {"min_knowledge": 500, "min_checked": 0.2, "min_mrr": 0.6, "min_auc": 0.75, "min_labelled": 0.5, "min_examples": 1000}
REQUIRED = ("knowledge", "checked", "search", "router", "hints_no_harm", "labels", "training_data")


def _cfg() -> dict:
    from . import config
    try:
        return {**DEFAULTS, **(config.read_raw(config.fpath()).get("incubator") or {})}
    except Exception:  # noqa: BLE001
        return dict(DEFAULTS)


def _c(name: str, state: str, value, threshold, note: str = "") -> dict:
    return {"kriterium": name, "zustand": state, "wert": value, "schwelle": threshold, "hinweis": note}


def _knowledge(index: str | None) -> list[tuple]:
    sql = ("SELECT id, json_extract(daten, '$.nuetzlich.n'), json_extract(daten, '$.bestaetigt_von'), json_extract(daten, '$.klasse.zustand') "
           "FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill') AND modus IN ('aktiv', 'test') AND sicht IN ('geteilt', 'intern')"
           + (" AND idx = ?" if index else ""))
    with g.lock:
        return g.db().execute(sql, ([index] if index else [])).fetchall()


def status(index: str | None = None) -> dict:
    """Every criterion with threshold, value and state; `reif` or `im_inkubator`."""
    from . import classify, evaluation, learning, metrics
    cfg = _cfg()
    rows = _knowledge(index)
    n = len(rows)
    out = [_c("knowledge", "erfuellt" if n >= cfg["min_knowledge"] else "offen", n, cfg["min_knowledge"], "shared or internal knowledge objects")]
    checked = sum(1 for _i, used, conf, _k in rows if (used or 0) > 0 or (conf not in (None, "{}", "null")))
    share = round(checked / n, 3) if n else 0.0
    out.append(_c("checked", "erfuellt" if n and share >= cfg["min_checked"] else "offen", share, cfg["min_checked"],
                  f"{checked} of {n} rated after being shown or confirmed by an instance"))
    with g.lock:
        refuted = g.db().execute("SELECT COUNT(*) FROM objekt WHERE modus = 'widerlegt'" + (" AND idx = ?" if index else ""),
                                 ([index] if index else [])).fetchone()[0]
    out.append(_c("refuted_handled", "erfuellt", refuted, None, f"{refuted} refuted object(s) marked, not deleted (informative)"))
    hist = evaluation.history(1)
    mrr = (((hist[-1].get("suche") or {}).get("hybrid") or {}).get("gesamt") or {}).get("mrr") if hist else None
    out.append(_c("search", "nicht_gemessen" if mrr is None else "erfuellt" if mrr >= cfg["min_mrr"] else "offen", mrr, cfg["min_mrr"],
                  "hybrid MRR of the daily fixed question set" + (f" ({hist[-1].get('datum') or hist[-1].get('zeit', '')[:10]})" if hist else " — no measurement yet")))
    m = (learning.active(index) if index else None) or learning.model()
    auc = (m.data.get("auc_holdout") if m else None)
    active = bool(m) and m.mode == "aktiv"
    out.append(_c("router", "nicht_gemessen" if auc is None else "erfuellt" if active and auc >= cfg["min_auc"] else "offen", auc, cfg["min_auc"],
                  (f"model {m.id} ({m.mode})" if m else "no model yet")))
    hb = metrics.holdback_effect(24 * 30)
    if hb.get("zustand") != "gemessen":
        out.append(_c("hints_no_harm", "nicht_gemessen", hb.get("zurueckgehalten"), "no harm beyond 2 SE", hb.get("urteil", "")))
    else:
        harm = hb["differenz"] < -2 * hb["standardfehler"]
        out.append(_c("hints_no_harm", "offen" if harm else "erfuellt", hb["differenz"], "no harm beyond 2 SE", hb["urteil"]))
    labelled = sum(1 for *_x, k in rows if k in ("einig", "uneinig", "schueler"))
    lshare = round(labelled / n, 3) if n else 0.0
    st = g.load(classify.STUDENT)
    lab_ok = n and lshare >= cfg["min_labelled"] and st is not None and st.mode == "aktiv"
    out.append(_c("labels", "erfuellt" if lab_ok else "offen", lshare, cfg["min_labelled"],
                  f"{labelled} of {n} classified; student {'active' if st is not None and st.mode == 'aktiv' else st.mode if st else 'not trained'}"))
    from . import dataset
    data = dataset.build(index)
    ex = len(data["qa"])
    out.append(_c("training_data", "erfuellt" if ex >= cfg["min_examples"] and data["held_out"] else "offen", ex, cfg["min_examples"],
                  f"question → answer examples; {data['held_out']} evaluation targets held out"
                  + ("" if data["held_out"] else " — no fixed question set yet, so a fine-tuned model could not be measured")))
    missing = [c["kriterium"] for c in out if c["kriterium"] in REQUIRED and c["zustand"] != "erfuellt"]
    return {"index": index or "all", "zustand": "reif" if not missing else "im_inkubator", "offen": missing, "kriterien": out, "zeit": g.now()}


def lines(st: dict) -> list[str]:
    mark = {"erfuellt": "✓", "offen": "·", "nicht_gemessen": "?"}
    head = (f"Incubator ({st['index']}): " + ("ready to hatch — `vi-mcp incubator hatch DIR` exports the training data"
                                             if st["zustand"] == "reif" else f"in the incubator, open: {', '.join(st['offen'])}"))
    return [head] + [f"  {mark[c['zustand']]} {c['kriterium']:15} {c['wert']!s:>8}  (threshold {c['schwelle']})  {c['hinweis']}" for c in st["kriterien"]]


def hatch(directory: str, index: str | None = None, force: bool = False) -> dict:
    """Export the training data of a mature VI. Without force, a VI still in the incubator is refused with the open criteria."""
    from . import dataset
    st = status(index)
    if st["zustand"] != "reif" and not force:
        raise ValueError(f"still in the incubator — open: {', '.join(st['offen'])} (vi-mcp incubator status; --force exports anyway, the "
                         "datasheet then names the open criteria)")
    manifest = dataset.export(directory, index)
    manifest["inkubator"] = {"zustand": st["zustand"], "offen": st["offen"], "zeit": st["zeit"]}
    from pathlib import Path
    p = Path(directory)
    (p / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with (p / "DATASHEET.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## Incubator\nState when hatched: {st['zustand']}" + (f" — open criteria: {', '.join(st['offen'])}" if st["offen"] else "") + "\n")
    return manifest


def main(argv: list[str]) -> int:
    """vi-mcp incubator status [--index X] [--json] | hatch DIR [--index X] [--force]"""
    import argparse
    from . import config
    a = argparse.ArgumentParser(prog="vi-mcp incubator", description="maturity of a VI for fine-tuning an AI")
    u = a.add_subparsers(dest="cmd", required=True)
    s = u.add_parser("status", help="every maturity criterion with threshold, value and state")
    s.add_argument("--index")
    s.add_argument("--json", action="store_true")
    h = u.add_parser("hatch", help="export the training data of a mature VI (dataset export plus the incubator state)")
    h.add_argument("directory")
    h.add_argument("--index")
    h.add_argument("--force", action="store_true")
    o = a.parse_args(argv)
    g.open_db(config.load().db)
    try:
        if o.cmd == "status":
            st = status(o.index)
            print(json.dumps(st, indent=2, ensure_ascii=False) if o.json else "\n".join(lines(st)))
        else:
            print(json.dumps(hatch(o.directory, o.index, o.force), indent=2, ensure_ascii=False))
    except ValueError as e:
        print(f"vi-mcp incubator: {e}")
        return 1
    finally:
        g.close_db()
    return 0

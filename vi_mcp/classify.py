"""Classify knowledge for the AI language (0.62.0): which question an object answers, what kind of memory it is.

The user (13.11.2026): "Nimm <LLM-Server>/<Modell> als LLM, um die Daten für unsere Suchsprache zu klassifizieren. Neue Daten werden ja
automatisch klassifiziert. Im Endeffekt ist das ja das Konzept des maschinellen Lernens, dass man Daten klassifiziert."

- Labels (English, the language of VIL): answers ∈ how · why · what · who · where · rule (plus a second one or none), memory ∈ fact ·
  procedure · episode · rule, and up to three questions a colleague would type to find the object (doc2query).
- Two prompt variants (different wording and label order — order and wording shift LLM labels, Pezeshkpour & Hruschka 2024, Reiss 2023).
  Both agree → the label is stored as hashtags `answers:<type>` and `memory:<kind>`; they disagree → the named state `answers:unsure`.
  The model's own confidence is never used (verbalised confidence is overconfident, Xiong et al. 2024).
- Every answer is checked against the schema here: on 13.11.2026 6 of 90 answers of a llama.cpp endpoint were outside the enum despite
  json_schema (`when`, `episode` as a second type). Outside → asked once more, then unsure.
- Every label carries its version (model, prompt hash, schema): a new model or prompt relabels instead of mixing.
- Measured on a production sample (13.11.2026, 45 objects, two variants): question type agreement 82 %, Cohen's kappa 0.75 (tentative,
  Krippendorff ≥ 0.667); memory kind 87 %, kappa 0.80; most disagreements how ↔ what.
Config `classify` ({url, model}) names the model; without it the server's `llm`. The language model is not trained — it labels.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request

from . import memory as g

SCHEMA_VERSION = "answers-v1"
ANSWERS = ("how", "why", "what", "who", "where", "rule")
MEMORY = ("fact", "procedure", "episode", "rule")
KINDS = ("insight", "rule", "skill")
CONTENT_CHARS = 1500

DEF = {
    "how": "how to do something: steps, commands, a procedure, a solution",
    "why": "why something happens or fails: cause, error explanation, diagnosis",
    "what": "what something is: a fact, definition, setting, version, property of a system",
    "who": "who is responsible or involved: owner, team, contact, person",
    "where": "where something is: host, path, URL, port, location of a file or service",
    "rule": "what must or must not be done: a policy, requirement, decision, convention",
    "none": "none of these, or too unclear to say",
}
MEMDEF = {"fact": "a lasting fact about a system or thing", "procedure": "how to do something (steps, commands)",
          "episode": "something that happened once (an incident, a measurement at a time, a finding)", "rule": "a policy or requirement"}


def _schema(order: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["primary", "secondary", "memory", "questions"],
            "properties": {"primary": {"enum": order}, "secondary": {"enum": order}, "memory": {"enum": list(MEMORY)},
                           "questions": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}}}}


def prompt(variant: str, o: g.MemoryObject) -> tuple[list[str], str, str]:
    """(label order, system, user) — variant A and B differ in wording and order on purpose."""
    order = list(ANSWERS) + ["none"] if variant == "A" else ["rule", "where", "who", "what", "why", "how", "none"]
    if variant == "A":
        system = ("You classify entries of a knowledge base for AI agents. Decide which kind of question the entry answers.\n"
                  + "\n".join(f"- {k}: {DEF[k]}" for k in order)
                  + "\nmemory: " + "; ".join(f"{k} = {v}" for k, v in MEMDEF.items())
                  + "\nprimary = the main question type; secondary = a second one it also answers, or 'none'. questions = 1 to 3 short "
                    "questions a colleague would type to find this entry, in the language of the entry. Answer with JSON only.")
    else:
        system = ("Label this knowledge-base entry. Which question would someone have, for this entry to be the answer? Options:\n"
                  + "\n".join(f"* {k} — {DEF[k]}" for k in order)
                  + "\nAlso say what kind of memory it is: " + ", ".join(f"{k} ({v})" for k, v in MEMDEF.items())
                  + ".\nGive the main type as primary, an additional one as secondary (else none), and up to three search questions in the "
                    "entry's own language. JSON only.")
    from . import checks
    tags = ", ".join(t for t in o.hashtags if not t.startswith(checks.LOCAL_FIXED) and not t.startswith(("answers:", "memory:")))
    user = (f"Entry kind: {o.kind}\nHashtags: {tags}\nTitle: {o.text}\n\nContent:\n{str(o.data.get('content') or '(none)')[:CONTENT_CHARS]}")
    return order, system, user


def prompt_hash() -> str:
    """Identity of the prompts and schema — part of every label's version."""
    probe = g.MemoryObject.__new__(g.MemoryObject)
    probe.kind, probe.text, probe.hashtags, probe.data = "insight", "", [], {}
    parts = [prompt(v, probe)[1] for v in ("A", "B")] + [SCHEMA_VERSION]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


def _config() -> dict:
    from . import config, reflection
    try:
        raw = config.read_raw(config.fpath())
    except Exception:  # noqa: BLE001
        raw = {}
    return raw.get("classify") or reflection.config or {}


def model_name() -> str:
    """0.69.3: the classify model's name for the version records — config model, else the path segment of its URL before /v1
    (".../qwen27b/v1/chat/completions" → qwen27b). Production configs name only the URL, so every record said "?"."""
    import re as _re
    c = _config()
    if c.get("model"):
        return str(c["model"])
    m = _re.search(r"/([^/]+)/v1/", str(c.get("url") or ""))
    return m.group(1) if m else "?"


def configured() -> bool:
    """An explicit classify model in the config (sleep labels only then; `vi-mcp classify` also uses the server's llm)."""
    from . import config
    try:
        return bool((config.read_raw(config.fpath()).get("classify") or {}).get("url"))
    except Exception:  # noqa: BLE001
        return False


def per_sleep() -> int:
    """How many objects one sleep labels (config classify.per_sleep, default 10: two calls each, ~40 s per call measured on a shared server)."""
    from . import config
    try:
        return max(0, min(int((config.read_raw(config.fpath()).get("classify") or {}).get("per_sleep", 10)), 500))
    except Exception:  # noqa: BLE001
        return 10


def available() -> bool:
    from . import reflection
    return reflection.ask_fn is not None or bool(_config().get("url"))


def _ask(system: str, user: str, order: list[str]) -> str:
    """One call, temperature 0, schema-constrained, thinking off, no token cap (project rule)."""
    return _ask_schema(system, user, _schema(order), "label")


def _ask_schema(system: str, user: str, schema: dict, name: str) -> str:
    """The classify model with any JSON schema (also relevance.py) — temperature 0, thinking off, no token cap."""
    from . import reflection
    if reflection.ask_fn is not None:  # tests
        return reflection.ask_fn(system, user)
    cfg = _config()
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}}
    if cfg.get("model"):
        body["model"] = cfg["model"]
    from clingo_object.agent import chat_post  # 0.63.3: retries once without llama.cpp fields if the provider refuses them
    header = {"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else {}
    return chat_post(cfg["url"], body, header, 600, urllib.request.build_opener(urllib.request.ProxyHandler({})))["choices"][0]["message"]["content"]


def valid(answer: dict) -> str | None:
    """None if the answer fits the schema, else what is wrong (checked here — the endpoint does not always enforce it)."""
    if not isinstance(answer, dict):
        return "not an object"
    for k, allowed in (("primary", ANSWERS + ("none",)), ("secondary", ANSWERS + ("none",)), ("memory", MEMORY)):
        if answer.get(k) not in allowed:
            return f"{k}={answer.get(k)!r} outside the schema"
    q = answer.get("questions")
    if not isinstance(q, list) or not 1 <= len(q) <= 3 or not all(isinstance(x, str) and x.strip() for x in q):
        return "questions: 1 to 3 strings"
    return None


def _one(variant: str, o: g.MemoryObject) -> tuple[dict | None, str | None]:
    from . import reflection
    order, system, user = prompt(variant, o)
    why = None
    for _attempt in range(2):
        try:
            a = reflection._json_from(_ask(system, user, order))
        except Exception as e:  # noqa: BLE001 — a failed call leaves the object unlabelled, named
            return None, f"{type(e).__name__}: {str(e)[:120]}"
        why = valid(a)
        if why is None:
            return a, None
    return None, why


def label(o: g.MemoryObject) -> dict:
    """Both variants for one object → the label (pure apart from the model calls)."""
    a, why_a = _one("A", o)
    b, why_b = _one("B", o)
    version = {"modell": model_name(), "prompt": prompt_hash(), "schema": SCHEMA_VERSION}
    if a is None or b is None:
        return {"zustand": "fehler", "grund": why_a or why_b, "version": version}
    agree = a["primary"] == b["primary"]
    return {"zustand": "einig" if agree else "uneinig", "answers": a["primary"] if agree else "unsure",
            "zweite": a["secondary"] if agree and a["secondary"] == b["secondary"] else "none",
            "memory": a["memory"] if a["memory"] == b["memory"] else "unsure",
            "varianten": {"A": [a["primary"], a["secondary"], a["memory"]], "B": [b["primary"], b["secondary"], b["memory"]]},
            "fragen": [q.strip()[:200] for q in a["questions"][:3]], "version": version}


def apply(o: g.MemoryObject, lab: dict, who: str = "vi") -> bool:
    """Store a label on the object: data.klasse and the hashtags answers:/memory: (replacing older ones). False on an error label."""
    if lab.get("zustand") == "fehler":
        return False
    tags = [f"answers:{lab['answers']}", f"memory:{lab['memory']}"] + ([f"answers:{lab['zweite']}"] if lab.get("zweite") not in (None, "none", lab["answers"]) else [])
    old = [t for t in o.hashtags if t.startswith(("answers:", "memory:"))]
    o.hashtags = sorted((set(o.hashtags) - set(old)) | set(tags))
    o.data = {**o.data, "class": {**lab, "ts": g.now()}}
    o.change(who, "classified " + " ".join(tags), f"labels {lab['zustand']} ({lab['version']['schema']}, prompt {lab['version']['prompt']})")
    g.save(o)
    _queue_table()
    with g.lock:
        g.db().execute("DELETE FROM class_queue WHERE id = ?", (o.id,))
        g.db().commit()
    return True


QUEUE_MAX = 5000


def _queue_table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS class_queue (id TEXT PRIMARY KEY, ts TEXT NOT NULL)")
        g.db().commit()


def on_search(objs) -> dict:
    """0.62.0 — the user: "Wenn die Suche unqualifizierte Daten bekommt, dann müssen diese Objekte automatisch klassifiziert werden, um
    die alte DB-Version in die neue Version zu migrieren." Knowledge a search returned without a label of the current version: the
    student labels it at once where it is sure (a matrix product, no language model); the rest is queued, and sleep step 8f labels the
    queue first — what is searched for migrates first. Never raises: a search must not fail because of labelling."""
    out = {"schueler": 0, "eingereiht": 0}
    try:
        ph = prompt_hash()
        todo = [o for o in objs if o is not None and o.kind in KINDS and o.visibility != "private" and o.mode not in ("quarantine", "refuted", "withdrawn")
                and (o.data.get("class") or {}).get("version", {}).get("prompt") != ph]
        if not todo:
            return out
        _queue_table()
        for o in todo:
            lab = student_label(o)
            if lab is not None:
                apply(o, lab, "search")
                out["schueler"] += 1
                continue
            with g.lock:
                n = g.db().execute("SELECT COUNT(*) FROM class_queue").fetchone()[0]
                if n < QUEUE_MAX:
                    g.db().execute("INSERT OR IGNORE INTO class_queue (id, ts) VALUES (?, ?)", (o.id, g.now()))
                    g.db().commit()
                    out["eingereiht"] += 1
    except Exception:  # noqa: BLE001
        pass
    return out


def queued() -> int:
    _queue_table()
    with g.lock:
        return g.db().execute("SELECT COUNT(*) FROM class_queue").fetchone()[0]


def pending(limit: int = 20) -> list[str]:
    """Knowledge without a label of the current version: first what searches returned (the queue, oldest first), then the newest."""
    ph = prompt_hash()
    _queue_table()
    with g.lock:
        q = [r[0] for r in g.db().execute("SELECT id FROM class_queue ORDER BY ts LIMIT ?", (int(limit) * 20,))]
    first = []
    for oid in q:
        o = g.load(oid)
        if o is None or (o.data.get("class") or {}).get("version", {}).get("prompt") == ph or o.kind not in KINDS or o.visibility == "private":
            with g.lock:  # labelled meanwhile, gone or not knowledge: off the queue
                g.db().execute("DELETE FROM class_queue WHERE id = ?", (oid,))
                g.db().commit()
            continue
        first.append(oid)
    rest = _pending_rest(limit * 20, ph)
    return (first + [i for i in rest if i not in set(first)])[:limit]


def _pending_rest(n: int, ph: str) -> list[str]:
    with g.lock:
        rows = g.db().execute(
            "SELECT id, json_extract(data, '$.class.version.prompt') FROM object WHERE kind IN ('insight', 'rule', 'skill') "
            "AND mode NOT IN ('quarantine', 'refuted', 'withdrawn', 'merged', 'archived') AND visibility <> 'private' "
            "AND idx NOT IN (SELECT name FROM vi_index WHERE explicit = 1) ORDER BY ts DESC LIMIT ?",  # 0.70.3: no LLM labels in sleep
            (int(n),)).fetchall()
    return [oid for oid, p in rows if p != ph]


def run(limit: int = 20, who: str = "sleep") -> dict:
    """Label up to `limit` pending objects (sleep step 8f, or `vi-mcp classify`). Counts per state."""
    if not available():
        return {"zustand": "uebersprungen", "grund": "no language model for classification (config classify or llm)"}
    out = {"einig": 0, "uneinig": 0, "fehler": 0, "gruende": {}}
    for oid in pending(limit):
        o = g.load(oid)
        if o is None:
            continue
        lab = label(o)
        out[lab["zustand"]] += 1
        if lab["zustand"] == "fehler":
            out["gruende"][lab["grund"][:80]] = out["gruende"].get(lab["grund"][:80], 0) + 1
        apply(o, lab, who)
    return out


def main(argv: list[str]) -> int:
    """vi-mcp classify [--limit N] [--dry-run] — label pending knowledge now (otherwise sleep step 8f does it with a classify model).
    vi-mcp classify --pairs [--limit N] [--workers W] [--stale] [--dry-run] — grounded training pairs and a probe question per object
    (otherwise sleep step 8i does a few per sleep)."""
    import argparse
    from . import config
    a = argparse.ArgumentParser(prog="vi-mcp classify", description="label knowledge for the AI language: which question it answers")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--dry-run", action="store_true", help="only count what is pending")
    a.add_argument("--pairs", action="store_true", help="store grounded training pairs and a probe question on knowledge (data.qa)")
    a.add_argument("--workers", type=int, default=1, help="with --pairs: parallel model calls")
    a.add_argument("--stale", action="store_true", help="with --pairs: also renew pairs whose knowledge changed since")
    o = a.parse_args(argv)
    from . import reflection
    k = config.load()
    reflection.config = k.llm or {}
    g.open_db(k.db)
    try:
        if o.pairs:
            print(json.dumps(pairs_report() if o.dry_run else run_pairs(o.limit, "admin", o.workers, o.stale), indent=2, ensure_ascii=False))
        elif o.dry_run:
            print(json.dumps({"ausstehend": len(pending(o.limit)), "prompt": prompt_hash(), "schema": SCHEMA_VERSION}, indent=2))
        else:
            print(json.dumps(run(o.limit, "admin"), indent=2, ensure_ascii=False))
    finally:
        g.close_db()
    return 0


# ── the student: a small model learns the labels from the embeddings (distillation) ─────────────────────────────────────────────
# Research (13.11.2026): classifiers trained on LLM labels do about as well as on human labels (Pangakis & Wolken 2024); FineWeb-Edu let
# an LLM rate 460,000 pages and trained a small classifier on them (arXiv 2406.17557). Here: logistic regression on the bge-m3 vectors
# the memory already has; new knowledge is labelled without a language model where the student is sure, the rest goes to the LLM, and a
# share of the student's labels is checked by the LLM (agreement recorded on the model object — drift becomes visible). Active only
# where its sure labels are ≥ 90 % right on ≥ 10 % of the objects (5-fold cross-validation, C chosen from C_GRID).

def student_id() -> str:
    """The id of the student model (modell:klassen up to 0.66, model:klassen for a memory created later)."""
    return g.keyed_id("model", "klassen")
MIN_PER_CLASS = 15
MIN_TOTAL = 120
SURE = 0.8
#: the student labels only where it is sure, so the gate is the accuracy OF THOSE labels, with enough of them to matter. Measured on a
#: production sample (13.11.2026, 160/195 agreed labels, bge-m3 vectors, 5-fold): with C = 1 no prediction ever reached 0.8 (the vectors
#: are unit length, the logits stay small) — the first version would never have labelled anything; C = 10 was sure on 17–21 % at
#: 94–97 % accuracy, C = 100 on about 60 % at 83–84 %. Overall accuracy was 0.69–0.76: an overall gate of 0.8 would never have opened.
GATE_SURE_ACCURACY = 0.9
GATE_COVERAGE = 0.1
C_GRID = (1.0, 10.0, 100.0)
AUDIT_SHARE = 0.1


def _labelled() -> tuple[list[str], list[str], list[str]]:
    """(ids, answers, memory) of objects the LLM labelled with both variants agreeing — the student learns only from those."""
    with g.lock:
        rows = g.db().execute(
            "SELECT id, json_extract(data, '$.class.answers'), json_extract(data, '$.class.memory') FROM object "
            "WHERE json_extract(data, '$.class.state') = 'einig' AND mode NOT IN ('refuted', 'withdrawn', 'archived')").fetchall()
    rows = [r for r in rows if r[1] in ANSWERS and r[2] in MEMORY]
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


def train_student(who: str = "sleep") -> dict:
    """Fit one logistic regression per head (answers, memory) on the agreed LLM labels; holdout accuracy decides active or test."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from . import vector
    ids, ans, mem = _labelled()
    vecs = {i: v for i in ids if (v := vector.load(i)) is not None}
    keep = [k for k, i in enumerate(ids) if i in vecs]
    report = {"n": len(keep), "trainiert": g.now(), "lehrer": {"prompt": prompt_hash(), "schema": SCHEMA_VERSION}}
    if len(keep) < MIN_TOTAL:
        return {**report, "zustand": "zu_wenig", "grund": f"{len(keep)} agreed labels with a vector, at least {MIN_TOTAL}"}
    X = np.vstack([vecs[ids[k]] for k in keep])
    heads = {}
    for head, labels in (("answers", [ans[k] for k in keep]), ("memory", [mem[k] for k in keep])):
        counts = {c: labels.count(c) for c in set(labels)}
        classes = sorted(c for c, n in counts.items() if n >= MIN_PER_CLASS)
        mask = [y in classes for y in labels]
        Xh, yh = X[mask], [y for y, m in zip(labels, mask) if m]
        if len(classes) < 2:
            heads[head] = {"zustand": "zu_wenig", "grund": f"fewer than 2 classes with {MIN_PER_CLASS} labels ({counts})"}
            continue
        yh = np.array(yh)
        folds = list(StratifiedKFold(5, shuffle=True, random_state=7).split(Xh, yh))
        grid = {}
        for C in C_GRID:  # 5-fold: overall accuracy, and how many it is sure of (≥ SURE) and how right those are
            ok = sure = sure_ok = 0
            for tr, te in folds:
                m = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xh[tr], yh[tr])
                pr = m.predict_proba(Xh[te])
                pred = m.classes_[pr.argmax(1)]
                s_ = pr.max(1) >= SURE
                ok += int((pred == yh[te]).sum())
                sure += int(s_.sum())
                sure_ok += int((pred[s_] == yh[te][s_]).sum())
            grid[C] = {"genauigkeit": round(ok / len(yh), 3), "abdeckung": round(sure / len(yh), 3),
                       "genauigkeit_sicher": round(sure_ok / sure, 3) if sure else None}
        passing = [C for C, r in grid.items() if r["genauigkeit_sicher"] is not None and r["genauigkeit_sicher"] >= GATE_SURE_ACCURACY
                   and r["abdeckung"] >= GATE_COVERAGE]
        C = max(passing, key=lambda c: grid[c]["abdeckung"]) if passing else max(grid, key=lambda c: grid[c]["genauigkeit"])
        clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xh, yh)  # the gate passed or not — the final fit uses all
        heads[head] = {"zustand": "active" if passing else "test", "C": C, "kreuzvalidierung": {str(k): v for k, v in grid.items()},
                       "genauigkeit_sicher": grid[C]["genauigkeit_sicher"], "abdeckung": grid[C]["abdeckung"], "genauigkeit": grid[C]["genauigkeit"],
                       "klassen": list(clf.classes_), "nicht_gelernt": {c: n for c, n in counts.items() if c not in classes},
                       "gewichte": [[round(float(x), 5) for x in row] for row in clf.coef_], "achsenabschnitt": [round(float(x), 5) for x in clf.intercept_]}
    state = "active" if all(h.get("zustand") == "active" for h in heads.values()) else "test"
    report.update(zustand=state, koepfe=heads, dim=int(X.shape[1]))
    text = (f"Student for the AI-language labels ({state}): {len(keep)} agreed LLM labels; where sure (≥ {SURE}): "
            + ", ".join(f"{h} {d.get('genauigkeit_sicher', '—')} right on {d.get('abdeckung', '—')} of objects (C {d.get('C', '—')})"
                        for h, d in heads.items()))
    m = g.load(student_id())
    if m is None:
        g.new_object("model", text, ["model:klassen"], report, importance=2, who=who, oid=student_id(), mode=state, reason="student trained",
                     instance=g.SERVER_INSTANCE)
    else:
        m.text, m.data, m.mode = text, {**report, "pruefung": m.data.get("pruefung", {"geprueft": 0, "gleich": 0})}, state
        m.change(who, f"retrained → {state}", "student trained")
        g.save(m)
    return {k: v for k, v in report.items() if k != "koepfe"} | {"koepfe": {h: {k: v for k, v in d.items() if k != "gewichte"} for h, d in heads.items()}}


def _predict(head: dict, v) -> tuple[str, float]:
    import numpy as np
    z = np.array(head["gewichte"]) @ v + np.array(head["achsenabschnitt"])
    if len(head["klassen"]) == 2:  # binary logistic regression has one row: the second class
        p1 = 1 / (1 + np.exp(-z[0]))
        probs = np.array([1 - p1, p1])
    else:
        e = np.exp(z - z.max())
        probs = e / e.sum()
    i = int(probs.argmax())
    return head["klassen"][i], float(probs[i])


def student_label(o: g.MemoryObject) -> dict | None:
    """The student's label for one object, or None if it is not active, has no vector or is not sure (≥ SURE on both heads)."""
    from . import vector
    m = g.load(student_id())
    if m is None or m.mode != "active":
        return None
    v = vector.load(o.id)
    if v is None or len(v) != m.data.get("dim"):
        return None
    ans, p_a = _predict(m.data["koepfe"]["answers"], v)
    mem, p_m = _predict(m.data["koepfe"]["memory"], v)
    if p_a < SURE or p_m < SURE:
        return None
    return {"zustand": "schueler", "answers": ans, "zweite": "none", "memory": mem, "fragen": [], "sicher": [round(p_a, 3), round(p_m, 3)],
            "version": {"modell": f"student@{m.data.get('trainiert', '?')[:16]}", "prompt": prompt_hash(), "schema": SCHEMA_VERSION}}


def run_with_student(limit: int = 20, who: str = "sleep", rng=None) -> dict:
    """Sleep step 8f: the student labels what it is sure of; the LLM labels the rest (up to `limit`) and checks a share of the student's
    labels — agreement is counted on the student, so its drift is visible."""
    import random
    rng = rng or random.Random()
    out = {"schueler": 0, "einig": 0, "uneinig": 0, "fehler": 0, "geprueft": 0, "gleich": 0, "gruende": {}}
    asked = 0
    for oid in pending(limit * 20):
        o = g.load(oid)
        if o is None:
            continue
        lab = student_label(o)
        if lab is not None and (rng.random() >= AUDIT_SHARE or not available() or asked >= limit):
            apply(o, lab, who)
            out["schueler"] += 1
            continue
        if not available() or asked >= limit:
            continue
        asked += 1
        llm = label(o)
        out[llm["zustand"]] += 1
        if llm["zustand"] == "fehler":
            out["gruende"][llm["grund"][:80]] = out["gruende"].get(llm["grund"][:80], 0) + 1
        elif lab is not None:  # an audit: the student said lab, the LLM says llm
            out["geprueft"] += 1
            out["gleich"] += int(llm["answers"] == lab["answers"])
        apply(o, llm, who)
    m = g.load(student_id())
    if m is not None and out["geprueft"]:
        p = m.data.get("pruefung", {"geprueft": 0, "gleich": 0})
        m.data = {**m.data, "pruefung": {"geprueft": p["geprueft"] + out["geprueft"], "gleich": p["gleich"] + out["gleich"]}}
        g.save(m)
    return out


# ── gold: labels set by people, and the truth check of the measurement ─────────────────────────────────────────────────────────────
# The user (13.11.2026): the gold set rests on the epistemic foundation ("dafür haben wir ja die philosophische Grundlage eingeführt nach
# der Wahrheits-/Erkenntnistheorie. Mache das aber."). Two agreeing prompts only measure how consistent the model is with itself; gold is
# what a person decided. Only instances with `human: true` (config) set gold — no instance rates itself, and an AI is not the gold.

def set_gold(oid: str, answers: str, memory: str, who: str, human: bool) -> g.MemoryObject:
    """A person's label for one object (daten.gold). Raises with the reason if not allowed or not valid."""
    if not human:
        raise ValueError(f"{who} is no human instance (config human: true) — gold labels come from people only")
    if answers not in ANSWERS + ("none",) or memory not in MEMORY:
        raise ValueError(f"answers must be one of {', '.join(ANSWERS)}, none; memory one of {', '.join(MEMORY)}")
    o = g.load(oid)
    if o is None or o.kind not in KINDS:
        raise ValueError(f"{oid}: no knowledge object")
    o.data = {**o.data, "gold": {"answers": answers, "memory": memory, "who": who, "ts": g.now()}}
    o.change(who, f"gold label {answers}/{memory}", "set by a person")
    g.save(o)
    return o


def gold_report() -> dict:
    """The language model's and the student's labels against the people's, and the truth check of the measured weights."""
    with g.lock:
        rows = g.db().execute("SELECT id FROM object WHERE json_extract(data, '$.gold.answers') IS NOT NULL").fetchall()
    llm = {"n": 0, "richtig": 0, "unsure": 0}
    student = {"n": 0, "richtig": 0}
    per: dict[str, list[int]] = {}
    for (oid,) in rows:
        o = g.load(oid)
        if o is None:
            continue
        gold, k = o.data["gold"], o.data.get("class") or {}
        if k.get("state") in ("einig", "uneinig"):
            llm["n"] += 1
            if k["answers"] == "unsure":
                llm["unsure"] += 1
            hit = int(k["answers"] == gold["answers"])
            llm["richtig"] += hit
            per.setdefault(gold["answers"], [0, 0])
            per[gold["answers"]][0] += 1
            per[gold["answers"]][1] += hit
        elif k.get("state") == "schueler":
            student["n"] += 1
            student["richtig"] += int(k["answers"] == gold["answers"])
    return {"gold": len(rows), "llm": {**llm, "genauigkeit": round(llm["richtig"] / llm["n"], 3) if llm["n"] else None},
            "schueler": {**student, "genauigkeit": round(student["richtig"] / student["n"], 3) if student["n"] else None},
            "je_klasse": {c: {"n": n, "richtig": r} for c, (n, r) in sorted(per.items())}, "wahrheitsprobe": truth_check()}


def truth_check(humans: set[str] | None = None) -> dict:
    """Does the memory's measurement agree with people's judgement? Over knowledge that human instances confirmed or refuted: the
    probability that a confirmed object has a higher measured weight than a refuted one (AUC; 0.5 = the measurement ignores truth)."""
    from . import config, vil
    if humans is None:
        try:
            humans = {n for n, i in config.load().instances.items() if i.human}
        except Exception:  # noqa: BLE001
            humans = set()
    if not humans:
        return {"zustand": "keine_menschen", "grund": "no instance with human: true in the config"}
    with g.lock:
        rows = g.db().execute("SELECT id FROM object WHERE kind IN ('insight', 'rule', 'skill') AND (json_extract(data, '$.confirmed_by') IS NOT NULL "
                              "OR json_extract(data, '$.refuted_by') IS NOT NULL)").fetchall()
    conf, ref = [], []
    for (oid,) in rows:
        o = g.load(oid)
        if o is None:
            continue
        w, n = vil.weight_of(o)
        if n == 0:
            continue
        by_c = set((o.data.get("confirmed_by") or {})) & humans
        by_r = set((o.data.get("refuted_by") or {})) & humans
        if by_c and not by_r:
            conf.append(w)
        elif by_r and not by_c:
            ref.append(w)
    if not conf or not ref:
        return {"zustand": "zu_wenig", "bestaetigt": len(conf), "widerlegt": len(ref),
                "grund": "needs measured objects that people confirmed and others they refuted"}
    pairs = sum(1.0 if c > r else 0.5 if c == r else 0.0 for c in conf for r in ref)
    return {"zustand": "gemessen", "auc": round(pairs / (len(conf) * len(ref)), 3), "bestaetigt": len(conf), "widerlegt": len(ref)}


# ── training pairs: knowledge stored training-ready (0.65.0) ──────────────────────────────────────────────────────────────────────
# The user (15.11.2026): "Es muss alles so dokumentiert werden, dass jeder aus dem Stand ein Modell trainieren kann. D.h. die Daten
# müssen von Anfang an in der richtigen Art und Weise gespeichert sein." The first fine-tuning runs had to synthesise question-answer
# pairs for 23,585 documents on the trainer (~25 h with a 35B model). Now the server writes them onto each knowledge object while it
# sleeps (step 8i, the classify model, PAIRS_PER_SLEEP objects) or on `vi-mcp classify --pairs`: data.qa = {state, pairs, probe,
# rejected, content_sha256, version {model, prompt, schema}, time}. One definition of a good pair for server and kit: qa_pairs.py.
# Changed knowledge makes its pairs stale (content hash): the export leaves them out and the next run makes new ones.

PAIRS_RETRY_AFTER_S = 86400  # a failed generation (model down, no JSON) is retried after a day, not at every sleep


PAIRS_SECONDS = 1800  # 0.69.3: a sleep spends this much time on training pairs (config classify.pairs_seconds)


def pairs_per_sleep() -> int:
    """At most this many objects per sleep get training pairs (config classify.pairs_per_sleep, default 200 since 0.69.3, before 5) —
    the time budget pairs_seconds() usually ends first (~40 s per object measured on a shared model)."""
    from . import config
    try:
        return max(0, min(int((config.read_raw(config.fpath()).get("classify") or {}).get("pairs_per_sleep", 200)), 2000))
    except Exception:  # noqa: BLE001
        return 200


def pairs_seconds() -> float:
    """0.69.3 (the user, 17.11.2026, after the import of ~16,000 documentation pages: "mehr pro Schlaf"): the time a sleep spends on
    training pairs — config classify.pairs_seconds, default 1,800 s (~45 objects at 40 s; 5 before, ~3 min)."""
    from . import config
    try:
        return max(0.0, min(float((config.read_raw(config.fpath()).get("classify") or {}).get("pairs_seconds", PAIRS_SECONDS)), 14400.0))
    except Exception:  # noqa: BLE001
        return float(PAIRS_SECONDS)


def _pairs_queue_table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS pairs_queue (id TEXT PRIMARY KEY, ts TEXT NOT NULL)")
        g.db().commit()


def pairs_queued() -> int:
    _pairs_queue_table()
    with g.lock:
        return g.db().execute("SELECT COUNT(*) FROM pairs_queue").fetchone()[0]


def queue_pairs(objs) -> int:
    """0.69.3 (the user: what agents search for and read is qualified first): knowledge without current training pairs that was just
    accessed goes in front of sleep step 8i. No model call here. At most QUEUE_MAX waiting."""
    from . import qa_pairs
    ph = qa_pairs.prompt_sha256()
    todo = [o.id for o in objs if o is not None and o.kind in ("insight", "rule", "skill") and o.visibility != "private"
            and o.mode not in ("quarantine", "refuted", "withdrawn", "merged", "archived") and "knowledge_kind:code" not in o.hashtags
            and ((o.data.get("qa") or {}).get("version") or {}).get("prompt") not in (ph, "agent-v1")]  # 0.69.3: agent pairs are current
    if not todo:
        return 0
    _pairs_queue_table()
    n = 0
    with g.lock:
        waiting = g.db().execute("SELECT COUNT(*) FROM pairs_queue").fetchone()[0]
        for oid in todo:
            if waiting + n >= QUEUE_MAX:
                break
            n += g.db().execute("INSERT OR IGNORE INTO pairs_queue (id, ts) VALUES (?, ?)", (oid, g.now())).rowcount
        g.db().commit()
    return n


def document_of(o: g.MemoryObject) -> str:
    """Exactly the text the training export uses as this object's answer (scrubbed, with source) — pairs are grounded in it."""
    from collections import Counter
    from . import dataset
    return dataset._answer(o, Counter())


def make_pairs(o: g.MemoryObject) -> dict:
    """Ask the classify model once for grounded pairs and keep only what qa_pairs.select admits (pure apart from the model call)."""
    from . import qa_pairs
    doc = document_of(o)
    version = {"model": model_name(), "prompt": qa_pairs.prompt_sha256(), "schema": qa_pairs.SCHEMA_VERSION}
    # named, not silent: a long page gets pairs only from its first DOC_CHARS characters (anchored chunks are the next step)
    base = {"content_sha256": qa_pairs.content_sha256(doc), "version": version, "truncated": len(doc) > qa_pairs.DOC_CHARS,
            "chars": len(doc)}
    try:
        raw = _ask_schema(qa_pairs.system_for(), doc[:qa_pairs.DOC_CHARS], qa_pairs.SCHEMA, "pairs")
    except Exception as e:  # noqa: BLE001 — named, retried after PAIRS_RETRY_AFTER_S
        return {**base, "state": "error", "reason": f"{type(e).__name__}: {str(e)[:120]}", "pairs": [], "probe": None, "rejected": {}}
    pairs = qa_pairs.parse(raw)
    if pairs is None:
        return {**base, "state": "error", "reason": "no JSON answer", "pairs": [], "probe": None, "rejected": {}}
    kept, rejected = qa_pairs.select(pairs, doc)
    if kept:  # qa-v4: a language model checks each kept pair against the document and may only reject
        try:
            raw_s = _ask_schema(qa_pairs.SUPPORT_SYSTEM, qa_pairs.support_user(doc, kept), qa_pairs.SUPPORT_SCHEMA, "support")
        except Exception as e:  # noqa: BLE001 — no check, no pairs: retried after PAIRS_RETRY_AFTER_S
            return {**base, "state": "error", "reason": f"support check: {type(e).__name__}: {str(e)[:100]}", "pairs": [], "probe": None, "rejected": rejected}
        kept, rej_s, complete = qa_pairs.apply_support(kept, raw_s)
        if not complete:
            return {**base, "state": "error", "reason": "support check incomplete (a pair without a verdict)", "pairs": [], "probe": None, "rejected": rejected}
        for k, v in rej_s.items():
            rejected[k] = rejected.get(k, 0) + v
    train, probe, close = qa_pairs.split_probe(o.id, kept)
    if close:
        rejected["too close to the object's probe question"] = close
    return {**base, "state": "ok" if train else "empty", "pairs": train, "probe": probe, "rejected": rejected}


def store_pairs(o: g.MemoryObject, res: dict, who: str = "vi") -> bool:
    """Write the result onto the CURRENT object: the model call takes up to minutes, and saving the copy loaded before it would undo
    whatever changed meanwhile (lost update, Codex's review 15.11.2026). Knowledge that changed during the call keeps no pairs made
    from its old text. False if nothing was stored."""
    from . import qa_pairs
    cur = g.load(o.id)
    if (cur is None or cur.visibility == "private" or cur.mode in ("quarantine", "refuted", "merged", "archived")
            or qa_pairs.content_sha256(document_of(cur)) != res["content_sha256"]):
        return False
    cur.data = {**cur.data, "qa": {**res, "time": g.now()}}
    cur.change(who, f"training pairs: {len(res['pairs'])}" + (" + probe" if res.get("probe") else ""),
               f"state {res['state']} ({res['version']['schema']}, prompt {res['version']['prompt'][:12]})")
    g.save(cur)
    return True


STALE_SAMPLE = 200  # per sleep: stored pairs checked against today's text in a random sample (the full scan is --stale)


def pairs_pending(limit: int = 20, stale: bool = False, sample: int = 0) -> list[str]:
    """Knowledge without current training pairs, newest first: none yet, another prompt or schema, or a failed try older than a day.
    Then knowledge whose text changed since its pairs were made (any state): stale=True checks all of it (command line), sample=N a
    random N per call (sleep) — the content hash is not in SQL. The export checks every object anyway: stale pairs are never trained."""
    from . import qa_pairs
    ph = qa_pairs.prompt_sha256()
    live = ("SELECT id FROM object WHERE kind IN ('insight', 'rule', 'skill') AND mode NOT IN ('quarantine', 'refuted', 'withdrawn', "
            "'merged', 'archived') AND visibility <> 'private' AND NOT EXISTS (SELECT 1 FROM tag t WHERE t.object_id = object.id "
            "AND t.tag = 'knowledge_kind:code') "
            "AND idx NOT IN (SELECT name FROM vi_index WHERE explicit = 1) ")  # 0.70.3: an explicit-only corpus gets no LLM pairs in sleep
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PAIRS_RETRY_AFTER_S)).isoformat(timespec="milliseconds")
    _pairs_queue_table()
    with g.lock:  # 0.69.3: what was searched for or read comes first (queue_pairs), oldest request first
        queued = [r[0] for r in g.db().execute("SELECT id FROM pairs_queue ORDER BY ts LIMIT ?", (int(limit) * 4,))]
    out = []
    for oid in queued:
        o = g.load(oid)
        if o is None or ((o.data.get("qa") or {}).get("version") or {}).get("prompt") in (ph, "agent-v1") or o.mode in ("archived", "merged", "refuted", "withdrawn"):
            with g.lock:
                g.db().execute("DELETE FROM pairs_queue WHERE id = ?", (oid,))
                g.db().commit()
            continue
        out.append(oid)
        if len(out) >= limit:
            return out
    with g.lock:
        rows = g.db().execute(live + "AND (json_extract(data, '$.qa.version.prompt') IS NULL OR json_extract(data, '$.qa.version.prompt') NOT IN (?, 'agent-v1') "
                              "OR (json_extract(data, '$.qa.state') = 'error' AND json_extract(data, '$.qa.time') < ?)) ORDER BY ts DESC LIMIT ?",
                              (ph, cutoff, int(limit))).fetchall()
    out += [r[0] for r in rows if r[0] not in set(out)][:max(0, int(limit) - len(out))]
    if (stale or sample) and len(out) < limit:
        q = live + "AND json_extract(data, '$.qa.state') IN ('ok', 'empty') AND json_extract(data, '$.qa.version.prompt') = ? "
        with g.lock:
            cand = [r[0] for r in (g.db().execute(q + "ORDER BY ts DESC", (ph,)) if stale else
                                   g.db().execute(q + "ORDER BY RANDOM() LIMIT ?", (ph, int(sample))))]
        for oid in cand:
            o = g.load(oid)
            if o is not None and (o.data.get("qa") or {}).get("content_sha256") != qa_pairs.content_sha256(document_of(o)):
                out.append(oid)
                if len(out) >= limit:
                    break
    return out


def run_pairs(limit: int = 20, who: str = "sleep", workers: int = 1, stale: bool = False, sample: int = 0, budget_s: float | None = None) -> dict:
    """Training pairs for up to `limit` pending objects (sleep step 8i, or `vi-mcp classify --pairs`). Counts per state. budget_s
    (0.69.3): no new object is started after that many seconds (the sleep passes pairs_seconds())."""
    import concurrent.futures as cf
    import time as _time
    t0 = _time.monotonic()
    if not available():
        return {"zustand": "uebersprungen", "grund": "no language model for training pairs (config classify or llm)"}
    out = {"ok": 0, "empty": 0, "error": 0, "pairs": 0, "probes": 0, "changed_meanwhile": 0, "truncated": 0, "rejected": {}, "reasons": {}}
    objs = [o for o in (g.load(i) for i in pairs_pending(limit, stale, sample)) if o is not None]
    w = max(1, int(workers))
    _pairs_queue_table()
    n_done = 0
    with cf.ThreadPoolExecutor(w) as pool:
        for k in range(0, len(objs), w):  # in rounds of `workers`: a time budget ends between rounds, each round is stored at once
            if budget_s is not None and _time.monotonic() - t0 > budget_s:
                out["stopped"] = f"time budget {int(budget_s)} s after {n_done} objects"
                break
            chunk = objs[k:k + w]
            for o, res in zip(chunk, pool.map(make_pairs, chunk)):  # model calls in parallel, database writes here, one at a time
                n_done += 1
                with g.lock:
                    g.db().execute("DELETE FROM pairs_queue WHERE id = ?", (o.id,))
                    g.db().commit()
                if not store_pairs(o, res, who):
                    out["changed_meanwhile"] += 1
                    continue
                out[res["state"]] += 1
                out["truncated"] += 1 if res.get("truncated") else 0
                out["pairs"] += len(res["pairs"])
                out["probes"] += 1 if res.get("probe") else 0
                for kk, v in res["rejected"].items():
                    out["rejected"][kk] = out["rejected"].get(kk, 0) + v
                if res["state"] == "error":
                    out["reasons"][res["reason"][:80]] = out["reasons"].get(res["reason"][:80], 0) + 1
    return out


def pairs_report() -> dict:
    """How much knowledge is training-ready: objects by pair state (vi_stats, vi-mcp classify --pairs --dry-run)."""
    from . import qa_pairs
    with g.lock:
        rows = g.db().execute(
            "SELECT json_extract(data, '$.qa.state'), json_extract(data, '$.qa.version.prompt') = ?, COUNT(*), "
            "COALESCE(SUM(json_array_length(json_extract(data, '$.qa.pairs'))), 0), SUM(json_extract(data, '$.qa.probe') IS NOT NULL) "
            "FROM object WHERE kind IN ('insight', 'rule', 'skill') AND mode NOT IN ('quarantine', 'refuted', 'withdrawn', 'merged', 'archived') "
            "AND visibility <> 'private' GROUP BY 1, 2", (qa_pairs.prompt_sha256(),)).fetchall()
    out = {"objects": 0, "ok": 0, "empty": 0, "error": 0, "none": 0, "other_prompt": 0, "pairs": 0, "probes": 0}
    for state, current, n, pairs, probes in rows:
        out["objects"] += n
        if state is None:
            out["none"] += n
            continue
        if not current:
            out["other_prompt"] += n
        out[state if state in ("ok", "empty", "error") else "error"] += n
        out["pairs"] += int(pairs or 0)
        out["probes"] += int(probes or 0)
    return out

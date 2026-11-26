"""vi-mcp side of philosophy packages (0.66.0): the command line, installing a checked package into the VI, the tool vi_philosophy.

The technique itself is clingo_object.philosophy (standard library plus clingo, usable without a server). The user (15.11.2026): "Die
Philosophie-Technik muss als Skill vorhanden sein, damit man eine KI mit irgendeiner Philosophie ausstatten kann."
"""
from __future__ import annotations

import json
import re

from clingo_object import philosophy as ph

from . import memory as g

TAG = "topic:philosophie"
#: a binding is its own object (kind regel, visibility intern), not a config entry: it has an author, a change history and a tombstone
#: when it ends (mode aus), it reaches every server process and both databases without a restart, and an instance can read which
#: philosophy applies to it. It stores the name and the HASH it was bound to — a newer install does not silently take over.
BIND_TAG = "topic:philosophie-bindung"


def check_lines(r: dict) -> list[str]:
    head = "Package passes every check." if r["ok"] else f"Package refused: {len(r['errors'])} problem(s)."
    out = [head + (f" Hash {r['hash'][:16]}…" if r.get("hash") else "")]
    out += [f"  ✗ {e}" for e in r["errors"]] + [f"  ! {w}" for w in r["warnings"]]
    if r.get("worlds"):
        out.append(f"  worlds: {sum(1 for w in r['worlds'] if w['ok'])}/{len(r['worlds'])} as expected")
    for pred, cov in (r.get("coverage") or {}).items():
        out.append(f"  {pred}: " + " ".join(f"{v}{'✓' if ok else '✗'}" for v, ok in cov.items()))
    return out


def show_lines(pkg: dict, translation: dict | None = None) -> list[str]:
    """The stored package — seed, vocabulary, answers — and, if one exists, the latest DERIVED translation with its agreement."""
    bl, _problems = ph.blocks(pkg["seed"])
    out = [f"Philosophy {pkg['name']} {pkg['version']} — {pkg.get('description', '')}", f"Author: {pkg['author']} · profile "
           f"{pkg['profile'].get('semantics')} · priority {pkg['profile'].get('priority', 'none')} · hash {ph.package_hash(pkg)[:16]}…",
           "Only the seed is stored; prose is a translation checked by its round trip (vi-mcp philosophy explain).",
           "Blocks: " + ", ".join(f"{b} ({len(r)} rule{'s' if len(r) != 1 else ''})" for b, r in bl)]
    out += ["", "Inputs the world gives:"] + [f"  {k}/{v['arity']}: {v.get('doc', '')}" for k, v in ph.vocabulary(pkg).items() if v["kind"] == "input"]
    iface = [f"  {k}/{v['arity']}: {v.get('doc', '')}" for k, v in ph.vocabulary(pkg).items() if v["kind"] == "interface"]
    out += (["", "Read by the priority profile (given by the world or derived by the seed from evidence):"] + iface) if iface else []
    out += ["", "Answers:"] + [f"  {k}: {', '.join(v['values'])}" for k, v in pkg["answers"].items()]
    out += ["", "Seed (clingo-object notation):", pkg["seed"]]
    out += [""] + translation_lines(pkg, translation)
    return out


def translation_lines(pkg: dict, t: dict | None) -> list[str]:
    if not t:
        return ["Translation: none stored (vi-mcp philosophy explain NAME … --store makes one; it is derived, never a source)."]
    stale = t.get("seed_hash") != ph.package_hash(pkg)
    head = (f"DERIVED translation ({'STALE — made for hash ' + t.get('seed_hash', '?')[:16] + '…, the seed changed since' if stale else 'current'}): "
            f"translator {t.get('translator') or '?'}, back-translator {t.get('back_translator') or '?'}, {t.get('time', '?')}; whole seed "
            f"{t['whole']['same']}/{t['whole']['worlds']} worlds agree ({t['whole']['agreement']:.0%})"
            + (f", control {t['control']['agreement']:.0%}" if t.get("control") else ", no control"))
    out = [head, t["whole"]["prose"]]
    for b, x in (t.get("blocks") or {}).items():
        out.append(f"  {b} ({x['agreement']:.0%} of {x['worlds']} worlds): {x['prose']}")
    return out


def stored_translation(name: str) -> dict | None:
    """The newest derived translation stored on an installed object of this philosophy (needs the memory)."""
    for o in _installed_all(name):
        if o.data.get("translation"):
            return o.data["translation"]
    return None


def explain(ref: str, url: str | None, model: str | None, judge_url: str | None, judge_model: str | None, *, random_n: int = 50,
            per_block: bool = True, prose: str | None = None, control: str | None = None, proxy: bool = True,
            judge_cmd: str | None = None) -> dict:
    """The round trip of a philosophy (clingo_object.philosophy_explain): translator prose → independent back-translator → agreement
    with the original's answers and duties. prose: measure given prose instead (a model's recitation); control: a reference prose."""
    from clingo_object import philosophy_explain as pe
    if not judge_url and not judge_cmd:
        raise ValueError("explain needs a back-translator (judge_url, judge_model) — without the round trip a translation is unchecked")
    if prose is None and not url:
        raise ValueError("explain needs a translator (url, model), or prose to measure")
    pkg = ph.load(ref)
    names = {"translator": None if prose is not None else (model or "model at the translator URL"),
             "back_translator": pe.command_name(judge_cmd, judge_model) if judge_cmd else (judge_model or "model at the judge URL")}
    judge = pe.command_client(judge_cmd, judge_model) if judge_cmd else pe.chat_client(judge_url, judge_model, proxy=proxy)
    r = pe.round_trip(pkg, pe.chat_client(url, model, proxy=proxy) if prose is None else None, judge,
                      prose=prose, control=control, per_block=per_block and prose is None, random_n=random_n, names=names)
    if prose is None and (judge_model or judge_url) == (model or url):
        r["warning"] = "the same model translated and back-translated — not independent; prefer another model family as judge"
    return r


def store_translation(r: dict, who: str) -> g.MemoryObject:
    """Store a round-trip report as a DERIVED artifact on the installed object whose hash it was made for — never as a source."""
    o = next((x for x in _installed_all(r["package"]) if x.data["philosophy"]["hash"] == r["seed_hash"]), None)
    if o is None:
        raise ValueError(f"no installed {r['package']} with hash {r['seed_hash'][:16]}… — install it first, then store its translation")
    o.data = {**o.data, "translation": r}
    o.change(f"ki@{who}", "derived translation stored", f"round trip: whole seed {r['whole']['agreement']:.0%} of {r['whole']['worlds']} worlds"
             + (f", control {r['control']['agreement']:.0%}" if r.get("control") else ""))
    return g.save(o)


def installed() -> list[g.MemoryObject]:
    """The newest installed object per philosophy name."""
    newest: dict[str, g.MemoryObject] = {}
    for _s, o, _w in g.recall(TAG, limit=1000, viewer=None):
        p = o.data.get("philosophy") or {}
        if p.get("name") and o.mode not in ("refuted", "withdrawn", "archived") and (p["name"] not in newest or o.ts > newest[p["name"]].ts):
            newest[p["name"]] = o
    return sorted(newest.values(), key=lambda o: o.data["philosophy"]["name"])


def resolve(ref: str, viewer: str | None = None) -> dict:
    """0.69.6: a philosophy by name — built in, else the newest installed one the viewer may see, else a package directory on the server
    (administrators). Before 0.69.6 an installed philosophy could not be read or bound by its name unless it was built in."""
    if ref in ph.BUILTIN:
        return ph.load(ref)
    inst = [o for o in installed() if o.data["philosophy"]["name"] == ref and (viewer is None or g.visible_to(o, viewer))]
    if inst:
        return _package_of(inst[0])
    try:
        return ph.load(ref)
    except ph.PackageError as e:
        raise ph.PackageError(f"{ref}: neither built in ({', '.join(sorted(ph.BUILTIN))}) nor installed in this VI — install it with "
                              "vi_philosophy(action=\"install\", package={manifest, seed, worlds})") from e


def install(ref: str | None, instance: str, who: str | None = None, visibility: str | None = None, pkg: dict | None = None) -> g.MemoryObject:
    """Check, then store as a rule set object (vi_logic runs it) carrying the manifest and hash. Refused with the reasons if any check fails.
    pkg (0.69.6): a package handed over whole (from_parts) instead of a name. The names of the built-in philosophies are the package's;
    a name installed by another instance is that instance's — it publishes the new versions."""
    from . import logic
    if pkg is None:
        pkg = ph.load(ref or "")
    elif pkg.get("name") in ph.BUILTIN:
        raise ValueError(f"{pkg['name']} is a built-in philosophy — install yours under another name")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,50}", str(pkg.get("name") or "")):  # it becomes the rule set philosophie-<name>
        raise ValueError("the package's name: lower case, digits, - and _ (at most 51), e.g. bewusstsein")
    owner = next((o.instance for o in _installed_all(pkg["name"])), None)
    if owner and owner != instance and pkg["name"] not in ph.BUILTIN:
        raise ValueError(f"the philosophy {pkg['name']} was installed by {owner} — only {owner} installs its new versions")
    r = ph.check(pkg)
    if not r["ok"]:
        raise ValueError("package refused: " + "; ".join(r["errors"][:5]))
    o = logic.save_rule_set(f"philosophie-{pkg['name']}", pkg["seed"], f"philosophy {pkg['name']} {pkg['version']}: {pkg.get('description', '')}"[:300],
                            visibility, instance, who)
    o.hashtags = sorted(set(o.hashtags) | {TAG, f"philosophy:{pkg['name']}"})
    o.data = {**o.data, "philosophy": {**{k: v for k, v in pkg.items() if k != "seed"}, "hash": r["hash"],
                                         "check": {"worlds": len(r["worlds"]), "coverage": r["coverage"]}}}
    o.change(f"ki@{who or instance}", "philosophy installed", f"{pkg['name']} {pkg['version']} hash {r['hash'][:16]} — every check passed")
    return g.save(o)


def _installed_all(name: str) -> list[g.MemoryObject]:
    """Every installed object of one philosophy (all versions), newest first."""
    objs = [o for _s, o, _w in g.recall(TAG, limit=1000, viewer=None)
            if (o.data.get("philosophy") or {}).get("name") == name and o.mode not in ("refuted", "withdrawn", "archived")]
    return sorted(objs, key=lambda o: o.ts, reverse=True)


def _package_of(o: g.MemoryObject) -> dict:
    """The package an installed object holds (manifest + seed), as it was checked."""
    pkg = {k: v for k, v in o.data["philosophy"].items() if k not in ("hash", "check")}
    pkg["seed"] = o.data["logic"]["source"]
    return pkg


def _target(instance: str | None, index: str | None) -> tuple[str, str]:
    from . import indexes
    if bool(instance) == bool(index):
        raise ValueError("name exactly one target: an instance or an index")
    return ("instance", str(instance)) if instance else ("index", indexes.normalize(index))


def _active_bindings() -> list[g.MemoryObject]:
    return [o for _s, o, _w in g.recall(BIND_TAG, limit=1000, viewer=None)
            if o.mode == "active" and (o.data.get("philosophy_binding") or {}).get("name")]


def bind(name: str, who: str, instance: str | None = None, index: str | None = None, off: bool = False) -> str:
    """Bind an installed philosophy (its current hash) to an instance or an index, or end the binding (off: mode aus, kept as a
    tombstone with the reason). Several philosophies may apply to one target; their verdicts stay apart (evaluate_bound)."""
    kind, target = _target(instance, index)
    current = [o for o in _active_bindings() if o.data["philosophy_binding"]["name"] == name
               and (o.data["philosophy_binding"]["target_kind"], o.data["philosophy_binding"]["target"]) == (kind, target)]
    if off:
        if not current:
            return f"no active binding of {name} to {kind} {target} — nothing to end"
        for o in current:
            o.mode = "off"
            o.change(f"ki@{who}", "philosophy binding ended", f"{name} no longer applies to {kind} {target}")
            g.save(o)
        return f"ended: {name} no longer applies to {kind} {target} ({', '.join(o.id for o in current)} kept with mode aus)"
    objs = _installed_all(name)
    if not objs:
        raise ValueError(f"{name} is not installed — install it first (vi_philosophy action install, or vi-mcp philosophy install {name})")
    inst = objs[0]
    h = inst.data["philosophy"]["hash"]
    for o in current:
        if o.data["philosophy_binding"]["hash"] == h:
            return f"already bound: {name} {inst.data['philosophy']['version']} (hash {h[:16]}…) applies to {kind} {target} — {o.id}"
        o.mode = "off"
        o.change(f"ki@{who}", "philosophy binding replaced", f"rebound to hash {h[:16]}")
        g.save(o)
    meta = inst.data["philosophy"]
    o = g.new_object("rule", f"Philosophy binding: {name} {meta['version']} applies to {kind} {target}",
                     [BIND_TAG, f"philosophy:{name}"],
                     {"philosophy_binding": {"name": name, "version": meta["version"], "hash": h, "installed": inst.id,
                                              "profile": meta.get("profile"), "target_kind": kind, "target": target}},
                     importance=1, who=f"ki@{who}", reason="vi_philosophy use", instance=who,
                     visibility="internal")
    return f"bound {o.id}: {name} {meta['version']} (hash {h[:16]}…) applies to {kind} {target}"


def bindings(instance: str | None = None, index: str | None = None) -> list[dict]:
    """The philosophies that apply to an instance and/or an index, each with the hash it was bound to and a named state:
    current (the installed package has that hash) · stale (a newer install differs — the bound hash still decides) · missing."""
    out = []
    for o in _active_bindings():
        b = o.data["philosophy_binding"]
        if not ((b["target_kind"] == "instance" and b["target"] == instance) or (b["target_kind"] == "index" and index and b["target"] == index)):
            continue
        objs = _installed_all(b["name"])
        hashes = [x.data["philosophy"]["hash"] for x in objs]
        state = "missing" if b["hash"] not in hashes else ("current" if hashes[0] == b["hash"] else "stale")
        out.append({**b, "binding": o.id, "state": state})
    return sorted(out, key=lambda b: (b["name"], b["target_kind"]))


def evaluate_bound(facts: str, instance: str | None = None, index: str | None = None) -> dict:
    """The verdict of every philosophy that applies, NAMESPACED by philosophy and never merged (Codex: bind each query to one
    profile or return the verdicts of both apart). Each runs the package with the bound hash; a missing one gives no verdict."""
    out: dict[str, dict] = {}
    for b in bindings(instance, index):
        key = b["name"] if b["name"] not in out else f"{b['name']}@{b['target_kind']}"
        if b["state"] == "missing":
            out[key] = {"hash": b["hash"], "state": "missing", "verdict": None}
            continue
        o = next(x for x in _installed_all(b["name"]) if x.data["philosophy"]["hash"] == b["hash"])
        pkg = _package_of(o)
        if ph.package_hash(pkg) != b["hash"]:  # the stored package must still be the one that was checked and bound
            out[key] = {"hash": b["hash"], "state": "hash_mismatch", "verdict": None}
            continue
        out[key] = {"hash": b["hash"], "state": b["state"], "applies_to": f"{b['target_kind']} {b['target']}", "verdict": ph.evaluate(pkg, facts)}
    return out


def binding_lines(rows: list[dict]) -> list[str]:
    if not rows:
        return ["No philosophy is bound."]
    return [f"  {b['name']} {b['version']} → {b['target_kind']} {b['target']}: hash {b['hash'][:16]}… ({b['state']}) [{b['binding']}]" for b in rows]


# ── 0.73.0: a bound philosophy in the session instructions ─────────────────────────────────────────────────────────────────────────
# The user (26.11.2026): "Das muss auf jedem vi Server funktionieren insofern muss das Übersetzen das Modell machen. Wir haben nicht
# überall Codex. Ansonsten nehmen wir einen clingo Skill der im Server gespeichert ist." So the prose a session sees is translated by
# the server's OWN model (the classify model, else the llm), checked by the round trip, and shown only when it passes the gate; otherwise
# the session gets the name, the hash, the evaluate duty, the reason, and the server-stored clingo skill to read the seed itself.

GATE_AGREEMENT = 0.95  # whole-seed agreement over package + random worlds
GATE_RANDOM = 50       # at least this many random worlds besides the package's own
RETRY_DAYS = 7         # a translation that failed the gate is tried again by sleep after this many days, not every night
SAME_MODEL_NOTE = "same model translated and back-translated — weaker independence"
CLINGO_SKILL = "insight:skill-clingo"


def _model_cfg(section: dict | None) -> dict | None:
    return {k: section.get(k) for k in ("url", "token", "model")} if section and section.get("url") else None


def server_models() -> tuple[dict | None, dict | None]:
    """(translator, back-translator) from the server's own configuration — never an external service. Translator: the classify model,
    else the llm. Back-translator: the llm when it is a different model (url or model name), else the translator itself."""
    from . import config, reflection
    try:
        raw = config.read_raw(config.fpath())
    except Exception:  # noqa: BLE001
        raw = {}
    llm = _model_cfg(raw.get("llm") or reflection.config)
    translator = _model_cfg(raw.get("classify")) or llm  # as classify._config: its own section, else the server's llm
    if translator is None:
        return None, None
    other = llm is not None and (llm["url"], llm.get("model")) != (translator["url"], translator.get("model"))
    return translator, (llm if other else translator)


def model_label(cfg: dict) -> str:
    """How a server model is named in a report: its model name, else the path segment before /v1 of its URL (no host)."""
    if cfg.get("model"):
        return str(cfg["model"])
    m = re.search(r"/([^/]+)/v1/", str(cfg.get("url") or ""))
    return m.group(1) if m else "server model"


#: tests replace this: cfg -> (messages -> text)
client_fn = None


def model_client(cfg: dict):
    """A `messages -> text` function for a server model: temperature 0, thinking off, NO token cap (project rule), no proxy."""
    if client_fn is not None:
        return client_fn(cfg)
    import urllib.request
    from clingo_object import philosophy_explain as pe
    from clingo_object.agent import chat_post
    url = cfg["url"] if cfg["url"].rstrip("/").endswith("/chat/completions") else cfg["url"].rstrip("/") + "/chat/completions"
    header = {"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def chat(messages: list[dict]) -> str:
        body = {"messages": messages, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
                **({"model": cfg["model"]} if cfg.get("model") else {})}
        return pe.clean(chat_post(url, body, header, 600, opener)["choices"][0]["message"]["content"] or "")
    return chat


def gate(t: dict | None, pkg: dict) -> tuple[bool, str]:
    """Whether a stored translation may stand in the instructions, with the reason when not. Passes only with: made by the server's
    own model, for this package hash, ≥ GATE_RANDOM random worlds, whole-seed agreement ≥ GATE_AGREEMENT, and every package world."""
    if not t:
        return False, "no translation stored yet (sleep makes one with the server's model)"
    if t.get("seed_hash") != ph.package_hash(pkg):
        return False, f"the translation is stale: made for hash {str(t.get('seed_hash'))[:12]}…"
    if not t.get("server_model"):
        return False, "the stored translation was not made by this server's own model"
    w, whole = t.get("worlds") or {}, t.get("whole") or {}
    if whole.get("error"):
        return False, f"the back-translated seed did not run ({str(whole['error'])[:80]})"
    if int(w.get("random") or 0) < GATE_RANDOM:
        return False, f"only {w.get('random') or 0} random worlds (the gate needs {GATE_RANDOM})"
    if "package_same" not in whole:
        return False, "the report does not count the package worlds apart (made before 0.73.0)"
    if whole["package_same"] < whole["package_worlds"]:
        return False, f"{whole['package_worlds'] - whole['package_same']} of {whole['package_worlds']} package worlds disagree"
    if float(whole.get("agreement") or 0) < GATE_AGREEMENT:
        return False, (f"round trip {whole.get('same')}/{whole.get('worlds')} worlds ({float(whole.get('agreement') or 0):.0%}, "
                       f"the gate needs {GATE_AGREEMENT:.0%})")
    return True, ""


def explain_server(pkg: dict, random_n: int = GATE_RANDOM, control: str | None = None) -> dict:
    """The round trip with the server's own models (whole seed only — the instructions show the whole prose). The control is the
    package's own description unless another reference prose is given; it is reported beside the agreement, never a pass condition."""
    from clingo_object import philosophy_explain as pe
    tr, back = server_models()
    if tr is None:
        raise ValueError("no language model configured on this server (config classify or llm) — no translation; a session reads "
                         "the seed with the clingo skill")
    same = back is tr
    r = pe.round_trip(pkg, model_client(tr), model_client(back), control=control if control is not None else (pkg.get("description") or None),
                      per_block=False, random_n=random_n, names={"translator": model_label(tr), "back_translator": model_label(back)})
    r["server_model"], r["same_model"] = True, same
    if same:
        r["warning"] = SAME_MODEL_NOTE
    r["gate"] = dict(zip(("passed", "reason"), gate(r, pkg)))
    return r


def _installed_with(name: str, h: str) -> g.MemoryObject | None:
    return next((x for x in _installed_all(name) if x.data["philosophy"]["hash"] == h), None)


def translate_bound(who: str = "sleep", now=None) -> dict:
    """Sleep step: for every bound philosophy (its bound hash) without a translation that passes the gate, translate it with the
    server's model and store the report on the installed object — passed or not, so the block can name the reason. A failed one is
    tried again after RETRY_DAYS. Nothing bound or no model: nothing to do, named."""
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    bound = {(o.data["philosophy_binding"]["name"], o.data["philosophy_binding"]["hash"]) for o in _active_bindings()}
    if not bound:
        return {"state": "no philosophy bound"}
    if server_models()[0] is None:
        return {"state": "no model configured"}
    from . import logic  # the round trip runs the seed: clingo may live in the logic layer's own directory
    if not logic.available():
        return {"state": f"logic layer off ({logic.unavailable_reason()})"}
    done: dict[str, str] = {}
    for name, h in sorted(bound):
        key = f"{name}@{h[:12]}"
        o = _installed_with(name, h)
        if o is None:
            done[key] = "installed package missing"
            continue
        pkg, t = _package_of(o), o.data.get("translation")
        if gate(t, pkg)[0]:
            done[key] = "passed earlier"
            continue
        if t and t.get("server_model") and t.get("seed_hash") == h:
            try:
                age = now - dt.datetime.fromisoformat(str(t.get("time")).replace("Z", "+00:00"))
            except ValueError:
                age = dt.timedelta(days=RETRY_DAYS)
            if age < dt.timedelta(days=RETRY_DAYS):
                done[key] = f"failed {str(t.get('time'))[:10]}, next try after {RETRY_DAYS} days"
                continue
        try:
            r = explain_server(pkg)
        except Exception as e:  # noqa: BLE001 — a model error is named, never a broken sleep
            done[key] = f"error: {type(e).__name__}: {str(e)[:160]}"
            continue
        store_translation(r, who)
        done[key] = ("passed" if r["gate"]["passed"] else "failed: " + r["gate"]["reason"]) + f" ({r['whole']['same']}/{r['whole']['worlds']})"
    return done


def instruction_block(instance: str | None, index: str | None = None, room: int = 6000, compact: bool = False) -> str:
    """The [Philosophy] block: every philosophy bound to the instance or its index, with name, version and hash, and the duty to get
    verdicts from evaluate. Full form (the first prompt of a session): the checked prose when it passes the gate and fits the room.
    Compact form (the session instructions, which a client cuts at 4,096 characters): one short line per philosophy with the state
    of its prose and where to read it. Without a checked prose: the reason, and the way to read the seed itself — the server-stored
    clingo skill and vi_philosophy show. Empty when nothing is bound."""
    rows = bindings(instance, index if index and index != "global" else None)
    if not rows:
        return ""
    if compact:
        head = ("[Philosophy] Bound to you; its verdict comes only from vi_philosophy(action=\"evaluate\"): claim → facts → evaluate → "
                "act by the verdict, name it as the philosophy's.")
    else:
        head = ("[Philosophy] Bound to you. The binding verdict comes from vi_philosophy(action=\"evaluate\"), not from prose: before you "
                "assert a claim the philosophy covers, translate it into its facts, evaluate, act by the verdict and name it as the "
                "philosophy's. Prose below is a checked translation.")
    out, left = [head], room - len(head)
    for i, b in enumerate(rows):
        who = f"{b['name']} {b['version']} (hash {b['hash'][:12]}…" + ("" if compact else f", {b['target_kind']} {b['target']}")
        who += ", a newer version is installed — the bound hash decides)" if b["state"] == "stale" else ")"
        show = f"vi_philosophy(action=\"show\", name=\"{b['name']}\")"
        o = _installed_with(b["name"], b["hash"]) if b["state"] != "missing" else None
        if o is None:
            out.append(f"- {who}: the installed package is missing — no verdict until it is installed again.")
            left -= len(out[-1]) + 1
            continue
        t = o.data.get("translation")
        ok, why = gate(t, _package_of(o))
        line = ""
        if ok:
            w, prose = t["whole"], " ".join(str(t["whole"].get("prose") or "").split())
            check = (f"round trip {w['same']}/{w['worlds']} worlds incl. every package world, by {t.get('translator')} and "
                     f"{t.get('back_translator')}" + (f" ({SAME_MODEL_NOTE})" if t.get("same_model") else ""))
            reserve = 260 * (len(rows) - i - 1)  # room for the short lines of the philosophies after this one
            line = f"- {who}, checked prose ({check}): {prose}"
            if compact or len(line) + 1 > left - reserve:
                line = f"- {who}: checked prose ({check}) — {show} prints it."
        else:
            line = (f"- {who}: no checked prose — {why}. Read the seed yourself: vi_object {CLINGO_SKILL} (the notation) and {show}.")
        out.append(line)
        left -= len(line) + 1
    return "\n".join(out)


def block_report(instance: str | None, index: str | None = None) -> list[str]:
    """What a new session of this instance gets, with sizes (characters, and tokens as an estimate): the compact block in the
    instructions and the full block with the first prompt."""
    from .context_budget import CHARS_PER_TOKEN, estimate_tokens
    full, compact = instruction_block(instance, index), instruction_block(instance, index, compact=True)
    if not full:
        return []
    size = (lambda t: f"{len(t)} characters, ≈ {estimate_tokens(t)} tokens")
    return ["", f"In the session instructions ({size(compact)} — tokens estimated at {CHARS_PER_TOKEN} characters per token):", compact,
            "", f"With the first prompt of a session ({size(full)}):", full]


def tool(args: dict, instance: str) -> str:
    """vi_philosophy: guide (default) · list · show · check · evaluate · install · use · bound · explain · kit."""
    action = args.get("action") or "guide"
    if action == "guide":
        return ph.GUIDE
    if action in ("check", "evaluate", "install", "explain", "kit"):  # 0.69.7: these run the seed — clingo may live in the logic layer's own
        from . import logic                                    # directory, which only logic.available() puts on sys.path
        if not logic.available():
            raise ValueError(f"the logic layer is off on this server ({logic.unavailable_reason()}) — an administrator runs: "
                             "sudo vi-mcp logic install")
    if action == "list":
        inst = installed()
        lines = ["Built in: " + ", ".join(sorted(ph.BUILTIN))]
        lines += ["Installed: " + (", ".join(f"{o.data['philosophy']['name']} {o.data['philosophy']['version']} ({o.id})" for o in inst) or "none")]
        lines += ["Bound to you:"] + binding_lines(bindings(instance, args.get("index")))
        return "\n".join(lines)
    if action == "bound":
        return "\n".join([f"Philosophies that apply to instance {instance}" + (f" and index {args['index']}" if args.get("index") else "") + ":"]
                         + binding_lines(bindings(instance, args.get("index"))) + block_report(instance, args.get("index")))
    if action in ("suggest", "rate"):  # 0.69.6: which philosophy fits which situation — declared, measured, learned
        from . import philosophy_fit as pf
        if action == "suggest":
            return "\n".join(pf.lines(pf.suggest(str(args.get("situation") or ""), args.get("tags"), instance)))
        if not isinstance(args.get("helped"), bool):
            raise ValueError("rate needs helped: true or false")
        return json.dumps(pf.rate(str(args.get("name") or ""), args.get("tags"), args["helped"], instance, str(args.get("reason") or "")),
                          ensure_ascii=False)
    if action == "evaluate" and not args.get("name"):
        return json.dumps(evaluate_bound(str(args.get("facts") or ""), instance, args.get("index")), ensure_ascii=False, indent=1)
    if action == "install" and args.get("package") is not None:  # 0.69.6: a philosophy handed over MCP
        p = args["package"] if isinstance(args["package"], dict) else {}
        pkg = ph.from_parts(p.get("manifest"), p.get("seed"), p.get("worlds"))
        o = install(None, instance, None, args.get("visibility") or "internal", pkg=pkg)
        return f"installed {o.id} — philosophy {pkg['name']} {pkg['version']}, hash {o.data['philosophy']['hash'][:16]}…"
    ref = str(args.get("name") or "")
    if not ref:
        raise ValueError(f"{action} needs name — a built-in philosophy ({', '.join(sorted(ph.BUILTIN))}), an installed one, or for "
                         "install a package={manifest, seed, worlds}")
    pkg = resolve(ref, instance)
    if action == "export":  # 0.69.6: the whole package, as install takes it
        return json.dumps(ph.to_parts(pkg), ensure_ascii=False, indent=1)
    if action == "show":
        return "\n".join(show_lines(pkg, stored_translation(pkg["name"])))
    if action == "explain":
        from clingo_object import philosophy_explain as pe
        r = explain(ref, args.get("url"), args.get("model"), args.get("judge_url"), args.get("judge_model"),
                    random_n=int(args.get("random") if args.get("random") is not None else 50), per_block=not args.get("whole_only"),
                    prose=args.get("prose"), control=args.get("control"))
        lines = pe.summary_lines(r) + ([f"  ! {r['warning']}"] if r.get("warning") else [])
        if args.get("store"):
            lines.append(f"stored as a derived translation on {store_translation(r, instance).id}")
        return "\n".join(lines + ["", "Prose (derived):", r["whole"]["prose"]])
    if action == "check":
        return "\n".join(check_lines(ph.check(pkg)))
    if action == "evaluate":
        return json.dumps(ph.evaluate(pkg, str(args.get("facts") or "")), ensure_ascii=False, indent=1)
    if action == "kit":  # 0.70.1: the training kit for the seed path — nothing of the memory in it, so it may be built over MCP
        from . import finetune
        r, built = finetune.philosophy_kit_on_server(ref, args.get("base_model"), int(args.get("seed") or 11),
                                                      int(args.get("rows") or finetune.PHILOSOPHY_ROWS))
        return "\n".join(kit_lines(r, built))
    if action == "install":
        o = install(ref, instance, None, args.get("visibility") or "internal")
        return f"installed {o.id} — philosophy {pkg['name']} {pkg['version']}, hash {o.data['philosophy']['hash'][:16]}…"
    if action == "use":
        target = args.get("instance")
        if target and target != instance:  # a seed never overrides tool rights: an instance binds itself; an administrator binds others
            raise ValueError(f"an instance binds only itself — bind {target} with: vi-mcp philosophy use {pkg['name']} --instance {target}")
        idx = args.get("index")
        return bind(pkg["name"], instance, None if idx else instance, idx, bool(args.get("off")))
    raise ValueError(f"unknown action {action}")


def kit_lines(r: dict, built: bool = True) -> list[str]:
    p = r.get("philosophy") or {}
    ph_ = p.get("philosophy") or {}
    rec = ph_.get("recipe") or {}
    return [f"{'Built' if built else 'Already built (same package, seed, rows and base model)'}: {r['directory']}",
            f"  philosophy {p.get('name')} {p.get('version')} (hash {str(p.get('hash'))[:16]}…), base model {r.get('base_model')}, "
            f"memory exported: {'no' if r.get('memory_exported') is False else 'yes'}",
            f"  language rows {(p.get('language') or {}).get('train')}, seed-stage rows {ph_.get('train')} ({ph_.get('format')}), "
            f"held-out rows {ph_.get('test')}, GRPO prompts {p.get('prompts')}",
            f"  evaluation items {sum(((p.get('eval') or {}).get('items') or {}).values())}: "
            + ", ".join(f"{k} {v}" for k, v in ((p.get("eval") or {}).get("items") or {}).items()),
            *([f"  worlds by statements {rec.get('statements')}, rare cases {rec.get('cases_in_judged_rows')}"] if rec else []),
            "  Next (a person, on a GPU host — copy the directory there): python train.py --stage language --fp32, then --stage "
            "philosophy, optionally --stage grpo; python phil_answers.py; python phil_score.py; vi-mcp finetune record DIR."]


def _cli_installed(name: str, k) -> dict:
    g.open_db(k.db)
    try:
        return resolve(name)
    finally:
        g.close_db()


def main(argv: list[str]) -> int:
    """vi-mcp philosophy guide | list | show REF | check REF | new DIR --name N [--author A] | evaluate REF --facts FILE | install REF
    | explain REF --url U --model M --judge-url U2 --judge-model M2 [--random N] [--prose F] [--control F] [--store]
    | explain REF --server-model [--random N] [--control F] [--store]
    | shadow kollektiv [--limit N] [--db COPY] [--json F]
    | use NAME --instance I | --index X [--off] | bound --instance I | --index X"""
    import argparse
    a = argparse.ArgumentParser(prog="vi-mcp philosophy", description="equip an AI with a philosophy: packages of a clingo-object seed and test worlds")
    u = a.add_subparsers(dest="cmd", required=True)
    u.add_parser("guide", help="the technique, step by step")
    u.add_parser("list", help="built-in and installed philosophies")
    for c in ("show", "check"):
        u.add_parser(c).add_argument("ref", help="built-in name or package directory")
    nw = u.add_parser("new", help="write a minimal valid package to start from")
    nw.add_argument("directory")
    nw.add_argument("--name", required=True)
    nw.add_argument("--author", default="unknown")
    ev = u.add_parser("evaluate", help="the seed's verdict on facts (clingo-object notation)")
    ev.add_argument("ref")
    ev.add_argument("--facts", required=True, help="file with facts")
    ex = u.add_parser("explain", help="translate the seed into prose and check it by the round trip prose → seed → same verdicts")
    ex.add_argument("ref")
    ex.add_argument("--url", help="translator: OpenAI-compatible endpoint (…/v1)")
    ex.add_argument("--model", help="translator model name")
    jx = ex.add_mutually_exclusive_group(required=True)
    jx.add_argument("--judge-url", help="independent back-translator endpoint (preferably another model family)")
    jx.add_argument("--server-model", action="store_true", help="0.73.0: translate AND back-translate with this server's own models (config "
                                                                 "classify, else llm; the llm back-translates when it is another model) — what "
                                                                 "sleep does for a bound philosophy; the control is the package description")
    jx.add_argument("--judge-cmd", help="a command-line back-translator, e.g. \"codex exec -s read-only --skip-git-repo-check\" "
                                        "(command line only — the MCP tool never runs a command a caller names)")
    ex.add_argument("--judge-model", help="back-translator model name")
    ex.add_argument("--random", type=int, default=50, help="random worlds from the package's generator besides its own worlds (default 50)")
    ex.add_argument("--whole-only", action="store_true", help="only the whole seed, not each block")
    ex.add_argument("--prose", help="measure this prose (a file, e.g. a model's recitation) instead of translating")
    ex.add_argument("--control", help="a reference prose (file), back-translated alike and reported beside every number")
    ex.add_argument("--no-proxy", action="store_true", help="talk to the endpoints without the environment's proxy")
    ex.add_argument("--json", help="write the full report to this file")
    ex.add_argument("--store", action="store_true", help="store the report on the installed object of this hash (derived, never a source)")
    sh = u.add_parser("shadow", help="kollektiv's acceptance from the memory's provenance next to today's object mode — changes nothing")
    sh.add_argument("name")
    sh.add_argument("--limit", type=int)
    sh.add_argument("--db", help="a database file (use a COPY: opening it may migrate its schema); default: the configured one")
    sh.add_argument("--json", help="write the full report to this file")
    kt = u.add_parser("kit", help="write the training kit for the seed path only (no memory content) — language, philosophy and GRPO stages")
    kt.add_argument("ref")
    kt.add_argument("directory")
    kt.add_argument("--base", help="the model to fine-tune (Hugging Face id or directory); default: config finetune.base_model")
    kt.add_argument("--seed", type=int, default=11)
    kt.add_argument("--rows", type=int, help="seed-stage rows (default: the kit's PHILOSOPHY_ROWS)")
    ins = u.add_parser("install", help="check and store in the VI as a rule set")
    ins.add_argument("ref")
    ins.add_argument("--visibility", choices=["shared", "internal"], default="internal")
    us = u.add_parser("use", help="bind an installed philosophy (its current hash) to an instance or an index")
    us.add_argument("name")
    for c in (us, u.add_parser("bound", help="which philosophies and hashes apply to an instance or an index")):
        t = c.add_mutually_exclusive_group(required=True)
        t.add_argument("--instance")
        t.add_argument("--index")
    us.add_argument("--off", action="store_true", help="end the binding (kept with mode aus)")
    o = a.parse_args(argv)
    if o.cmd == "guide":
        print(ph.GUIDE)
        return 0
    if o.cmd == "new":
        d = ph.write(ph.template(o.name, o.author), o.directory)
        print(f"written {d} — edit philosophy.json, seed.co and worlds.jsonl, then: vi-mcp philosophy check {d}")
        return 0
    if o.cmd == "show":
        print("\n".join(show_lines(ph.load(o.ref))))  # without the memory; vi_philosophy show adds a stored translation
        return 0
    if o.cmd == "shadow":
        from . import philosophy_provenance
        return philosophy_provenance.main_shadow(o.name, o.limit, o.db, o.json)
    if o.cmd == "explain":
        from pathlib import Path
        from clingo_object import philosophy_explain as pe
        read = (lambda f: Path(f).read_text(encoding="utf-8") if f else None)
        if o.server_model:
            from . import config, reflection
            k = config.load()
            reflection.config = k.llm or {}
            r = explain_server(ph.load(o.ref) if o.ref in ph.BUILTIN or "/" in o.ref else _cli_installed(o.ref, k), o.random, read(o.control))
            print("\n".join(pe.summary_lines(r) + ([f"  ! {r['warning']}"] if r.get("warning") else [])
                             + [f"  gate: {'passed' if r['gate']['passed'] else 'failed — ' + r['gate']['reason']}"]))
        else:
            r = explain(o.ref, o.url, o.model, o.judge_url, o.judge_model, random_n=o.random, per_block=not o.whole_only,
                        prose=read(o.prose), control=read(o.control), proxy=not o.no_proxy, judge_cmd=o.judge_cmd)
            print("\n".join(pe.summary_lines(r) + ([f"  ! {r['warning']}"] if r.get("warning") else [])))
        if o.json:
            Path(o.json).write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"report: {o.json}")
        if not o.store:
            return 0
        from . import config
        g.open_db(config.load().db)
        try:
            print(f"stored as a derived translation on {store_translation(r, 'admin').id}")
        finally:
            g.close_db()
        return 0
    if o.cmd == "check":
        r = ph.check(ph.load(o.ref))
        print("\n".join(check_lines(r)))
        return 0 if r["ok"] else 1
    if o.cmd == "kit":
        from . import finetune
        r = finetune.philosophy_kit(o.directory, o.ref, o.base, o.seed, o.rows or finetune.PHILOSOPHY_ROWS)
        print("\n".join(kit_lines(r)))
        return 0
    if o.cmd == "evaluate":
        from pathlib import Path
        print(json.dumps(ph.evaluate(ph.load(o.ref), Path(o.facts).read_text(encoding="utf-8")), ensure_ascii=False, indent=1))
        return 0
    from . import config
    g.open_db(config.load().db)
    try:
        if o.cmd == "list":
            print(tool({"action": "list"}, "admin"))
        elif o.cmd == "install":
            ob = install(o.ref, "admin", "admin", o.visibility)
            print(f"installed {ob.id} (hash {ob.data['philosophy']['hash'][:16]}…)")
        elif o.cmd == "use":
            print(bind(o.name, "admin", o.instance, o.index, o.off))
        elif o.cmd == "bound":
            print("\n".join(binding_lines(bindings(o.instance, o.index))))
    finally:
        g.close_db()
    return 0

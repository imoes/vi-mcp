"""0.73.0: a bound philosophy reaches every session. The instructions carry the compact block (the evaluate duty, name, version, hash,
the state of the checked prose); the first prompt carries the full block with the prose. The prose is translated by the server's OWN
model (the user, 26.11.2026: "Das muss auf jedem vi Server funktionieren insofern muss das Übersetzen das Modell machen. Wir haben nicht
überall Codex. Ansonsten nehmen wir einen clingo Skill der im Server gespeichert ist."), checked by the round trip, shown only when it
passes the gate; otherwise the session reads the seed itself with the server-stored clingo skill. Models are functions here."""
import datetime as dt
import json
import threading

import pytest

pytest.importorskip("clingo")

from clingo_object import philosophy as ph  # noqa: E402
from vi_mcp import config, intuition, philosophy, philosophy_fit, server, tools  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

T = {"url": "http://translator/v1", "token": "", "model": "m-translate"}
B = {"url": "http://back/v1", "token": "", "model": "m-back"}
PROSE = "A member never confirms its own statement; support and opposition are counted apart."


def _rules(pkg):
    return "\n".join(r for _b, rs in ph.blocks(pkg["seed"])[0] for r in rs)


def _models(monkeypatch, back=B, faithful=True):
    """Translator writes PROSE; back-translator returns the seed's rules (faithful) or the rules without self-confirmation (lossy).
    With back=T the same model does both and answers by the request it gets."""
    pkg = ph.load("kollektiv")
    rules = _rules(pkg) if faithful else _rules(pkg).replace(" & (I != A)", "")
    monkeypatch.setattr(philosophy, "server_models", lambda: (T, back))
    monkeypatch.setattr(philosophy, "client_fn", lambda cfg: (
        lambda m: PROSE if m[0]["content"].startswith("You translate logic rules") else rules))


def _bind(name="kollektiv", instance="a"):
    tools.call_tool("vi_philosophy", {"action": "install", "name": name}, instance, False)
    tools.call_tool("vi_philosophy", {"action": "use", "name": name}, instance, False)


def test_nothing_bound_no_block_and_sleep_names_it(gd):
    assert philosophy.instruction_block("a") == ""
    tools.call_tool("vi_philosophy", {"action": "install", "name": "kollektiv"}, "a", False)  # installed, not bound
    assert philosophy.instruction_block("a") == "" and philosophy.instruction_block("a", compact=True) == ""
    assert philosophy.translate_bound() == {"state": "no philosophy bound"}


def test_bound_without_translation_falls_back_to_the_server_clingo_skill(gd, monkeypatch):
    _bind()
    h = ph.package_hash(ph.load("kollektiv"))
    for compact in (False, True):
        block = philosophy.instruction_block("a", compact=compact)
        assert block.startswith("[Philosophy]") and 'vi_philosophy(action="evaluate")' in block
        assert f"kollektiv 1.3.0 (hash {h[:12]}…" in block and "no checked prose — no translation stored yet" in block
        assert "vi_object insight:skill-clingo" in block and 'vi_philosophy(action="show", name="kollektiv")' in block
    assert philosophy.instruction_block("b") == ""  # another instance is not bound
    monkeypatch.setattr(philosophy, "server_models", lambda: (None, None))
    assert philosophy.translate_bound() == {"state": "no model configured"}


def test_sleep_translates_with_the_server_model_and_a_passing_prose_is_shown(gd, monkeypatch):
    _bind()
    _models(monkeypatch)
    done = philosophy.translate_bound()
    (key, state), = done.items()
    assert key.startswith("kollektiv@") and state.startswith("passed")
    t = philosophy.stored_translation("kollektiv")
    assert t["server_model"] and not t["same_model"] and t["translator"] == "m-translate" and t["back_translator"] == "m-back"
    assert t["worlds"]["random"] >= philosophy.GATE_RANDOM and t["whole"]["package_same"] == t["whole"]["package_worlds"] > 0
    assert "control" in t and t["gate"]["passed"]  # the package description is the control, reported beside it
    full = philosophy.instruction_block("a")
    assert PROSE in full and "checked prose (round trip" in full and "weaker independence" not in full
    compact = philosophy.instruction_block("a", compact=True)
    assert PROSE not in compact and "checked prose (round trip" in compact and 'vi_philosophy(action="show", name="kollektiv") prints it' in compact
    assert philosophy.translate_bound()[key] == "passed earlier"  # nothing runs twice


def test_the_same_model_is_named_as_weaker_independence(gd, monkeypatch):
    _bind()
    _models(monkeypatch, back=T)
    philosophy.translate_bound()
    t = philosophy.stored_translation("kollektiv")
    assert t["same_model"] and t["warning"] == philosophy.SAME_MODEL_NOTE
    assert "same model translated and back-translated — weaker independence" in philosophy.instruction_block("a")


def test_a_lossy_translation_fails_the_gate_is_named_and_retried_only_after_days(gd, monkeypatch):
    _bind()
    _models(monkeypatch, faithful=False)
    (key, state), = philosophy.translate_bound().items()
    assert state.startswith("failed: ")
    block = philosophy.instruction_block("a")
    assert PROSE not in block and "no checked prose — " in block and "insight:skill-clingo" in block
    assert "next try after" in philosophy.translate_bound()[key]  # not every night
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=philosophy.RETRY_DAYS + 1)
    _models(monkeypatch)
    assert philosophy.translate_bound(now=later)[key].startswith("passed")


def test_the_gate_demands_every_package_world_enough_random_worlds_the_server_model_and_the_hash():
    pkg = ph.load("kollektiv")
    good = {"seed_hash": ph.package_hash(pkg), "server_model": True, "worlds": {"package": 10, "random": 50},
            "whole": {"agreement": 0.98, "same": 59, "worlds": 60, "package_same": 10, "package_worlds": 10}}
    assert philosophy.gate(good, pkg) == (True, "")
    cases = [({**good, "seed_hash": "0" * 64}, "stale"), ({**good, "server_model": False}, "not made by this server's own model"),
             ({**good, "worlds": {"package": 10, "random": 20}}, "only 20 random worlds"),
             ({**good, "whole": {**good["whole"], "package_same": 9}}, "1 of 10 package worlds disagree"),
             ({**good, "whole": {**good["whole"], "agreement": 0.9, "same": 54}}, "the gate needs 95%"),
             ({**good, "whole": {k: v for k, v in good["whole"].items() if not k.startswith("package")}}, "made before 0.73.0"),
             (None, "no translation stored yet")]
    for t, why in cases:
        ok, reason = philosophy.gate(t, pkg)
        assert not ok and why in reason, (why, reason)


def test_a_stale_binding_and_a_stale_translation_are_marked(gd, monkeypatch, tmp_path):
    _bind()
    _models(monkeypatch)
    philosophy.translate_bound()
    newer = ph.load("kollektiv")
    newer["version"] = "1.3.1"
    philosophy.install(str(ph.write(newer, str(tmp_path / "k2"))), "a")
    block = philosophy.instruction_block("a")
    assert "a newer version is installed — the bound hash decides" in block and PROSE in block  # the bound hash's prose still holds
    t = philosophy.stored_translation("kollektiv") or g.load(philosophy.bindings("a")[0]["installed"]).data["translation"]
    assert "stale" in philosophy.gate(t, newer)[1]  # a translation never carries over to another hash


def test_server_models_come_from_the_servers_own_config(tmp_path, monkeypatch):
    from vi_mcp import reflection
    p = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(p))
    monkeypatch.setattr(reflection, "config", None)
    config.create_instance("a")
    raw = json.loads(p.read_text())
    for cfg, want in (({}, (None, None)), ({"llm": {"url": "http://l/v1", "model": "L"}}, ("L", "L")),
                      ({"llm": {"url": "http://l/v1", "model": "L"}, "classify": {"url": "http://c/v1", "model": "C"}}, ("C", "L")),
                      ({"classify": {"url": "http://c/v1", "model": "C"}}, ("C", "C"))):
        p.write_text(json.dumps({**raw, **cfg}))
        tr, back = philosophy.server_models()
        assert ((tr or {}).get("model"), (back or {}).get("model")) == want, cfg
        assert tr is None or (back is tr) == (want[0] == want[1])  # one model doing both is the same object: same_model


@pytest.fixture
def srv(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("anna")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db")})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], tok
    s.shutdown()
    s.server_close()
    server.finish([s])


def test_the_instructions_carry_the_compact_block_within_the_cut(srv, monkeypatch, capsys):
    from test_http import request
    from vi_mcp.context_budget import estimate_tokens
    port, tok = srv
    for i in range(40):  # a full index, as in test_instructions_budget
        g.new_object("insight", f"The user decided rule number {i}: deploys need a ticket and a named reviewer every time",
                     ["topic:requirement"], {"source": "test"}, instance="anna")
    _bind(instance="anna")
    _models(monkeypatch)
    philosophy.translate_bound()
    _, _, a = request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "t"}}}, tok)
    ins = a["result"]["instructions"]
    assert len(ins) <= server.INSTRUCTIONS_BUDGET < 4096 and "cut at the client limit" not in ins
    assert ins.index("Rules for the VI") < ins.index("[Philosophy]") < ins.index("[Index]")  # early: right after the rules
    assert "NEVER learn passwords" in ins and "kollektiv 1.3.0" in ins and "checked prose (round trip" in ins and PROSE not in ins
    block = philosophy.instruction_block("anna", compact=True)
    nxt = [k for k in (ins.find("[Training]"), ins.find("[Self]"), ins.find("[Network]")) if k > 0]
    assert (min(nxt) if nxt else len(ins)) - ins.index("[Index]") >= server.PHIL_INDEX_MIN - 50
    with capsys.disabled():  # the size of the block, reported with the run
        print(f"\n  [Philosophy] in the instructions: {len(block)} characters, ≈ {estimate_tokens(block)} tokens (estimate); "
              f"instructions {len(ins)} of {server.INSTRUCTIONS_BUDGET}")
    out = tools.call_tool("vi_philosophy", {"action": "bound"}, "anna", False)
    assert "In the session instructions (" in out and "tokens" in out and "With the first prompt of a session (" in out


def test_the_first_prompt_carries_the_full_block_once_per_conversation(gd, monkeypatch):
    _bind()
    _models(monkeypatch)
    philosophy.translate_bound()
    r = intuition.prompt_hints("How should I decide whether this claim is accepted?", "a", [])
    assert r["hinweise"][0].startswith("[Philosophy]") and PROSE in r["hinweise"][0] and "philosophy-bound:a" in r["ids"]
    again = intuition.prompt_hints("And the next one?", "a", r["ids"])
    assert not any(h.startswith("[Philosophy]") for h in again["hinweise"])
    assert not any(h.startswith("[Philosophy]") for h in intuition.prompt_hints("a question", "b", [])["hinweise"])


def test_the_context_line_suggests_only_unbound_philosophies(gd, monkeypatch):
    tools.call_tool("vi_philosophy", {"action": "install", "name": "kollektiv"}, "a", False)
    fit = {"situation": ["topic:claim"], "ranking": [{"name": "kollektiv", "matched": [
        {"tag": "topic:claim", "declared": True, "helped": 0, "not_helped": 0}]}]}
    monkeypatch.setattr(philosophy_fit, "suggest", lambda text, tags, viewer, rng=None: fit)
    line, pid = philosophy_fit.context_line("is this claim accepted", "a", [])
    assert pid == "philosophy:kollektiv" and "fits the philosophy kollektiv" in line
    _bind()
    assert philosophy_fit.context_line("is this claim accepted", "a", []) == (None, None)  # bound: in the instructions already

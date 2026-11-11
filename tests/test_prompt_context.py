"""0.44.0: memory for every user prompt — follow-up questions find the VI too (Claude Code UserPromptSubmit, Hermes pre_llm_call)."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from vi_mcp import intuition, setup as e, tools
from vi_mcp import memory as g

from test_einrichten import HERMES, target  # noqa: F401
from test_http import srv  # noqa: F401

_spec = importlib.util.spec_from_file_location("vi_hook_p", Path(__file__).parent.parent / "hook" / "vi_hook.py")
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def _k(text, tags, **kw):
    return g.new_object("erkenntnis", text, tags, {"quelle": "Messung 11.11.2026"}, instance="a", **kw)


def test_prompt_words():
    assert intuition.prompt_words("Und warum hängt ssh nach buildhost07 bei der Passwortabfrage?") == ["hängt", "ssh", "buildhost07", "Passwortabfrage"]
    assert intuition.prompt_words("und was ist das?") == []
    assert intuition.prompt_words("Exit 137 on host db01.example.org") == ["Exit", "host", "db01.example.org"]


def test_follow_up_question_finds_the_memory(gd):
    k = _k("ssh to the build host hangs at the password prompt without -i; use the key file", ["tool:ssh", "thema:ssh"])
    _k("Borg restore needs the repository key", ["tool:borg"])
    r = intuition.prompt_hints("und warum hängt ssh am build host?", "a")
    assert r["ids"] == [k.id] and "vi_object" in r["hinweise"][0]
    assert intuition.prompt_hints("und warum hängt ssh am build host?", "a", shown=[k.id])["ids"] == []  # not repeated in one conversation
    assert intuition.prompt_hints("danke, das war es", "a")["hinweise"] == []
    assert intuition.prompt_hints("wie ist das wetter morgen am meer", "a")["hinweise"] == []  # no shared words, no noise


def test_a_host_name_alone_is_enough_and_compounds_are_split(gd):
    """Measured with Claude Code 11.11.2026: "Meine ssh-Verbindung zu buildhost07 hängt" missed the knowledge "ssh to buildhost07 hangs …"."""
    k = _k("ssh to buildhost07 hangs at the password prompt without -i; use the key file", ["host:buildhost07", "tool:ssh"])
    assert "ssh" in intuition.prompt_words("Meine ssh-Verbindung zu buildhost07 hängt")
    assert intuition.prompt_hints("Kurze Frage: Meine ssh-Verbindung zu buildhost07 hängt. Woran liegt das?", "a")["ids"] == [k.id]
    assert intuition.prompt_hints("Was läuft auf buildhost07?", "a")["ids"] == [k.id]  # a host name is specific: it counts 2
    assert intuition.prompt_hints("Wie ist das Passwort-Prompt Verhalten bei Telnet?", "a")["ids"] == []  # one plain shared word is not enough


def test_most_shared_words_first_and_host_only_noise_dropped(gd):
    """0.44.1, measured on production: notes that shared only the host name ranked before the one that answered the question."""
    noise = [_k(f"ssh to buildhost07 note number {i} about the login banner", ["host:buildhost07"]) for i in range(3)]
    k = _k("buildhost07 kills large models with exit 137: mlock OOM, use load-mode mmap", ["host:buildhost07", "fehler:exit-137"])
    r = intuition.prompt_hints("Und warum stirbt das große Modell auf buildhost07 mit Exit 137?", "a")
    assert r["ids"][0] == k.id and not set(r["ids"]) & {n.id for n in noise}
    assert set(intuition.prompt_hints("Was läuft auf buildhost07?", "a")["ids"]) <= {k.id, *[n.id for n in noise]}  # host alone still finds


def test_disputed_and_private_of_others_stay_out(gd):
    d = _k("ssh build host needs agent forwarding always", ["tool:ssh"])
    d.mode = "strittig"
    g.save(d)
    g.new_object("erkenntnis", "ssh build host private note of bert", ["tool:ssh"], {"quelle": "q"}, instance="bert", visibility="privat")
    assert intuition.prompt_hints("ssh build host", "a")["ids"] == []


def test_tool_and_open_instance(gd):
    k = _k("ssh to the build host hangs at the password prompt without -i", ["tool:ssh"])
    out = json.loads(tools.call_tool("vi_prompt_context", {"prompt": "ssh build host hangs", "shown": []}, "offen", False))
    assert out["ids"] == [k.id]


@pytest.fixture()
def h(srv, tmp_path, monkeypatch):  # noqa: F811
    port, tok, _ = srv
    (tmp_path / "token").write_text(tok + "\n")
    monkeypatch.setattr(hook, "URL", f"http://127.0.0.1:{port}/mcp")
    monkeypatch.setattr(hook, "TOKEN_FILE", tmp_path / "token")
    monkeypatch.setattr(hook, "STATE", tmp_path / "hook")
    monkeypatch.setattr(hook, "SIGNAL_TOKEN_FILE", tmp_path / "missing-signal-token")
    return hook


def test_hook_user_prompt_submit_gives_context_once(h):
    k = _k("ssh to the build host hangs at the password prompt without -i; use the key file", ["tool:ssh"])
    ev = {"hook_event_name": "UserPromptSubmit", "session_id": "cc-9", "cwd": "/tmp", "prompt": "und warum hängt ssh am build host? password=geheim123"}
    out = h.process(ev)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" and k.id in ctx and ctx.startswith("[VI memory for this question")
    assert h.process(ev) is None  # the same hint is not repeated in this conversation
    assert h.process({**ev, "prompt": "/compact"}) is None
    # a correction without signal token does not cost the context
    k2 = _k("borg restore needs the repository key exported first", ["tool:borg"])
    out = h.process({**ev, "prompt": "nein, ich meine borg restore mit repository key"})
    assert k2.id in out["hookSpecificOutput"]["additionalContext"]


def test_prompt_is_masked_and_not_stored(h):
    _k("ssh to the build host hangs at the password prompt without -i", ["tool:ssh"])
    h.process({"hook_event_name": "UserPromptSubmit", "session_id": "cc-8", "cwd": "/tmp", "prompt": "ssh build host hangs password=geheim123"})
    with g.lock:
        dump = json.dumps([list(r) for r in g.db().execute("SELECT * FROM objekt")]) + json.dumps([list(r) for r in g.db().execute("SELECT * FROM nutzung")])
    assert "geheim123" not in dump and "ssh build host hangs" not in dump


def test_hermes_payload(h, monkeypatch):
    k = _k("ssh to the build host hangs at the password prompt without -i", ["tool:ssh"])
    # the shape Hermes really sends to a shell hook (captured 11.11.2026 with `hermes hooks test pre_llm_call`)
    payload = {"hook_event_name": "pre_llm_call", "tool_name": None, "tool_input": None, "session_id": "h-1", "cwd": "/tmp",
               "extra": {"user_message": "warum hängt ssh am build host", "conversation_history": [], "is_first_turn": False, "model": "x", "platform": "cli"}}
    out = h.hermes(payload)
    assert set(out) == {"context"} and k.id in out["context"]
    flat = {"hook_event_name": "pre_llm_call", "session_id": "h-2", "user_message": "warum hängt ssh am build host"}  # plugin shape
    assert k.id in h.hermes(flat)["context"]
    assert h.hermes({**payload, "hook_event_name": "post_llm_call"}) is None


def test_claude_hook_always_registers_user_prompt_submit(target):  # noqa: F811
    e._hook_on(target, "http://h/mcp", "tok", None)
    s = json.loads((target.home / ".claude/settings.json").read_text())
    assert len(s["hooks"]["UserPromptSubmit"]) == 1


HOOKED = HERMES + '''
hooks:
  post_tool_call:
    - command: "/usr/local/bin/audit.sh"
  pre_llm_call:
    - command: "/usr/local/bin/other.sh"
      timeout: 3
hooks_auto_accept: false
'''


@pytest.mark.parametrize("text", [HERMES, HERMES + "hooks: {}\n", HOOKED])
def test_hermes_hook_set_and_remove(text):
    cmd = "python3 -I /usr/share/vi-mcp/hook/vi_hook.py --hermes"
    t = e.hermes_hook_set(text, cmd)
    d = yaml.safe_load(t)
    assert {"command": cmd, "timeout": 10} in d["hooks"]["pre_llm_call"]
    assert e.hermes_hook_set(t, cmd) == t  # idempotent: one entry
    if "other.sh" in text:
        assert d["hooks"]["pre_llm_call"][0]["command"] == "/usr/local/bin/other.sh" and d["hooks"]["post_tool_call"][0]["command"] == "/usr/local/bin/audit.sh"
        assert d["hooks_auto_accept"] is False
    back = yaml.safe_load(e.hermes_hook_remove(t))
    orig = yaml.safe_load(text)
    assert (back.get("hooks") or {}) == (orig.get("hooks") or {}) and {k: v for k, v in back.items() if k != "hooks"} == {k: v for k, v in orig.items() if k != "hooks"}
    assert "# Kopf" in t  # comments stay


def test_hermes_on_writes_hook_config(target):  # noqa: F811
    v = target.home / ".hermes"
    v.mkdir()
    (v / "config.yaml").write_text(HERMES)
    msg = e._hermes_on(target, "http://h/mcp", "tok")
    assert "consent" in msg
    c = json.loads((target.home / ".config/vi-mcp/hook-hermes.json").read_text())
    assert c["url"] == "http://h/mcp" and (target.home / ".config/vi-mcp/token-hermes").read_text() == "tok\n"
    d = yaml.safe_load((v / "config.yaml").read_text())
    assert d["hooks"]["pre_llm_call"][0]["command"].endswith("vi_hook.py --hermes") and d["mcp_servers"]["vi-mcp"]["url"] == "http://h/mcp"
    e._hermes_off(target)
    d = yaml.safe_load((v / "config.yaml").read_text())
    assert "hooks" not in d and not (target.home / ".config/vi-mcp/hook-hermes.json").exists()


def test_first_prompt_of_a_session_carries_the_skill_table_once(h):
    """0.53.0: which skills exist — once per session, with its first question; without overview objects nothing."""
    from vi_mcp import capabilities
    capabilities._cache.clear()  # cached per instance for 10 minutes; an earlier test of this module cached an empty table
    g.new_object("erkenntnis", "Vollständige Doku zu gitlab-api: vi_erinnere doku:gitlab-api. Verbindet sich mit GitLab.",
                 ["art-wissen:ueberblick", "doku:gitlab-api", "skill:gitlab"], {"quelle": "skills folder"}, instance="alice")
    ev = {"hook_event_name": "UserPromptSubmit", "session_id": "cc-skills", "cwd": "/tmp", "prompt": "wo liegt das Repo der Web-Komponente?"}
    ctx = h.process(ev)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("[Skills] 1 skill manuals") and "gitlab-api" in ctx
    again = h.process({**ev, "prompt": "und die Pipeline dazu?"})
    assert again is None or "[Skills]" not in again["hookSpecificOutput"]["additionalContext"]

"""0.56.0: problem → solution with content — what was done and looked up between an error and the success, including web sources."""
import itertools
import json

from vi_mcp import intuition, reflection, session, sleep_cycle, solutions
from vi_mcp import memory as g

_n = itertools.count()


def call(s, tool, args, ok, error=None, result=None):
    with session.on_behalf(s):
        v = intuition.before(tool, args, s.instance)
        return intuition.after(tool, args, ok, 1, error, result, v["vorher_id"], s.instance)


def web_episode(instance="a", fix="systemctl restart borg-agent --now"):
    s = session.begin(instance, "t")
    call(s, "Bash", {"command": "borg create ::x /data"}, False, "Error: Failed to create/acquire the lock /repo/lock.exclusive (timeout)")
    call(s, "WebSearch", {"query": "borg Failed to create/acquire the lock"}, True, result="borg break-lock removes stale locks …")
    call(s, "WebFetch", {"url": "https://borgbackup.readthedocs.io/en/stable/usage/break-lock.html", "prompt": "how to remove"}, True,
         result="borg break-lock REPOSITORY — break the repository and cache locks. Use with care: only if no borg process runs.")
    call(s, "Bash", {"command": "borg break-lock /repo"}, True)
    return call(s, "Bash", {"command": "borg create ::x /data"}, True)


def test_web_episode_becomes_a_solution_with_command_and_source(gd, monkeypatch):
    seen = {}

    def llm(system, user):
        seen["prompt"] = user
        return json.dumps({"problem": "borg create fails: repository lock held", "ursache": "a stale lock from an aborted run",
                           "loesung": "remove the stale lock with borg break-lock, then run borg create again",
                           "befehle": ["borg break-lock /repo", "borg create ::x /data"],
                           "quellen": ["https://borgbackup.readthedocs.io/en/stable/usage/break-lock.html"]})
    monkeypatch.setattr(reflection, "ask_fn", llm)
    web_episode()
    r = sleep_cycle.run("Test").data["schritte"]["4c_skills"]
    assert r["neu"] == 1 and r["mit_web"] == 1
    sk = [o for _, o, _g in g.recall("art:skill herkunft:web", viewer=None)][0]
    content = str(sk.data.get("inhalt") or sk.data["loesung"]["text"])
    assert "borg break-lock /repo" in content and "https://borgbackup.readthedocs.io" in content and "stale lock" in content
    assert sk.visibility == "intern" and sk.mode == "test" and "herkunft:episode" in sk.hashtags
    assert any(t.startswith("fehler:") for t in sk.hashtags) and sk.data["geschrieben_von"] == "sprachmodell"
    assert "break the repository and cache locks" in seen["prompt"]  # the web excerpt reached the write-up
    # the same error later: the solution is the first hint after it
    s = session.begin("b", "t")
    out = call(s, "Bash", {"command": "borg create ::y /data"}, False, "Error: Failed to create/acquire the lock /repo/lock.exclusive (timeout)")
    assert out["hinweise"] and sk.id in out["hinweise"][0]


def test_without_language_model_a_template_and_the_same_fix_evolves(gd, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", None)
    monkeypatch.setattr(reflection, "config", {})
    web_episode("a")
    assert sleep_cycle.run("Test").data["schritte"]["4c_skills"]["neu"] == 1
    web_episode("b")
    r = sleep_cycle.run("Test 2").data["schritte"]["4c_skills"]
    assert r["neu"] == 0 and r["weiterentwickelt"] == 1
    sk = [o for _, o, _g in g.recall("art:skill herkunft:web", viewer=None)][0]
    assert sk.data["geschrieben_von"] == "vorlage" and "borg break-lock /repo" in str(sk.data.get("inhalt") or sk.data["loesung"]["text"])


def test_the_same_call_repeated_is_counted_not_stored(gd):
    s = session.begin("a", "t")
    call(s, "Bash", {"command": "make test"}, False, "Error: flaky network")
    call(s, "Bash", {"command": "make test"}, True)
    r = sleep_cycle.run("Test").data["schritte"]["4c_skills"]
    assert r["episoden"] == 1 and r["ohne_inhalt"] == 1 and r["neu"] == 0


def test_hidden_characters_from_the_web_reject_the_solution(gd, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"problem": "x fails", "ursache": "y", "loesung": "run z​ now", "befehle": ["z"], "quellen": []}))
    web_episode()
    r = sleep_cycle.run("Test").data["schritte"]["4c_skills"]
    assert r["abgelehnt"] == 1 and "invisible" in r["fehler"][0]


def test_evidence_and_name_are_pure_functions_of_the_episode():
    ev = {"tool": "Bash", "signatur": "fehler:x", "fehlgeschlagen": {"args": {"command": "a"}, "fehler": "boom"}, "web": [],
          "massnahmen": [{"tool": "Edit", "args": {"file_path": "/etc/x.conf"}}], "loesung": {"args": {"command": "a"}}, "dokumente": [],
          "schritte": ["Bash", "Edit", "Bash"], "kontext": [], "belege": [], "gespraech": "1"}
    assert solutions.has_content(ev) and solutions.name_for(ev) == solutions.name_for(dict(ev))
    assert not solutions.has_content({**ev, "massnahmen": []})

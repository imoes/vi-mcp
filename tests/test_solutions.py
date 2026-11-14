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


def test_shell_solution_gets_the_program_as_trigger_and_generic_ones_are_counted(gd, monkeypatch):
    # 0.58.1: on production 4 of 6 solutions had no specific trigger and appeared before every Bash command
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"problem": "sqlite3 CLI missing", "ursache": "not installed", "loesung": "use python3 -c 'import sqlite3'", "befehle": ["python3 -c ..."],
         "quellen": [], "allgemein": True}))
    s = session.begin("a", "t")
    call(s, "Bash", {"command": "sqlite3 /tmp/x.db '.tables'"}, False, "Exit code 127")
    call(s, "Bash", {"command": "python3 -c 'import sqlite3'"}, True)
    s2 = session.begin("b", "t")
    call(s2, "Bash", {"command": "cd /tmp && ls -la"}, False, "Exit code 2")
    call(s2, "Bash", {"command": "cd /var/tmp && ls"}, True)
    r = sleep_cycle.run("Test").data["schritte"]["4c_skills"]
    assert r["neu"] == 1 and r["unspezifisch"] == 1
    sk = [o for _, o, _g in g.recall("art:skill herkunft:episode", viewer=None)][0]
    assert "thema:sqlite3" in sk.hashtags


def test_language_model_may_hold_back_a_one_off(gd, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"problem": "typo in a file name", "ursache": "typo", "loesung": "fixed the typo", "befehle": [], "quellen": [], "allgemein": False}))
    web_episode()
    r = sleep_cycle.run("Test").data["schritte"]["4c_skills"]
    assert r["nicht_allgemein"] == 1 and r["neu"] == 0


def test_an_unrelated_next_shell_command_is_no_solution():
    """0.62.1, found on production: after a failed `git … rev-parse --short HEAD origin/main` the next successful call was an unrelated
    grep/ls, and a wrong cause was written up as a solution. A shell fix must share a program with the failed call."""
    from vi_mcp import solutions
    ev = lambda failed, fixed: {"tool": "Bash", "fehlgeschlagen": {"args": {"command": failed}}, "loesung": {"args": {"command": fixed}}}  # noqa: E731
    assert not solutions.related(ev("git push origin main && git rev-parse --short HEAD origin/main", "grep -rln x tests/ | head; ls tests"))
    assert solutions.related(ev("git rev-parse --short HEAD origin/main", "git rev-parse --short HEAD"))
    assert solutions.related(ev("sudo -n systemctl restart vi-mcp", "systemctl --user restart vi-mcp"))
    assert solutions.related(ev("sqlite3 /tmp/x.db '.tables'", "python3 -c 'import sqlite3'"))  # a replacement names the program
    assert not solutions.related(ev("cd /x && make build", "cd /x && echo done"))  # cd/echo alone relate nothing
    assert solutions.related({"tool": "WebFetch", "fehlgeschlagen": {"args": {"url": "a"}}, "loesung": {"args": {"url": "b"}}})


def test_an_unproven_cause_is_a_hypothesis_and_the_lesson_leads(gd, monkeypatch):
    """0.63.0: auto solutions from episodes had 9 % success after showing (n=29 ratings, production 13.11.2026); experience-following
    copies errors (arXiv 2505.16067), distilled strategies transfer better than raw trajectories (ReasoningBank, arXiv 2509.25140).
    A cause the evidence does not show is marked as the language model's hypothesis, and the transferable lesson comes right after the
    problem, inside the key statement that hints show."""
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"problem": "borg create fails: repository lock held", "ursache": "a cron job ran twice", "ursache_belegt": False,
         "loesung": "borg break-lock, then borg create again", "befehle": ["borg break-lock /repo"], "quellen": [],
         "lehre": "when borg reports a held lock and no borg process runs: break the lock; never break it while a backup runs"}))
    web_episode()
    assert sleep_cycle.run("Test").data["schritte"]["4c_skills"]["neu"] == 1
    sk = [o for _, o, _g in g.recall("art:skill herkunft:episode", viewer=None)][0]
    content = str(sk.data.get("inhalt") or sk.data["loesung"]["text"])
    assert "Cause: not determined from the evidence — hypothesis of the language model: a cron job ran twice" in content
    assert content.index("Lesson:") < content.index("Cause:") and "Lesson: when borg reports a held lock" in sk.text


def test_a_proven_cause_stays_as_written(gd, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"problem": "borg create fails", "ursache": "a stale lock from an aborted run", "ursache_belegt": True,
         "loesung": "borg break-lock", "befehle": [], "quellen": [], "lehre": "break stale locks only when no borg runs"}))
    web_episode()
    sleep_cycle.run("Test")
    sk = [o for _, o, _g in g.recall("art:skill herkunft:episode", viewer=None)][0]
    assert "Cause: a stale lock from an aborted run" in str(sk.data.get("inhalt") or sk.data["loesung"]["text"])

"""0.24.0: no repeated hints within a conversation; project from the working directory; statistics with honest time windows."""
import time

from vi_mcp import intuition, server, session, usage_stats
from vi_mcp import memory as g


def _before(s, tool="Bash"):
    with session.on_behalf(s):
        return intuition.before(tool, {"command": "ls"}, s.instance, False)


def test_hint_is_not_repeated_within_the_conversation(gd):
    k = g.new_object("erkenntnis", "ssh to the build host only with the key file", ["tool:Bash"], {"quelle": "x"}, instance="b")
    s = session.begin("a", "t")
    first = _before(s)
    assert k.id in first["zugriff"]["gezeigt"]
    second = _before(s)
    assert k.id not in second["zugriff"]["gezeigt"] and second["zugriff"]["repeat_suppressed"] == [k.id]
    assert any("1 already shown in this conversation within the last hour, not repeated" in h for h in second["hinweise"])  # named, not silent
    other = session.begin("a", "t")  # another conversation sees it again
    assert k.id in _before(other)["zugriff"]["gezeigt"]
    s.shown[k.id] = time.monotonic() - intuition.REPEAT_S - 1  # after an hour it may come again
    assert k.id in _before(s)["zugriff"]["gezeigt"]


def test_project_is_the_last_part_of_the_working_directory(gd):
    assert server.project_name("/home/anna/Dev/cue-print/") == "cue-print"
    assert server.project_name("C:\\Users\\anna\\my project") == "my_project"
    assert server.project_name(None) is None and server.project_name("/") is None
    s = session.begin("a", "claude-code-hook 1", "cue-print")
    assert g.load(f"gespraech:{s.serial}").data["project"] == "cue-print"


def test_stats_count_rules_only_while_calls_are_recorded_and_show_projects(gd):
    s = session.begin("a", "claude-code-hook 1", "cue-print")
    with session.on_behalf(s):
        v = intuition.before("Write", {"file_path": "/tmp/x"}, "a", False)
        intuition.after("Write", {"file_path": "/tmp/x"}, True, 1, None, None, v["vorher_id"], "a", False)
    d = usage_stats.data(1)
    assert d["nutzung"]["aufrufe_seit"] is None and d["regeln"]["aendernd"] == 0  # no calls recorded yet: no rule rate
    assert d["nutzung"]["je_projekt"]["cue-print"]["n"] == 1
    usage_stats.record("a", "t", "vi_recall", "ok", 3, "1 object for “x”")
    d = usage_stats.data(1)
    assert d["nutzung"]["aufrufe_seit"] is not None and d["regeln"]["aendernd"] == 0  # the action happened before calls were recorded
    report = usage_stats.report(1)
    assert "recorded since" in report and "cue-print 1 (100 % ok)" in report

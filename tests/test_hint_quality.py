"""0.49.0: fewer, better hints and better feedback — measured on production (7 days to 11.11.2026): three hints were shown before nearly
every shell command, feedback came for 2 of 10,673 hints, and the raw lift (−20 points) mixed instances with different base rates."""
import time

from vi_mcp import intuition, metrics, session, tools, usage_stats
from vi_mcp import memory as g


def _k(text, tags, **kw):
    return g.new_object("erkenntnis", text, tags, {"quelle": "test 11.11.2026"}, instance="b", **kw)


def test_tool_only_and_generic_word_hints_stay_away_from_shell_commands(gd):
    noise = _k("ssh to the build host only with the key file", ["tool:Bash", "skill:Bash"])
    grep_noise = _k("A commit chain with pytest | tail commits on red tests", ["tool:Bash", "thema:grep"])
    specific = _k("web1 answers ssh only with BatchMode and the key file", ["host:web1.example", "tool:Bash"])
    v = intuition.before("Bash", {"command": "grep -n foo vi_mcp/web.py"}, "a", False)
    shown = v["zugriff"]["gezeigt"]
    assert noise.id not in shown and grep_noise.id not in shown
    assert any("share only the tool or generic words, not shown" in h for h in v["hinweise"])  # counted, not silent
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "a", False)
    assert specific.id in v["zugriff"]["gezeigt"]


def test_mcp_tools_keep_their_tool_hints(gd):
    k = _k("netbox_get_devices pages at 50 results", ["tool:netbox_get_devices"])
    assert k.id in intuition.before("netbox_get_devices", {"name": "x"}, "a", False)["zugriff"]["gezeigt"]


def test_a_hint_at_most_daily_max_times_a_day_per_instance(gd, monkeypatch):
    monkeypatch.setattr(intuition, "_daily", {})
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "thema:uptime"])
    seen = 0
    for i in range(intuition.DAILY_MAX + 2):
        s = session.begin("a", f"t{i}")  # a new conversation every time: the per-conversation guard does not apply
        with session.on_behalf(s):
            v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        seen += k.id in v["zugriff"]["gezeigt"]
    assert seen == intuition.DAILY_MAX and any(f"shown {intuition.DAILY_MAX}× today already" in h for h in v["hinweise"])
    assert k.id in intuition.before("Bash", {"command": "uptime"}, "other-instance", False)["zugriff"]["gezeigt"]  # per instance


def test_feedback_in_one_call_and_the_nudge(gd):
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "thema:uptime"])
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        intuition.after("Bash", {"command": "uptime"}, True, 5, None, None, v["vorher_id"], "a", False)
    assert any("vi_feedback(helped=[ids], wrong=[ids])" in h for h in v["hinweise"])
    out = tools.call_tool("vi_feedback", {"helped": [k.id], "wrong": ["erkenntnis:nie-gezeigt"]}, "a", False)
    assert "feedback recorded for 1 hint(s)" in out and "erkenntnis:nie-gezeigt" in out
    d = usage_stats.data(1)
    assert d["regeln"]["rueckmeldungen"] == 1
    e = [o for _s, o, _g in g.recall("art:erfahrung", viewer=None)][0]
    assert e.data["rueckmeldung"] == {k.id: 1}


def test_opening_a_shown_hint_counts_as_use(gd):
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "thema:uptime"])
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        intuition.after("Bash", {"command": "uptime"}, True, 5, None, None, v["vorher_id"], "a", False)
        tools.call_tool("vi_object", {"id": k.id}, "a", False)
    assert usage_stats.data(1)["regeln"]["geoeffnet"] == 1
    assert "opened with vi_object after being shown 1" in usage_stats.report(1)


def _exp(instance, tool, ok, hint):
    return g.new_object("erfahrung", f"{tool} run", [f"tool:{tool}", f"ok:{'ja' if ok else 'nein'}"],
                        {"vorher": {"gefunden": ["erkenntnis:x"] if hint else [], "gezeigt": []}}, instance=instance)


def test_matched_lift_resolves_simpsons_paradox(gd):
    # high base rate instance: −1 point; low base rate instance (nearly always with a hint): +9 points
    for ok, n in ((True, 97), (False, 3)):
        for _ in range(n):
            _exp("claude", "Bash", ok, True)
    for ok, n in ((True, 98), (False, 2)):
        for _ in range(n):
            _exp("claude", "Bash", ok, False)
    for ok, n in ((True, 43), (False, 57)):
        for _ in range(n):
            _exp("cs", "analyse", ok, True)
    for ok, n in ((True, 17), (False, 33)):
        for _ in range(n):
            _exp("cs", "analyse", ok, False)
    raw = metrics.hint_lift(24)
    m = metrics.hint_lift_matched(24)
    assert raw["lift"] < 0  # the mixed comparison looks harmful (−6.7 points)
    assert m["lift"] > 0 and m["schichten"] == 2 and m["mit_vergleichbar"] == 200
    assert "matched within instance and tool" in metrics.matched_line(m)


def test_measured_useful_hints_and_warnings_are_not_capped(gd):
    useful = _k("uptime on the build host lies after a suspend", ["tool:Bash", "thema:uptime"])
    useful.data["nuetzlich"] = {"ja": 2.0, "nein": 0.5, "n": 4}  # the bandit measured an advantage
    g.save(useful)
    warning = _k("never run uptime -s on the frozen host", ["tool:Bash", "thema:uptime"], importance=3)
    for i in range(intuition.DAILY_MAX + 3):
        s = session.begin("a", f"t{i}")
        with session.on_behalf(s):
            shown = intuition.before("Bash", {"command": "uptime"}, "a", False)["zugriff"]["gezeigt"]
        assert useful.id in shown and warning.id in shown

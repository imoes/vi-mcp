"""0.49.0: fewer, better hints and better feedback — measured on production (7 days to 11.11.2026): three hints were shown before nearly
every shell command, feedback came for 2 of 10,673 hints, and the raw lift (−20 points) mixed instances with different base rates."""
import json
import time

from vi_mcp import intuition, learning, metrics, session, tools, usage_stats
from vi_mcp import memory as g


def _k(text, tags, **kw):
    return g.new_object("insight", text, tags, {"source": "test 11.11.2026"}, instance="b", **kw)


def test_tool_only_and_generic_word_hints_stay_away_from_shell_commands(gd):
    noise = _k("ssh to the build host only with the key file", ["tool:Bash", "skill:Bash"])
    grep_noise = _k("A commit chain with pytest | tail commits on red tests", ["tool:Bash", "topic:grep"])
    specific = _k("web1 answers ssh only with BatchMode and the key file", ["host:web1.example", "tool:Bash"])
    v = intuition.before("Bash", {"command": "grep -n foo vi_mcp/web.py"}, "a", False)
    shown = v["zugriff"]["shown"]
    assert noise.id not in shown and grep_noise.id not in shown
    assert any("share only the tool or generic words, not shown" in h for h in v["hinweise"])  # counted, not silent
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "a", False)
    assert specific.id in v["zugriff"]["shown"]


def test_mcp_tools_keep_their_tool_hints(gd):
    k = _k("netbox_get_devices pages at 50 results", ["tool:netbox_get_devices"])
    assert k.id in intuition.before("netbox_get_devices", {"name": "x"}, "a", False)["zugriff"]["shown"]


def test_a_hint_at_most_daily_max_times_a_day_per_instance(gd, monkeypatch):
    monkeypatch.setattr(intuition, "_daily", {})
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    seen = 0
    for i in range(intuition.DAILY_MAX + 2):
        s = session.begin("a", f"t{i}")  # a new conversation every time: the per-conversation guard does not apply
        with session.on_behalf(s):
            v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        seen += k.id in v["zugriff"]["shown"]
    assert seen == intuition.DAILY_MAX and any(f"shown {intuition.DAILY_MAX}× today already" in h for h in v["hinweise"])
    assert k.id in intuition.before("Bash", {"command": "uptime"}, "other-instance", False)["zugriff"]["shown"]  # per instance


def test_feedback_in_one_call_and_the_nudge(gd, monkeypatch):
    monkeypatch.setattr(intuition, "NUDGE_OFF", 0.0)  # 0.68.0: the request is A/B-tested per conversation; here always asked
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        intuition.after("Bash", {"command": "uptime"}, True, 5, None, None, v["vorher_id"], "a", False)
    assert any(f'vi_feedback(before_id="{v["vorher_id"]}", used=[' in h for h in v["hinweise"])  # Z7: the request names this action
    # the unbound call (helped/wrong without before_id) stays valid for older clients:
    out = tools.call_tool("vi_feedback", {"helped": [k.id], "wrong": ["erkenntnis:nie-gezeigt"]}, "a", False)
    assert "feedback recorded for 1 hint(s)" in out and "erkenntnis:nie-gezeigt" in out
    d = usage_stats.data(1)
    assert d["regeln"]["rueckmeldungen"] == 1
    e = [o for _s, o, _g in g.recall("kind:experience", viewer=None)][0]
    assert e.data["feedback"] == {k.id: 1}
    # 0.70.2 (d6cf286): the router report counts the same booked feedback (it searched the pre-0.67 key and reported 0)
    assert sum(len(json.loads(r[0]).get("feedback") or {}) for r in learning._feedbacks()) == 1


def test_opening_a_shown_hint_counts_as_use(gd):
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        intuition.after("Bash", {"command": "uptime"}, True, 5, None, None, v["vorher_id"], "a", False)
        tools.call_tool("vi_object", {"id": k.id}, "a", False)
    assert usage_stats.data(1)["regeln"]["geoeffnet"] == 1
    assert "opened with vi_object after being shown 1" in usage_stats.report(1)


def _exp(instance, tool, ok, hint):
    return g.new_object("experience", f"{tool} run", [f"tool:{tool}", f"ok:{'ja' if ok else 'nein'}"],
                        {"before": {"found": ["erkenntnis:x"] if hint else [], "shown": []}}, instance=instance)


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
    useful = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    useful.data["useful"] = {"yes": 2.0, "no": 0.5, "n": 4}  # the bandit measured an advantage
    g.save(useful)
    warning = _k("never run uptime -s on the frozen host", ["tool:Bash", "topic:uptime"], importance=3)
    for i in range(intuition.DAILY_MAX + 3):
        s = session.begin("a", f"t{i}")
        with session.on_behalf(s):
            shown = intuition.before("Bash", {"command": "uptime"}, "a", False)["zugriff"]["shown"]
        assert useful.id in shown and warning.id in shown


def test_feedback_with_before_id_books_exactly_that_action(gd):
    """0.50.1: two agents of one instance run in parallel with the same hint (CentralStation fleet, 11.11.2026). Without before_id the
    feedback lands on the most recent action — possibly the neighbour's; with before_id exactly on its own."""
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    ids = []
    for t in ("agent-1", "agent-2"):
        s = session.begin("cs", t)
        with session.on_behalf(s):
            v = intuition.before("Bash", {"command": "uptime"}, "cs", False)
        ids.append((v["vorher_id"], intuition.after("Bash", {"command": "uptime"}, True, 5, None, None, v["vorher_id"], "cs", False)["erfahrung"]))
    (first_before, first_exp), (_second_before, second_exp) = ids
    assert g.load(first_exp).data["before"]["id"] == first_before
    out = tools.call_tool("vi_feedback", {"helped": [k.id], "before_id": first_before}, "cs", False)
    assert "recorded for 1 hint" in out
    assert g.load(first_exp).data["feedback"] == {k.id: 1} and "feedback" not in g.load(second_exp).data
    out = tools.call_tool("vi_feedback", {"wrong": [k.id], "before_id": "vorher:gibt-es-nicht"}, "cs", False)
    assert "not shown before the action vorher:gibt-es-nicht" in out  # no fallback to the most recent action
    tools.call_tool("vi_feedback", {"wrong": [k.id]}, "cs", False)  # without before_id: the most recent action, as before
    assert g.load(second_exp).data["feedback"] == {k.id: -1}


def test_propensities_of_the_offer():
    # 0.57.0: given the ranking, the first places are certain, the last regular place 1 − ε, each candidate further back ε / n
    from vi_mcp import intuition
    p = intuition.propensities(["a", "b", "c", "d"], ["e", "f"], 0.1)
    assert p == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 0.9, "e": 0.05, "f": 0.05}
    assert intuition.propensities(["a", "b"], [], 0.1) == {"a": 1.0, "b": 1.0}
    assert intuition.propensities(["a"], ["e"], 0.1, full=False) == {"a": 1.0, "e": 0.1}  # a free slot: nothing is displaced


def test_exploration_effect_and_ips_lift_from_logged_offers(gd):
    # actions where the ranked hint "d" was shown succeed, explorations that showed "e" instead fail
    from vi_mcp import metrics
    offer = {"a": 1.0, "d": 0.9, "e": 0.1}
    for i in range(60):
        expl = i % 2 == 0
        shown = ["a", "e"] if expl else ["a", "d"]
        ok = not expl
        g.new_object("experience", f"Bash {i}", ["tool:Bash", f"ok:{'ja' if ok else 'nein'}"],
                     {"before": {"shown": shown, "rest_n": 1, "exploration": expl, "router": "modell", "offer": offer}}, instance="a")
    metrics._GRADES["db"] = None
    ex = metrics.exploration_effect(24)
    assert ex["zustand"] == "gemessen" and ex["differenz"] == -1.0 and "ranked hint beats a random candidate" in ex["urteil"]
    lift = metrics.ips_lift(24)
    assert lift["d"]["lift"] == 1.0 and lift["e"]["lift"] == -1.0 and "a" not in lift  # "a" was always shown: no counterfactual


def test_a_small_matched_difference_is_no_verdict_without_two_standard_errors(gd):
    """0.62.1, found on production: one day, 4 strata, −7 points was reported as "hints hurt"; with a standard error it was noise."""
    for ok, n in ((True, 13), (False, 7)):  # 65 % with hints
        for _ in range(n):
            _exp("claude", "Bash", ok, True)
    for ok, n in ((True, 72), (False, 28)):  # 72 % without
        for _ in range(n):
            _exp("claude", "Bash", ok, False)
    m = metrics.hint_lift_matched(24)
    assert -0.08 < m["lift"] < -0.06 and m["standardfehler"] > 0.05
    assert m["urteil"] == "no difference beyond 2 standard errors"
    assert "±" in metrics.matched_line(m)


def test_warned_actions_are_not_counted_as_hints(gd):
    """0.62.2: a warning is its own intervention (before risky actions, own line); mixed into the hint lift it made hints look harmful."""
    for ok, n in ((True, 50), (False, 50)):  # warned and failing often — must not count
        for _ in range(n):
            o = _exp("cs", "analyse", ok, True)
            o.data["before"]["warning"] = True
            g.save(o)
    for ok, n in ((True, 19), (False, 1)):
        for _ in range(n):
            _exp("cs", "analyse", ok, True)
    for ok, n in ((True, 19), (False, 1)):
        for _ in range(n):
            _exp("cs", "analyse", ok, False)
    m = metrics.hint_lift_matched(24)
    assert m["ohne_warnungen"] == 100 and m["mit_vergleichbar"] == 20 and abs(m["lift"]) < 1e-9
    assert "100 actions with a warning left out" in metrics.matched_line(m)


def test_a_clear_but_small_difference_names_the_minimum_effect_not_the_standard_error(gd):
    """Production 14.11.2026: "+3.6 ± 1.5 points … no difference beyond 2 standard errors" — 3.6 IS beyond 2 × 1.5; the 5-point
    minimum effect held the verdict back, and the line must name that reason."""
    for ok, n in ((True, 970), (False, 30)):   # 97 % with hints
        for _ in range(n):
            _exp("claude", "Bash", ok, True)
    for ok, n in ((True, 935), (False, 65)):   # 93.5 % without
        for _ in range(n):
            _exp("claude", "Bash", ok, False)
    m = metrics.hint_lift_matched(24)
    assert 0.03 < m["lift"] < 0.05 and m["lift"] > 2 * m["standardfehler"]
    assert m["urteil"] == "beyond 2 standard errors but below the 5-point minimum effect — no verdict"


def test_opening_a_hint_the_hook_showed_in_another_session_counts(gd):
    """Production 14.11.2026: 'opened with vi_object after being shown 0' over 7 days with 1503 vi_object calls. The hook shows hints
    in its own MCP session (client claude-code-hook); the agent opens them over its own connection — the same-session check in
    vi_object never matched. intuition.opened already links by instance and recent experience, across sessions."""
    k = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    hook = session.begin("a", "claude-code-hook")
    with session.on_behalf(hook):
        v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        intuition.after("Bash", {"command": "uptime"}, True, 5, None, None, v["vorher_id"], "a", False)
    agent = session.begin("a", "claude-code")
    with session.on_behalf(agent):
        tools.call_tool("vi_object", {"id": k.id}, "a", False)
    assert usage_stats.data(1)["regeln"]["geoeffnet"] == 1
    other = session.begin("b", "claude-code")       # another instance opening the same object is not "use of a shown hint"
    with session.on_behalf(other):
        tools.call_tool("vi_object", {"id": k.id}, "b", False)
    assert usage_stats.data(1)["regeln"]["geoeffnet"] == 1


def test_archive_hints_need_specific_triggers_and_feedback_on_them_is_booked(gd):
    """0.69.5 (production 17.11.2026): an archived Confluence page tagged topic:grep was offered before nearly every grep, and the
    user's vi_feedback(wrong=[it]) was not booked — archive hints were never recorded as shown."""
    from vi_mcp import archive
    noise = _k("Exchange incident 2021: commands used on the mail server", ["topic:grep", "topic:exchange"])
    fit = _k("web1 rotates its logs at 03:00 with logrotate", ["host:web1.example", "topic:logrotate"])
    for o in (noise, fit):
        archive.store_in_archive(g.load(o.id), "test: unused")
    v = intuition.before("Bash", {"command": "grep -n foo vi_mcp/web.py"}, "a", False)
    assert not any("long-term archive" in h for h in v["hinweise"]) and "archive_shown" not in v["zugriff"]
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "ssh web1.example grep -c rotate /var/log/syslog"}, "a", False)
        intuition.after("Bash", {"command": "ssh web1.example"}, True, 5, None, None, v["vorher_id"], "a", False)
    assert any(fit.id in h and "long-term archive" in h for h in v["hinweise"]) and v["zugriff"]["archive_shown"] == [fit.id]
    out = tools.call_tool("vi_feedback", {"wrong": [fit.id]}, "a", False)
    assert "feedback recorded for 1 hint(s)" in out
    assert g.load(fit.id).data["archive_feedback"] == {"wrong": ["a"]}
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "a", False)
    assert not any(fit.id in h for h in v["hinweise"])  # reported wrong: not offered to this instance again
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "b", False)
    assert any(fit.id in h for h in v["hinweise"])  # another instance still sees it

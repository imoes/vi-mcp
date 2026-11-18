"""0.5.0: learning — observations, exploration, router model (sklearn optional), prediction without sklearn."""
import builtins
import json
import random
import time

import pytest

from vi_mcp import intuition, learning, sleep_cycle, tools
from vi_mcp import memory as g

try:
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

_n = iter(range(100_000))


def action(tool, host, ok, context=None, instance="a"):
    args = {"host": host, "n": next(_n)}
    v = intuition.before(tool, args, instance, context=context)
    intuition.after(tool, args, ok, 1, None if ok else "Fehler: x", "ok" if ok else None, v["vorher_id"], instance)
    return v


def test_observation_view_and_features(gd):
    g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x"}, reason="T")
    action("checkmk_get_host", "web1", True, context=["topic:oom"])
    action("checkmk_get_host", "web2", False)
    with g.lock:
        rows = g.db().execute("SELECT tool, ok, hint_n, surprise, router FROM observation ORDER BY ts").fetchall()
    assert rows[0][:3] == ("checkmk_get_host", 1, 1) and rows[1][:3] == ("checkmk_get_host", 0, 0) and rows[0][4] == "heuristik"
    b = learning.observations()
    assert len(b) == 2  # one pair (with hint) + one baseline (without)
    with_hint = next(m for m, y, _ in b if y == 1)
    assert "topic:oom" in with_hint and "hint_kind:insight" in with_hint and "hint_n:1" in with_hint and any(k.startswith("hint:insight:") for k in with_hint)
    without = next(m for m, y, _ in b if y == 0)
    assert "hint_n:0" in without and not any(k.startswith("hint:") for k in without)
    assert "topic:oom" in g.recall("tool:checkmk_get_host ok:yes", viewer=None)[0][1].hashtags  # context stimulus is a tag


def test_exploration_is_tagged(gd, monkeypatch):
    for i in range(8):
        g.new_object("insight", f"Hinweis {i} zu web3", ["host:web3"], {"source": "x"}, reason="T")
    monkeypatch.setattr(learning, "EPSILON", 1.0)
    v = intuition.before("Bash", {"host": "web3"}, "a", False)
    assert v["zugriff"]["exploration"] is True and len(v["zugriff"]["shown"]) == intuition.HINT_BUDGET
    assert any("(exploration: a random pick" in h for h in v["hinweise"]) and len(v["zugriff"]["candidates"]) == 8
    assert v["zugriff"]["shown"][-1] not in v["zugriff"]["candidates"][:intuition.HINT_BUDGET]
    monkeypatch.setattr(learning, "EPSILON", 0.0)
    v = intuition.before("Bash", {"host": "web3"}, "a", False)
    assert v["zugriff"]["exploration"] is False and v["zugriff"]["router"] == "heuristik"


def test_prediction_without_sklearn_and_ranking(gd):
    m = g.new_object("model", "Testmodell", ["modell:router"],
                       {"state": "aktiv", "gewichte": {"hint:regel:gut": 2.0, "hint:erkenntnis:schlecht": -2.0, "skill:x": 0.5}, "achsenabschnitt": 0.0},
                       oid=learning.model_id(None), reason="T", instance=g.SERVER_INSTANCE)
    p = learning.prediction(m, {"skill:x": 1.0, "hint:regel:gut": 1.0})
    assert abs(p - 1 / (1 + 2.718281828 ** -2.5)) < 1e-6
    r = learning.ranking(m, ["skill:x"], ["erkenntnis:schlecht", "erkenntnis:neutral", "regel:gut"])
    assert [h for h, _ in r] == ["regel:gut", "erkenntnis:neutral", "erkenntnis:schlecht"] and r[0][1] > 0 > r[2][1]


def test_too_little_data_and_missing_sklearn(gd, monkeypatch):
    action("t_a", "h", True)
    b = learning.train("Test")
    if HAS_SKLEARN:
        assert b["zustand"] == "zu_wenig_daten" and g.load(learning.model_id(None)).mode == "test" and learning.active() is None
        assert "zu_wenig_daten" in tools.call_tool("vi_modell", {}, "a", True)
    else:
        assert b["zustand"] == "uebersprungen" and "python3-sklearn" in b["grund"]
    real = builtins.__import__

    def without(name, *a, **k):
        if name.startswith("sklearn"):
            raise ImportError(name="sklearn")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", without)
    b = learning.train("Test")
    assert b["zustand"] == "uebersprungen" and "sklearn" in b["grund"]


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn nicht installiert (.venv nutzen)")
def test_router_learns_which_hint_helps(gd):
    """Synthetic: hint R (rule) → ok 90 %; hint E (insight) → ok 20 %. Every action is shown exactly one
    of the two (as with budget 1 / exploration). After training: weight(R) > 0 > weight(E), R first."""
    random.seed(7)
    r = g.new_object("rule", "vor graylog_search Zeitraum setzen", ["skill:graylog"], {"source": "x"}, reason="T")
    e = g.new_object("insight", "graylog ist immer schnell", ["skill:graylog"], {"source": "x"}, reason="T")
    for i in range(800):
        args = {"q": i}
        v = intuition.before("graylog_search", args, "a")
        intuition.after("graylog_search", args, True, 1, None, "ok", v["vorher_id"], "a")
    with g.lock:  # set "shown" to exactly one hint and then roll the label
        rows = g.db().execute("SELECT id, data FROM object WHERE kind = 'experience'").fetchall()
        for i, (oid, data) in enumerate(rows):
            d = json.loads(data)
            only = [r.id] if i % 2 == 0 else [e.id]
            ok_new = random.random() < (0.9 if only == [r.id] else 0.2)
            d["before"]["shown"] = only
            g.db().execute("UPDATE object SET data = ? WHERE id = ?", (json.dumps(d), oid))
            g.db().execute("DELETE FROM tag WHERE object_id = ? AND tag IN ('ok:yes', 'ok:no')", (oid,))
            g.db().execute("INSERT INTO tag VALUES (?, ?)", (oid, "ok:yes" if ok_new else "ok:no"))
        g.db().commit()
    b = learning.train("Test")
    assert b["zustand"] == "aktiv", b
    assert b["nutzen_holdout"]["zustand"] == "nutzen" and b["nutzen_holdout"]["abstand"] > 0.3, b["nutzen_holdout"]  # 0.30.0
    m = learning.active()
    assert m and m.data["gewichte"][f"hint:{r.id}"] > 0 > m.data["gewichte"][f"hint:{e.id}"]
    rf = learning.ranking(m, ["tool:graylog_search", "skill:graylog"], [e.id, r.id])
    assert rf[0][0] == r.id and rf[0][1] > 0.3
    v = intuition.before("graylog_search", {"q": "neu"}, "a")
    assert v["zugriff"]["router"] == "modell" and v["zugriff"]["shown"][0] == r.id
    assert "Router model (aktiv)" in tools.call_tool("vi_modell", {}, "a", True)
    why = tools.call_tool("vi_why", {"id": r.id}, "a", False)  # 0.29.0: the decision just made (open, no vi_after yet), laid open
    assert "open action, not reported yet" in why and "router modell" in why and f"hint:{r.id}" in why and "difference +" in why and "not success probabilities" in why
    assert sleep_cycle.run("Test").data["schritte"]["8_lernen"]["zustand"] == "aktiv"


def test_bandit_counters_and_ranking(gd):
    from vi_mcp import bandit
    good = g.new_object("rule", "Zeitraum setzen hilft", ["skill:graylog"], {"source": "x"}, reason="T")
    bad = g.new_object("insight", "graylog ist immer schnell", ["skill:graylog"], {"source": "x"}, reason="T")
    v = intuition.before("graylog_search", {"q": 0}, "a")
    assert v["zugriff"]["router"] == "heuristik" and set(v["zugriff"]["shown"]) == {good.id, bad.id}
    # counters: 20× ok after showing "good", 20× not ok after "bad" (booked directly, as after does)
    bandit._reason.update(zeit=time.time(), je={"graylog_search": 0.5}, alle=0.5)  # the tool's base rate: half and half
    assert bandit.book_entry([good.id], True, "graylog_search") == 1 and bandit.book_entry(["antwort:x"], True) == 0 and bandit.book_entry([good.id], None) == 0
    for _ in range(19):
        bandit.book_entry([good.id], True, "graylog_search")
    for _ in range(20):
        bandit.book_entry([bad.id], False, "graylog_search")
    assert bandit.counter(g.load(good.id)) == (10, 0) and bandit.counter(g.load(bad.id)) == (0, 10) and bandit.shown(g.load(good.id)) == 20
    assert "20× shown, success afterwards 100 % instead of expected 50 % (+50 points)" in tools.call_tool("vi_objekt", {"id": good.id}, "a", True)
    rnd = random.Random(1)
    fresh = [g.load(bad.id), g.load(good.id)]  # counters live in the DB; before() always loads candidates fresh
    in_front = sum(1 for _ in range(100) if bandit.arrange(fresh, rnd)[0].id == good.id)
    assert in_front >= 95  # Beta(11,1) versus Beta(1,11)
    v = intuition.before("graylog_search", {"q": 1}, "a")
    assert v["zugriff"]["router"] == "bandit"
    n = intuition.after("graylog_search", {"q": 1}, False, 1, "Fehler", None, v["vorher_id"], "a")
    assert n["bewertet"] == len(v["zugriff"]["shown"])
    assert bandit.counter(g.load(good.id))[1] == 0.5 and bandit.shown(g.load(good.id)) == 21  # "no" booked after a real action, weighted with the base rate


def test_ineffective_hint_stays_at_half(gd):
    """A hint shown before a tool that almost always succeeds gets no credit; a helpful one does."""
    from vi_mcp import bandit
    empty = g.new_object("rule", "Bash scheiterte und gelang danach", ["tool:Bash"], {"source": "x"}, reason="T")
    rng = random.Random(4)
    for i in range(400):  # Bash without hint: 94 %
        g.new_object("experience", "Bash", ["tool:Bash", "ok:yes" if rng.random() < 0.94 else "ok:no"], {"before": {"shown": []}, "args": {"i": i}}, reason="T")
    for i in range(300):  # with the empty hint: also 94 %
        g.new_object("experience", "Bash", ["tool:Bash", "ok:yes" if rng.random() < 0.94 else "ok:no"], {"before": {"shown": [empty.id]}, "args": {"j": i}}, reason="T")
    helps = g.new_object("rule", "Zeitraum halbieren", ["tool:graylog_search"], {"source": "x"}, reason="T")
    for i in range(200):  # graylog without hint 50 %, with hint 90 %
        g.new_object("experience", "g", ["tool:graylog_search", "ok:yes" if rng.random() < 0.5 else "ok:no"], {"before": {"shown": []}, "args": {"k": i}}, reason="T")
        g.new_object("experience", "g", ["tool:graylog_search", "ok:yes" if rng.random() < 0.9 else "ok:no"], {"before": {"shown": [helps.id]}, "args": {"l": i}}, reason="T")
    r = bandit.recompute()
    assert r["hinweise"] == 2
    e_empty, e_helps = bandit.expectation(g.load(empty.id)), bandit.expectation(g.load(helps.id))
    assert 0.35 < e_empty < 0.65 and e_helps > 0.75, (e_empty, e_helps)
    assert abs(bandit.lift(g.load(empty.id)) or 0) < 0.06 and bandit.lift(g.load(helps.id)) > 0.3
    old = g.new_object("rule", "Altlast mit falschen Zählern", ["tool:x"], {"source": "x", "useful": {"yes": 226, "no": 1}}, reason="T")
    bandit.recompute()
    assert "useful" not in g.load(old.id).data  # no counters without a rated action


def test_hint_is_measured_against_its_own_instances_rate(gd):
    """0.70.1 (bandit v2): a hint shown only where actions often fail is measured against THAT instance's rate for the tool, not against
    the tool pooled over all instances — otherwise an ineffective hint for a hard place reads "harmful" (Simpson). Live and in sleep."""
    from vi_mcp import bandit
    rng = random.Random(9)
    hint = g.new_object("insight", "hard host needs sudo", ["tool:Bash"], {"source": "x"}, reason="T")
    for i in range(300):  # instance "easy": Bash 98 % without a hint
        g.new_object("experience", "Bash", ["tool:Bash", "ok:yes" if rng.random() < 0.98 else "ok:no"], {"before": {"shown": []}, "args": {"e": i}},
                     reason="T", instance="easy")
    for i in range(200):  # instance "hard": 60 % without and 60 % with the (ineffective) hint
        g.new_object("experience", "Bash", ["tool:Bash", "ok:yes" if rng.random() < 0.6 else "ok:no"], {"before": {"shown": []}, "args": {"h": i}},
                     reason="T", instance="hard")
        g.new_object("experience", "Bash", ["tool:Bash", "ok:yes" if rng.random() < 0.6 else "ok:no"], {"before": {"shown": [hint.id]}, "args": {"w": i}},
                     reason="T", instance="hard")
    r = bandit.recompute()
    assert r["methode"] == "vorteil-v2" and r["grundraten_instanz"] == 2
    assert abs(bandit.lift(g.load(hint.id))) < 0.08, bandit.lift(g.load(hint.id))  # pooled Bash (~0.82) would say about −22 points
    assert abs(bandit.base_rate("Bash", "hard") - 0.6) < 0.08 and bandit.base_rate("Bash", "easy") > 0.93
    assert bandit.base_rate("Bash", "unknown-instance") == bandit.base_rate("Bash")  # too few → the tool's rate
    before = g.load(hint.id).data["useful"]["expected"]
    bandit.book_entry([hint.id], True, "Bash", "hard")  # live: the same expected rate as in sleep
    assert abs(g.load(hint.id).data["useful"]["expected"] - before - bandit.base_rate("Bash", "hard")) < 1e-6


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn fehlt")
def test_warning_before_risky_actions(gd):
    """0.20.8: the router model detects situations in which actions often fail and warns with a counted reason."""
    rnd = random.Random(7)
    for _ in range(400):
        broken = rnd.random() < 0.3
        action("deploy_run", "kaputt1" if broken else f"gut{rnd.randint(1, 5)}", (rnd.random() < 0.1) if broken else (rnd.random() < 0.95))
    r = learning.train("Test")
    # 0.30.0: no hints at all — the ranking cannot show utility (not determinable), the warning still works on the AUC alone
    assert r["zustand"] == "test" and r["nutzen_holdout"]["zustand"] == "nicht_bestimmbar"
    assert r["warnung"]["zustand"] == "aktiv" and r["warnung"]["praezision_pct"] >= 50
    w = learning.warning(intuition.triggers("deploy_run", {"host": "kaputt1"}))
    assert w and w.startswith("[VI warning]") and "host:kaputt1:" in w and "actions failed" in w
    assert learning.warning(intuition.triggers("deploy_run", {"host": "gut2"})) is None
    v = intuition.before("deploy_run", {"host": "kaputt1", "n": -1}, "a")
    assert any(h.startswith("[VI warning]") for h in v["hinweise"])
    assert "Warning before risky actions: active" in learning.explanation()


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn fehlt")
def test_a_tool_that_fails_often_is_no_reason_to_warn(gd):
    """0.63.0, production 13.11.2026: 826 of 848 warnings came before one automated tool failing 61 % of the time, and named only that
    tool — "check arguments, paths and reachability" before every one of its actions. Only what fails more often than the tool warns."""
    rnd = random.Random(11)
    for _ in range(500):
        action("deploy_run", f"gut{rnd.randint(1, 5)}", rnd.random() < 0.97)
    for _ in range(300):
        host = "kaputt9" if rnd.random() < 0.2 else f"web{rnd.randint(1, 5)}"
        action("analyse", host, (rnd.random() < 0.05) if host == "kaputt9" else (rnd.random() < 0.5))
    r = learning.train("Test")
    assert r["warnung"]["zustand"] == "aktiv"
    assert learning.warning(intuition.triggers("analyse", {"host": "web3"})) is None  # only the tool's own rate: no warning
    w = learning.warning(intuition.triggers("analyse", {"host": "kaputt9"}))
    assert w and w.index("host:kaputt9:") < w.index("tool:analyse:")  # the host is the reason, the tool's rate only context


def test_hint_feedback_is_direct_learning_signal(gd):
    """0.20.9: vi_bestaetige/vi_widerlege of a hint just shown becomes the label of the pair (situation + hint)."""
    h = g.new_object("insight", "web7 braucht den Proxy", ["host:web7"], {"source": "x"}, reason="T", instance="b")
    action("checkmk_get_host", "web7", False)  # the action failed anyway — the indirect label would be 0
    outputs = tools.call_tool("vi_bestaetige", {"id": h.id, "grund": "Hinweis war richtig, Fehler hatte andere Ursache"}, "a", True)
    assert "feedback on the hint" in outputs
    pair = [y for m, y, _ in learning.observations() if f"hint:{h.id}" in m]
    assert pair == [1]
    # refuting an object that was not shown: normal refutation, no feedback
    others = g.new_object("insight", "web8 ist abgeschaltet", ["host:web8"], {"source": "y"}, reason="T", instance="b")
    assert "feedback" not in tools.call_tool("vi_widerlege", {"id": others.id, "grund": "stimmt nicht"}, "a", True)


def test_holdout_grows_until_enough_failures():
    """0.20.9: with 9 failures in the most recent 20 % the AUC varied strongly; the holdout grows up to 30 failures (at most 50 %)."""
    y = [0] * 100 + [1] * 800 + [0] * 5 + [1] * 95  # most recent 20 % = 200 actions with only 5 failures
    n = learning._holdout_size(y)
    assert n == 500 and len(y[-n:]) - sum(y[-n:]) >= 5  # grows up to HOLDOUT_MAX because enough failures lie only at the very front
    assert learning._holdout_size([1, 0] * 500) == 200  # enough failures: stays at 20 %


def test_contributions_add_up_to_the_prediction(gd):
    """0.29.0: vi_why lays open the same arithmetic as the router — the contributions plus intercept are the logit."""
    import math
    m = g.new_object("model", "Testmodell", ["modell:router"],
                     {"state": "aktiv", "gewichte": {"hint:regel:gut": 1.5, "hint_kind:rule": 0.25, "hint_n:1": -0.2, "skill:x": 0.5},
                      "achsenabschnitt": -0.3}, oid=learning.model_id(None), reason="T", instance=g.SERVER_INSTANCE)
    f = {"skill:x": 1.0, "hint_n:1": 1.0, "hint:regel:gut": 1.0, "hint_kind:rule": 1.0, "unbekannt:y": 1.0}
    c = learning.contributions(m, f)
    assert c[0] == ("hint:regel:gut", 1.5) and "unbekannt:y" not in dict(c)
    p = learning.prediction(m, f)
    assert abs(math.log(p / (1 - p)) - (m.data["achsenabschnitt"] + sum(v for _, v in c))) < 1e-9
    w = learning.why(m, "regel:gut", ["skill:x"])
    assert w["lift"] > 0 and dict(w["hint"])["hint:regel:gut"] == 1.5 and dict(w["situation"]) == {"skill:x": 0.5}
    assert w["p_with"] == learning.ranking(m, ["skill:x"], ["regel:gut"])[0][1] + w["p_without"]


def test_vi_why_explains_the_stored_decision(gd):
    h = g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x"}, reason="T", instance="b")
    action("checkmk_get_host", "web1", True)
    out = tools.call_tool("vi_why", {"id": h.id}, "a", False)
    assert "position 1 of 1, router heuristik" in out and "1 trigger(s) match" in out and "host:web1" in out and "Router model: none yet" in out
    # another instance never saw it: no invented reason, a named state instead
    assert "was not shown to c" in tools.call_tool("vi_why", {"id": h.id}, "c", False)
    assert "Situation given: host:web1" in tools.call_tool("vi_why", {"id": h.id, "triggers": ["host:web1"]}, "c", False)
    with pytest.raises(tools.Rejected, match="kind:value"):
        tools.call_tool("vi_why", {"id": h.id, "triggers": ["web1"]}, "a", False)
    with pytest.raises(tools.Rejected, match="unknown"):
        tools.call_tool("vi_why", {"id": "erkenntnis:gibtsnicht"}, "a", False)


def test_lift_by_age_splits_new_and_old_hints(gd, monkeypatch):
    """0.29.0: cold-start observation point — advantage over the tool's base rate, by the hint's age when shown."""
    from datetime import datetime, timedelta, timezone
    from vi_mcp import bandit, metrics
    monkeypatch.setattr(bandit, "base_rate", lambda tool, instance=None: 0.5)
    old = g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x"}, reason="T", instance="b")
    new = g.new_object("insight", "web1 hat neues Zertifikat", ["host:web1"], {"source": "y"}, reason="T", instance="b")
    gone = g.new_object("insight", "web1 alt", ["host:web1"], {"source": "z"}, reason="T", instance="b")
    long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="milliseconds")
    with g.lock:
        g.db().execute("UPDATE object SET ts = ? WHERE id = ?", (long_ago, old.id))
        g.db().commit()
    for i in range(24):
        ok = i % 4 != 0  # 75 % ok
        e = g.new_object("experience", f"checkmk_get_host {i}", ["tool:checkmk_get_host", "ok:yes" if ok else "ok:no"],
                         {"before": {"shown": [old.id, new.id if i % 2 else gone.id]}}, reason="T", instance="a")
    with g.lock:
        g.db().execute("DELETE FROM object WHERE id = ?", (gone.id,))
        g.db().commit()
    r = metrics.lift_by_age(24)
    assert r["alt"]["n"] == 24 and r["neu"]["n"] == 12 and r["unbekannt"]["n"] == 12  # nothing vanishes silently
    # the new hint was only shown before odd i, which all succeeded: +0.5 against +0.25 for the old one
    assert abs(r["alt"]["vorteil"] - 0.25) < 1e-9 and abs(r["neu"]["vorteil"] - 0.5) < 1e-9 and r["urteil"] == "new hints stronger"
    assert "new (≤ 7 d) 12 shown" in metrics.age_line(r) and "12 of hints that no longer exist" in metrics.age_line(r)


def test_vi_why_separates_what_is_same_for_every_candidate(gd):
    """0.30.0: hinweis_n moves every lift alike; vi_why reports it apart from what decides the order."""
    m = g.new_object("model", "Testmodell", ["modell:router"],
                     {"state": "aktiv", "gewichte": {"hint_n:1": -0.35, "hint_n:0": 0.05, "hint_kind:insight": 0.2, "tool:x": 0.1},
                      "achsenabschnitt": 0.0}, oid=learning.model_id(None), reason="T", instance=g.SERVER_INSTANCE)
    h = g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x"}, reason="T", instance="b")
    w = learning.why(m, h.id, ["tool:x"])
    assert abs(w["same_for_all"] - (-0.40)) < 1e-9 and dict(w["distinguishing"]) == {"hint_kind:insight": 0.2}
    out = tools.call_tool("vi_why", {"id": h.id, "triggers": ["tool:x"]}, "a", False)
    assert "decides the order): +0.200" in out and "never the order): hint_n:1 − hint_n:0 = -0.400" in out


def test_hint_age_is_a_feature(gd):
    """0.30.0: alter:neu when the hint was at most metrics.NEW_DAYS old at the time it was shown."""
    from datetime import datetime, timedelta, timezone
    h = g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x"}, reason="T", instance="b")
    now = datetime.now(timezone.utc)
    assert learning.hint_features(h.id, [], now.isoformat())["age:new"] == 1.0
    assert "age:new" not in learning.hint_features(h.id, [], (now + timedelta(days=8)).isoformat())
    assert "age:new" not in learning.hint_features(h.id, [])  # no time, no age claim
    action("checkmk_get_host", "web1", True)
    assert any(m.get("age:new") == 1.0 and f"hint:{h.id}" in m for m, _y, _o in learning.observations())


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn fehlt")
def test_good_auc_without_ranking_utility_stays_test(gd):
    """0.30.0: the situation predicts the outcome (high AUC), the two hints do nothing — the order of hints must not go live."""
    rnd = random.Random(3)
    r = g.new_object("rule", "Hinweis A", ["tool:deploy_run"], {"source": "x"}, reason="T")
    e = g.new_object("insight", "Hinweis B", ["tool:deploy_run"], {"source": "x"}, reason="T")
    for i in range(1600):
        broken = i % 2 == 0
        ok = rnd.random() < (0.05 if broken else 0.95)
        host = "host:kaputt1" if broken else "host:gut1"
        g.new_object("experience", "deploy", ["tool:deploy_run", host, "ok:yes" if ok else "ok:no"],
                     {"before": {"triggers": ["tool:deploy_run", host], "shown": [rnd.choice([r.id, e.id])]}, "args": {"i": i}},
                     reason="T", instance="a")
    b = learning.train("Test")
    assert b["auc_holdout"] > 0.85 and b["zustand"] == "test" and b["nutzen_holdout"]["zustand"] == "kein_nutzen", b
    assert "ranking utility kein_nutzen" in b["urteil"] and learning.active() is None
    assert "Ranking utility on the holdout: kein_nutzen" in learning.explanation()


def test_gate_needs_two_standard_errors():
    """0.32.0 (Mayo, severity): a gap of about 1.5 standard errors passed the old gate (> 1 SE), it no longer does."""
    top = [(1.0, 0.7 if i % 2 else -0.3) for i in range(30)]      # mean +0.2
    bottom = [(0.0, 0.5 if i % 2 else -0.5) for i in range(30)]   # mean 0
    r = learning._gap(top + bottom, 30)
    assert 1.0 < r["abstand"] / r["standardfehler"] < 2.0 and r["zustand"] == "kein_nutzen" and "2 standard errors" in r["urteil"]


def test_gate_must_hold_in_every_reference_class(monkeypatch):
    """0.32.0 (generality problem): hint A is only shown on an easy host, hint B only on a hard one. Against the tool's base rate the
    order looks useful; against tool+host it is not — the "usefulness" was the host. The gate must not pass."""
    from vi_mcp import bandit
    monkeypatch.setattr(bandit, "base_rate", lambda tool, instance=None: 0.55)
    train = [({"tool:t": 1.0, "host:easy": 1.0, "hint_n:0": 1.0}, int(i % 10 != 0), f"e{i}") for i in range(50)]
    train += [({"tool:t": 1.0, "host:hard": 1.0, "hint_n:0": 1.0}, int(i % 10 < 2), f"h{i}") for i in range(50)]
    holdout = [({"tool:t": 1.0, "host:easy": 1.0, "hint_n:1": 1.0, "hint:A": 1.0}, int(i % 10 != 0), f"a{i}") for i in range(100)]
    holdout += [({"tool:t": 1.0, "host:hard": 1.0, "hint_n:1": 1.0, "hint:B": 1.0}, int(i % 10 < 2), f"b{i}") for i in range(100)]
    u = learning.utility({"hint:A": 2.0, "hint:B": -2.0}, 0.0, holdout, train)
    assert u["je_bezugsklasse"]["tool"]["zustand"] == "nutzen" and u["je_bezugsklasse"]["tool+host"]["zustand"] == "kein_nutzen"
    assert u["zustand"] == "kein_nutzen" and "tool+host:" in u["urteil"]


def test_inseparable_hints_are_named():
    """0.32.0 (Duhem): two hints always shown in the same actions are reported as one group; a hint also shown alone is not."""
    obs = [({"hint:A": 1.0, "hint:B": 1.0, "hint:C": 1.0}, 1, f"x{i}") for i in range(12)]
    obs += [({"hint:C": 1.0}, 0, f"y{i}") for i in range(3)]
    r = learning.inseparable(obs)
    assert r == {"gruppen": 1, "hinweise": 2, "beispiele": [["A", "B"]]}


def test_champion_challenger_on_unseen_observations(gd):
    # 0.55.0: the model of the last sleep against the new one, only on observations after the champion was trained
    from vi_mcp import learning
    old = [g.new_object("experience", f"old {i}", ["tool:Bash"], {}) for i in range(5)]
    time.sleep(0.01)
    champ = {"gewichte": {"tool:Bash": 2.0}, "achsenabschnitt": 0.0, "trainiert": g.now()}
    time.sleep(0.01)
    new = [g.new_object("experience", f"new {i}", ["tool:Bash"], {}) for i in range(learning.CHAMPION_MIN_N)]
    holdout = [({"tool:Bash": 1.0}, 1, o.id) for o in old + new]
    assert learning.compare_champion(None, {}, 0.0, holdout)["zustand"] == "kein_champion"
    worse = learning.compare_champion(champ, {"tool:Bash": -2.0}, 0.0, holdout)  # predicts failure where everything succeeded
    assert worse["zustand"] == "schlechter" and worse["n"] == learning.CHAMPION_MIN_N  # the 5 older ones are not counted
    assert learning.compare_champion(champ, {"tool:Bash": 3.0}, 0.0, holdout)["zustand"] == "nicht_schlechter"
    few = learning.compare_champion(champ, {"tool:Bash": 3.0}, 0.0, holdout[:20])
    assert few["zustand"] == "nicht_bestimmbar"


def test_training_notice_is_early_in_the_instructions(gd):
    # 0.57.0: the AI learns how the hints are chosen and what the marker means, before clients cut long instructions
    from vi_mcp import learning, server
    t = learning.training_notice()
    assert t.startswith("[Training]") and "no model yet" in t and "vi_solved" in t and "measured +X pts/N×" in t and len(t) <= 600
    assert server._training_notice() == t


def test_calibration_table_and_ece():
    """0.62.0: a perfectly calibrated forecaster has ECE 0; one that says 0.9 for events that happen half the time has ECE 0.4."""
    from vi_mcp import learning
    good = learning.calibration([0.25] * 4 + [0.75] * 4, [1, 0, 0, 0, 1, 1, 1, 0])
    assert good["ece_holdout"] == 0.0 and good["zuverlaessigkeit_holdout"] == [[0.2, 0.25, 0.25, 4], [0.7, 0.75, 0.75, 4]]
    bad = learning.calibration([0.9] * 10, [1, 0] * 5)
    assert bad["ece_holdout"] == 0.4 and bad["zuverlaessigkeit_holdout"] == [[0.9, 0.9, 0.5, 10]]
    assert learning.calibration([], []) == {}


def test_ips_factors_follow_the_logged_offer_probabilities(gd):
    """0.62.0: one factor per observation, 1/p of the hint's offer probability, clipped; 1 where nothing random was logged."""
    from vi_mcp import learning
    h1 = g.new_object("insight", "hint one", ["tool:Bash"], {"source": "t"}).id
    h2 = g.new_object("insight", "hint two", ["tool:Bash"], {"source": "t"}).id
    g.new_object("experience", "Bash ok", ["tool:Bash", "ok:yes"], {"before": {"triggers": ["tool:Bash"], "shown": [h1, h2],
                                                                            "offer": {h1: 0.9, h2: 0.02}}})
    g.new_object("experience", "Bash failed", ["tool:Bash", "ok:no"], {"before": {"triggers": ["tool:Bash"], "shown": []}})
    ips: list = []
    obs = learning.weighted_observations(ips_out=ips)
    assert len(ips) == len(obs) == 3
    assert sorted(round(x, 3) for x in ips) == [1.0, 1.111, learning.IPS_CLIP]  # 1/0.9, 1/0.02 clipped to 10, no hint → 1


def test_off_policy_correction_is_kept_only_when_it_wins():
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from vi_mcp import learning
    rng = np.random.default_rng(1)
    X = rng.normal(size=(600, 3))
    y = (X[:, 0] + 0.3 * rng.normal(size=600) > 0).astype(int)
    Xtr, Xte, ytr, yte = X[:400], X[400:], y[:400], y[400:]
    w = np.ones(400)
    clf = LogisticRegression().fit(Xtr, ytr)
    same, rep = learning._off_policy(clf, Xtr, ytr, w, np.ones(400), Xte, yte)
    assert same is clf and rep["zustand"] == "keine_propensities"
    # propensities unrelated to the outcome: the correction adds only variance and must not be kept
    noise = rng.uniform(1, 10, 400)
    kept, rep = learning._off_policy(clf, Xtr, ytr, w, noise, Xte, yte)
    assert rep["zustand"] == "verworfen" and kept is clf and "rejected" in rep["urteil"] and rep["gewichtet"] == 400


def test_off_policy_correction_is_kept_when_it_is_clearly_better(monkeypatch):
    import numpy as np
    from vi_mcp import learning
    class Fixed:
        def __init__(self, good):
            self.good = good

        def predict_proba(self, X):
            p = np.where(X[:, 0] == 1, 0.95, 0.05) if self.good else np.full(len(X), 0.5)
            return np.column_stack([1 - p, p])
    monkeypatch.setattr(learning, "fit_calibrated", lambda X, y, w, groups=None: (Fixed(not np.allclose(w, 1)), {}))
    y = np.array([0, 1] * 200)
    kept, rep = learning._off_policy(Fixed(False), y.reshape(-1, 1), y, np.ones(400), np.array([1.0, 3.0] * 200),
                                     None, None)  # the final holdout cannot even be read
    assert rep["zustand"] == "uebernommen" and kept.good and rep["log_loss_mit"] < rep["log_loss_ohne"]

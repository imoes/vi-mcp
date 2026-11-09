"""0.5.0: Lernen — Beobachtungen, Erkundung, Router-Modell (sklearn optional), Vorhersage ohne sklearn."""
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
    g.new_object("erkenntnis", "web1 braucht Proxy", ["host:web1"], {"quelle": "x"}, reason="T")
    action("checkmk_get_host", "web1", True, context=["thema:oom"])
    action("checkmk_get_host", "web2", False)
    with g.lock:
        rows = g.db().execute("SELECT tool, ok, hinweise_n, ueberraschung, router FROM beobachtung ORDER BY zeit").fetchall()
    assert rows[0][:3] == ("checkmk_get_host", 1, 1) and rows[1][:3] == ("checkmk_get_host", 0, 0) and rows[0][4] == "heuristik"
    b = learning.observations()
    assert len(b) == 2  # ein Paar (mit Hinweis) + eine Basis (ohne)
    with_hint = next(m for m, y, _ in b if y == 1)
    assert "thema:oom" in with_hint and "hinweisart:erkenntnis" in with_hint and "hinweis_n:1" in with_hint and any(k.startswith("hinweis:erkenntnis:") for k in with_hint)
    without = next(m for m, y, _ in b if y == 0)
    assert "hinweis_n:0" in without and not any(k.startswith("hinweis:") for k in without)
    assert "thema:oom" in g.recall("tool:checkmk_get_host ok:ja", viewer=None)[0][1].hashtags  # Kontext-Reiz ist Tag


def test_exploration_is_tagged(gd, monkeypatch):
    for i in range(8):
        g.new_object("erkenntnis", f"Hinweis {i} zu web3", ["host:web3"], {"quelle": "x"}, reason="T")
    monkeypatch.setattr(learning, "EPSILON", 1.0)
    v = intuition.before("Bash", {"host": "web3"}, "a", False)
    assert v["zugriff"]["exploration"] is True and len(v["zugriff"]["gezeigt"]) == intuition.HINT_BUDGET
    assert any("(Erkundung)" in h for h in v["hinweise"]) and len(v["zugriff"]["kandidaten"]) == 8
    assert v["zugriff"]["gezeigt"][-1] not in v["zugriff"]["kandidaten"][:intuition.HINT_BUDGET]
    monkeypatch.setattr(learning, "EPSILON", 0.0)
    v = intuition.before("Bash", {"host": "web3"}, "a", False)
    assert v["zugriff"]["exploration"] is False and v["zugriff"]["router"] == "heuristik"


def test_prediction_without_sklearn_and_ranking(gd):
    m = g.new_object("modell", "Testmodell", ["modell:router"],
                       {"zustand": "aktiv", "gewichte": {"hinweis:regel:gut": 2.0, "hinweis:erkenntnis:schlecht": -2.0, "skill:x": 0.5}, "achsenabschnitt": 0.0},
                       oid=learning.MODEL, reason="T", instance=g.SERVER_INSTANCE)
    p = learning.prediction(m, {"skill:x": 1.0, "hinweis:regel:gut": 1.0})
    assert abs(p - 1 / (1 + 2.718281828 ** -2.5)) < 1e-6
    r = learning.ranking(m, ["skill:x"], ["erkenntnis:schlecht", "erkenntnis:neutral", "regel:gut"])
    assert [h for h, _ in r] == ["regel:gut", "erkenntnis:neutral", "erkenntnis:schlecht"] and r[0][1] > 0 > r[2][1]


def test_too_little_data_and_missing_sklearn(gd, monkeypatch):
    action("t_a", "h", True)
    b = learning.train("Test")
    if HAS_SKLEARN:
        assert b["zustand"] == "zu_wenig_daten" and g.load(learning.MODEL).mode == "test" and learning.active() is None
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
    """Synthetik: Hinweis R (Regel) → ok 90 %; Hinweis E (Erkenntnis) → ok 20 %. Jede Handlung bekommt genau einen
    der beiden gezeigt (wie bei Budget 1 / Erkundung). Nach dem Training: Gewicht(R) > 0 > Gewicht(E), R zuerst."""
    random.seed(7)
    r = g.new_object("regel", "vor graylog_search Zeitraum setzen", ["skill:graylog"], {"quelle": "x"}, reason="T")
    e = g.new_object("erkenntnis", "graylog ist immer schnell", ["skill:graylog"], {"quelle": "x"}, reason="T")
    for i in range(400):
        args = {"q": i}
        v = intuition.before("graylog_search", args, "a")
        intuition.after("graylog_search", args, True, 1, None, "ok", v["vorher_id"], "a")
    with g.lock:  # „gezeigt“ auf genau einen Hinweis setzen und das Label danach würfeln
        rows = g.db().execute("SELECT id, daten FROM objekt WHERE art = 'erfahrung'").fetchall()
        for i, (oid, data) in enumerate(rows):
            d = json.loads(data)
            only = [r.id] if i % 2 == 0 else [e.id]
            ok_new = random.random() < (0.9 if only == [r.id] else 0.2)
            d["vorher"]["gezeigt"] = only
            g.db().execute("UPDATE objekt SET daten = ? WHERE id = ?", (json.dumps(d), oid))
            g.db().execute("DELETE FROM tag WHERE objekt_id = ? AND tag IN ('ok:ja', 'ok:nein')", (oid,))
            g.db().execute("INSERT INTO tag VALUES (?, ?)", (oid, "ok:ja" if ok_new else "ok:nein"))
        g.db().commit()
    b = learning.train("Test")
    assert b["zustand"] == "aktiv", b
    m = learning.active()
    assert m and m.data["gewichte"][f"hinweis:{r.id}"] > 0 > m.data["gewichte"][f"hinweis:{e.id}"]
    rf = learning.ranking(m, ["tool:graylog_search", "skill:graylog"], [e.id, r.id])
    assert rf[0][0] == r.id and rf[0][1] > 0.3
    v = intuition.before("graylog_search", {"q": "neu"}, "a")
    assert v["zugriff"]["router"] == "modell" and v["zugriff"]["gezeigt"][0] == r.id
    assert "Router-Modell (aktiv)" in tools.call_tool("vi_modell", {}, "a", True)
    assert sleep_cycle.run("Test").data["schritte"]["8_lernen"]["zustand"] == "aktiv"


def test_bandit_counters_and_ranking(gd):
    from vi_mcp import bandit
    good = g.new_object("regel", "Zeitraum setzen hilft", ["skill:graylog"], {"quelle": "x"}, reason="T")
    bad = g.new_object("erkenntnis", "graylog ist immer schnell", ["skill:graylog"], {"quelle": "x"}, reason="T")
    v = intuition.before("graylog_search", {"q": 0}, "a")
    assert v["zugriff"]["router"] == "heuristik" and set(v["zugriff"]["gezeigt"]) == {good.id, bad.id}
    # Zähler: 20× nach dem Zeigen von „gut“ ok, 20× nach „schlecht“ nicht ok (direkt verbucht, wie nachher es tut)
    bandit._reason.update(zeit=time.time(), je={"graylog_search": 0.5}, alle=0.5)  # Grundrate des Werkzeugs: halbe-halbe
    assert bandit.book_entry([good.id], True, "graylog_search") == 1 and bandit.book_entry(["antwort:x"], True) == 0 and bandit.book_entry([good.id], None) == 0
    for _ in range(19):
        bandit.book_entry([good.id], True, "graylog_search")
    for _ in range(20):
        bandit.book_entry([bad.id], False, "graylog_search")
    assert bandit.counter(g.load(good.id)) == (10, 0) and bandit.counter(g.load(bad.id)) == (0, 10) and bandit.shown(g.load(good.id)) == 20
    assert "20× gezeigt, Erfolg danach 100 % statt erwartet 50 % (+50 Punkte)" in tools.call_tool("vi_objekt", {"id": good.id}, "a", True)
    rnd = random.Random(1)
    fresh = [g.load(bad.id), g.load(good.id)]  # Zähler stehen in der DB; vorher() lädt Kandidaten immer frisch
    in_front = sum(1 for _ in range(100) if bandit.arrange(fresh, rnd)[0].id == good.id)
    assert in_front >= 95  # Beta(11,1) gegen Beta(1,11)
    v = intuition.before("graylog_search", {"q": 1}, "a")
    assert v["zugriff"]["router"] == "bandit"
    n = intuition.after("graylog_search", {"q": 1}, False, 1, "Fehler", None, v["vorher_id"], "a")
    assert n["bewertet"] == len(v["zugriff"]["gezeigt"])
    assert bandit.counter(g.load(good.id))[1] == 0.5 and bandit.shown(g.load(good.id)) == 21  # „nein“ nach echter Handlung verbucht, gewichtet mit der Grundrate


def test_ineffective_hint_stays_at_half(gd):
    """Ein Hinweis, der vor einem fast immer gelingenden Werkzeug steht, bekommt keinen Vorteil gutgeschrieben, ein hilfreicher schon."""
    from vi_mcp import bandit
    empty = g.new_object("regel", "Bash scheiterte und gelang danach", ["tool:Bash"], {"quelle": "x"}, reason="T")
    rng = random.Random(4)
    for i in range(400):  # Bash ohne Hinweis: 94 %
        g.new_object("erfahrung", "Bash", ["tool:Bash", "ok:ja" if rng.random() < 0.94 else "ok:nein"], {"vorher": {"gezeigt": []}, "args": {"i": i}}, reason="T")
    for i in range(300):  # mit dem leeren Hinweis: ebenfalls 94 %
        g.new_object("erfahrung", "Bash", ["tool:Bash", "ok:ja" if rng.random() < 0.94 else "ok:nein"], {"vorher": {"gezeigt": [empty.id]}, "args": {"j": i}}, reason="T")
    helps = g.new_object("regel", "Zeitraum halbieren", ["tool:graylog_search"], {"quelle": "x"}, reason="T")
    for i in range(200):  # graylog ohne Hinweis 50 %, mit Hinweis 90 %
        g.new_object("erfahrung", "g", ["tool:graylog_search", "ok:ja" if rng.random() < 0.5 else "ok:nein"], {"vorher": {"gezeigt": []}, "args": {"k": i}}, reason="T")
        g.new_object("erfahrung", "g", ["tool:graylog_search", "ok:ja" if rng.random() < 0.9 else "ok:nein"], {"vorher": {"gezeigt": [helps.id]}, "args": {"l": i}}, reason="T")
    r = bandit.recompute()
    assert r["hinweise"] == 2
    e_empty, e_helps = bandit.expectation(g.load(empty.id)), bandit.expectation(g.load(helps.id))
    assert 0.35 < e_empty < 0.65 and e_helps > 0.75, (e_empty, e_helps)
    assert abs(bandit.lift(g.load(empty.id)) or 0) < 0.06 and bandit.lift(g.load(helps.id)) > 0.3
    old = g.new_object("regel", "Altlast mit falschen Zählern", ["tool:x"], {"quelle": "x", "nuetzlich": {"ja": 226, "nein": 1}}, reason="T")
    bandit.recompute()
    assert "nuetzlich" not in g.load(old.id).data  # ohne bewertete Handlung keine Zähler


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn fehlt")
def test_warning_before_risky_actions(gd):
    """0.20.8: Das Router-Modell erkennt Lagen, in denen Handlungen oft scheitern, und warnt mit gezählter Begründung."""
    rnd = random.Random(7)
    for _ in range(400):
        broken = rnd.random() < 0.3
        action("deploy_run", "kaputt1" if broken else f"gut{rnd.randint(1, 5)}", (rnd.random() < 0.1) if broken else (rnd.random() < 0.95))
    r = learning.train("Test")
    assert r["zustand"] == "aktiv" and r["warnung"]["zustand"] == "aktiv" and r["warnung"]["praezision_pct"] >= 50
    w = learning.warning(intuition.triggers("deploy_run", {"host": "kaputt1"}))
    assert w and w.startswith("[VI-Warnung]") and "host:kaputt1:" in w and "Handlungen scheiterten" in w
    assert learning.warning(intuition.triggers("deploy_run", {"host": "gut2"})) is None
    v = intuition.before("deploy_run", {"host": "kaputt1", "n": -1}, "a")
    assert any(h.startswith("[VI-Warnung]") for h in v["hinweise"])
    assert "Warnung vor riskanten Handlungen: aktiv" in learning.explanation()


def test_hint_feedback_is_direct_learning_signal(gd):
    """0.20.9: vi_bestaetige/vi_widerlege eines gerade gezeigten Hinweises wird zum Label des Paares (Lage + Hinweis)."""
    h = g.new_object("erkenntnis", "web7 braucht den Proxy", ["host:web7"], {"quelle": "x"}, reason="T", instance="b")
    action("checkmk_get_host", "web7", False)  # Handlung scheiterte trotzdem — das indirekte Label wäre 0
    outputs = tools.call_tool("vi_bestaetige", {"id": h.id, "grund": "Hinweis war richtig, Fehler hatte andere Ursache"}, "a", True)
    assert "Rückmeldung zum Hinweis" in outputs
    pair = [y for m, y, _ in learning.observations() if f"hinweis:{h.id}" in m]
    assert pair == [1]
    # Widerlegen eines Objekts, das nicht gezeigt wurde: normale Widerlegung, keine Rückmeldung
    others = g.new_object("erkenntnis", "web8 ist abgeschaltet", ["host:web8"], {"quelle": "y"}, reason="T", instance="b")
    assert "Rückmeldung" not in tools.call_tool("vi_widerlege", {"id": others.id, "grund": "stimmt nicht"}, "a", True)


def test_holdout_grows_until_enough_failures():
    """0.20.9: Mit 9 Fehlschlägen in den jüngsten 20 % schwankte die AUC stark; das Holdout wächst bis 30 Fehlschläge (höchstens 50 %)."""
    y = [0] * 100 + [1] * 800 + [0] * 5 + [1] * 95  # jüngste 20 % = 200 Handlungen mit nur 5 Fehlschlägen
    n = learning._holdout_size(y)
    assert n == 500 and len(y[-n:]) - sum(y[-n:]) >= 5  # wächst bis HOLDOUT_MAX, weil erst ganz vorn genug Fehlschläge liegen
    assert learning._holdout_size([1, 0] * 500) == 200  # genug Fehlschläge: bleibt bei 20 %

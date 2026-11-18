"""0.29.0: weight audit — fixed rules read the router weights and name what looks wrong; nothing is changed."""
from vi_mcp import learning, sleep_cycle, tools, weight_audit
from vi_mcp import memory as g


def _model(weights):
    return g.new_object("model", "Testmodell", ["modell:router"], {"state": "aktiv", "gewichte": weights, "achsenabschnitt": 0.0},
                        oid=learning.model_id(None), reason="T", instance=g.SERVER_INSTANCE)


def test_no_model_is_a_named_state(gd):
    r = weight_audit.audit()
    assert r["zustand"] == "kein_modell" and "no trained router weights" in weight_audit.line(r)


def test_clean_weights_are_ok(gd):
    _model({"tool:a": 0.4, "tool:b": -0.3, "skill:c": 0.35, "host:d": 0.3, "topic:e": -0.25, "hour:03": 0.01})
    r = weight_audit.audit()
    assert r["zustand"] == "ok" and r["befunde"] == [] and "none of dominant, contradicts, network, hour" in weight_audit.line(r)


def test_each_class_is_found(gd):
    good = g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x", "useful": {"yes": 2, "no": 20, "n": 30, "ok": 6, "expected": 15}},
                        reason="T", instance="b")  # measured: −30 points
    net = g.new_object("insight", "aus dem Netz", ["host:web2", "origin:p2p", "publisher:peer1"], {"source": "y"}, reason="T", instance="p2p")
    m = _model({f"hint:{good.id}": 1.2, f"hint:{net.id}": 0.8, "hour:14": -5.0, "tool:a": 0.3, "tool:b": 0.2, "tool:c": 0.2, "tool:d": 0.1})
    r = weight_audit.audit()
    assert r["je_klasse"] == {"dominant": 1, "contradicts": 1, "network": 1, "hour": 1}
    by = {f["klasse"]: f for f in r["befunde"]}
    assert by["dominant"]["merkmal"] == "hour:14" and by["contradicts"]["merkmal"] == f"hint:{good.id}"
    assert "-30 points over 30 showings" in by["contradicts"]["grund"] and "peer1" in by["network"]["grund"]
    assert g.load(learning.model_id(None)).data["gewichte"] == m.data["gewichte"] and g.load(good.id).mode == "active"  # read only
    assert "Weight audit: dominant 1" in tools.call_tool("vi_modell", {}, "a", True)


def test_sleep_runs_the_audit_after_learning(gd):
    rep = sleep_cycle.run("Test").data["schritte"]
    assert "8b_gewichte_pruefen" in rep and rep["8b_gewichte_pruefen"]["zustand"] in ("kein_modell", "ok", "befunde")


def test_group_weight_against_measured_hints(gd, monkeypatch):
    """0.30.0: a meaning-group weight that pushes down hints which are measured as good is a contradiction, too."""
    from vi_mcp import content
    a = g.new_object("insight", "nginx -t vor reload", ["tool:Bash"], {"source": "x", "useful": {"yes": 9, "no": 1, "n": 15, "ok": 14, "expected": 10}},
                     reason="T", instance="b")
    b = g.new_object("rule", "certbot dry-run", ["tool:Bash"], {"source": "y", "useful": {"yes": 8, "no": 2, "n": 15, "ok": 13, "expected": 10}},
                     reason="T", instance="b")
    monkeypatch.setattr(content, "_progress", lambda: {"gruppe": {a.id: 21, b.id: 21, "gespraech:x": 21}})
    _model({"content:21": -0.72, "tool:a": 0.3, "tool:b": 0.2})
    r = weight_audit.audit()
    f = [x for x in r["befunde"] if x["merkmal"] == "content:21"]
    assert len(f) == 1 and f[0]["klasse"] == "contradicts" and "2 rated hints measured +23 points over 30 showings" in f[0]["grund"]


def test_contradiction_uses_the_models_whole_view_of_the_hint(gd, monkeypatch):
    """0.70.1 (seen live 18.11.2026): the audit compared the hint's own weight alone (+1.41) with its measurement (−8 points) and called
    it a contradiction, although the router's view of the hint — own weight + its meaning group + age + hint_n — was negative. The
    finding must come from what the router computes for the hint, averaged over the showings that were measured."""
    from vi_mcp import content
    h = g.new_object("insight", "web7 needs rpm -qa", ["host:web7"], {"source": "x", "useful": {"yes": 5, "no": 20, "n": 36, "ok": 20, "expected": 23}},
                     reason="T", instance="b")  # measured −8 points
    monkeypatch.setattr(content, "group", lambda hid: 19 if hid == h.id else None)
    for i in range(3):  # three stored showings, as data.before of experiences
        g.new_object("experience", f"Bash {i}", ["tool:Bash", "host:web7", "ok:no"],
                     {"before": {"shown": [h.id], "triggers": ["tool:Bash", "host:web7"], "router": "modell"}}, reason="T", instance="b")
    _model({f"hint:{h.id}": 1.41, "content:19": -0.98, "hint_n:1": -0.134, "tool:a": 0.3, "tool:b": 0.2, "tool:c": 0.2})
    r = weight_audit.audit()
    assert not [f for f in r["befunde"] if f["klasse"] == "contradicts"], r
    view, n = weight_audit.model_view(g.load(learning.model_id(None)), h.id)
    assert n == 3 and abs(view - (1.41 - 0.98 - 0.134)) < 1e-9  # the router's own arithmetic, over the three showings


def test_contradiction_names_the_view_and_the_own_weight(gd):
    h = g.new_object("insight", "web1 braucht Proxy", ["host:web1"], {"source": "x", "useful": {"yes": 2, "no": 20, "n": 30, "ok": 6, "expected": 15}},
                     reason="T", instance="b")
    _model({f"hint:{h.id}": 1.2, "tool:a": 0.3, "tool:b": 0.2, "tool:c": 0.2, "tool:d": 0.1})
    f = [x for x in weight_audit.audit()["befunde"] if x["klasse"] == "contradicts"]
    assert len(f) == 1 and "model view +1.20" in f[0]["grund"] and "now, no stored showing" in f[0]["grund"] and "own weight +1.20" in f[0]["grund"]

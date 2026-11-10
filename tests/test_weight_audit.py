"""0.29.0: weight audit — fixed rules read the router weights and name what looks wrong; nothing is changed."""
from vi_mcp import learning, sleep_cycle, tools, weight_audit
from vi_mcp import memory as g


def _model(weights):
    return g.new_object("modell", "Testmodell", ["modell:router"], {"zustand": "aktiv", "gewichte": weights, "achsenabschnitt": 0.0},
                        oid=learning.MODEL, reason="T", instance=g.SERVER_INSTANCE)


def test_no_model_is_a_named_state(gd):
    r = weight_audit.audit()
    assert r["zustand"] == "kein_modell" and "no trained router weights" in weight_audit.line(r)


def test_clean_weights_are_ok(gd):
    _model({"tool:a": 0.4, "tool:b": -0.3, "skill:c": 0.35, "host:d": 0.3, "thema:e": -0.25, "stunde:03": 0.01})
    r = weight_audit.audit()
    assert r["zustand"] == "ok" and r["befunde"] == [] and "none of dominant, contradicts, network, hour" in weight_audit.line(r)


def test_each_class_is_found(gd):
    good = g.new_object("erkenntnis", "web1 braucht Proxy", ["host:web1"], {"quelle": "x", "nuetzlich": {"ja": 2, "nein": 20, "n": 30, "ok": 6, "erwartet": 15}},
                        reason="T", instance="b")  # measured: −30 points
    net = g.new_object("erkenntnis", "aus dem Netz", ["host:web2", "herkunft:p2p", "herausgeber:peer1"], {"quelle": "y"}, reason="T", instance="p2p")
    m = _model({f"hinweis:{good.id}": 1.2, f"hinweis:{net.id}": 0.8, "stunde:14": -5.0, "tool:a": 0.3, "tool:b": 0.2, "tool:c": 0.2, "tool:d": 0.1})
    r = weight_audit.audit()
    assert r["je_klasse"] == {"dominant": 1, "contradicts": 1, "network": 1, "hour": 1}
    by = {f["klasse"]: f for f in r["befunde"]}
    assert by["dominant"]["merkmal"] == "stunde:14" and by["contradicts"]["merkmal"] == f"hinweis:{good.id}"
    assert "-30 points over 30 showings" in by["contradicts"]["grund"] and "peer1" in by["network"]["grund"]
    assert g.load(learning.MODEL).data["gewichte"] == m.data["gewichte"] and g.load(good.id).mode == "aktiv"  # read only
    assert "Weight audit: dominant 1" in tools.call_tool("vi_modell", {}, "a", True)


def test_sleep_runs_the_audit_after_learning(gd):
    rep = sleep_cycle.run("Test").data["schritte"]
    assert "8b_gewichte_pruefen" in rep and rep["8b_gewichte_pruefen"]["zustand"] in ("kein_modell", "ok", "befunde")


def test_group_weight_against_measured_hints(gd, monkeypatch):
    """0.30.0: a meaning-group weight that pushes down hints which are measured as good is a contradiction, too."""
    from vi_mcp import content
    a = g.new_object("erkenntnis", "nginx -t vor reload", ["tool:Bash"], {"quelle": "x", "nuetzlich": {"ja": 9, "nein": 1, "n": 15, "ok": 14, "erwartet": 10}},
                     reason="T", instance="b")
    b = g.new_object("regel", "certbot dry-run", ["tool:Bash"], {"quelle": "y", "nuetzlich": {"ja": 8, "nein": 2, "n": 15, "ok": 13, "erwartet": 10}},
                     reason="T", instance="b")
    monkeypatch.setattr(content, "_progress", lambda: {"gruppe": {a.id: 21, b.id: 21, "gespraech:x": 21}})
    _model({"inhalt:21": -0.72, "tool:a": 0.3, "tool:b": 0.2})
    r = weight_audit.audit()
    f = [x for x in r["befunde"] if x["merkmal"] == "inhalt:21"]
    assert len(f) == 1 and f[0]["klasse"] == "contradicts" and "2 rated hints measured +23 points over 30 showings" in f[0]["grund"]

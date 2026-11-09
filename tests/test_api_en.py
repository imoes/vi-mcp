"""0.22.0: Öffentliche Schnittstelle englisch — deutsche Werkzeug-, Parameter- und Wertnamen bleiben als Aliase gültig."""
from vi_mcp import api_en, werkzeuge
from vi_mcp import gedaechtnis as g


def test_jedes_werkzeug_hat_eine_vollstaendige_englische_form():
    namen = [t["name"] for t in werkzeuge.liste()]
    assert len(namen) == len(set(namen)) and all(n.startswith("vi_") for n in namen)
    for t in werkzeuge.TOOLS:
        assert t["name"] in api_en.TOOL_EN and t["name"] in api_en.DESC_EN, t["name"]
        en = api_en.schema(t)
        assert not any(c in en["description"] for c in "äöüß"), en["name"]  # Beschreibung englisch
        for k, v in t["inputSchema"].get("properties", {}).items():
            if isinstance(v, dict) and "enum" in v:
                assert k in api_en.ENUM_EN and all(x in api_en.ENUM_EN[k] for x in v["enum"]), (t["name"], k)
        assert set(en["inputSchema"].get("required", [])) <= set(en["inputSchema"]["properties"])


def test_englisch_und_deutsch_rufen_dasselbe(gd):
    aus = werkzeuge.rufe("vi_learn", {"text": "nginx auf web1 nur nach nginx -t neu laden", "hashtags": ["host:web1"],
                                      "source": "Betriebsregel 09.11.", "visibility": "internal", "outcome": "good"}, "a", True)
    oid = aus.split()[1]
    o = g.lade(oid)
    assert o.sicht == "intern" and o.daten["quelle"] == "Betriebsregel 09.11." and o.daten.get("ausgang") == "gut"
    alt = werkzeuge.rufe("vi_erinnere", {"filter": "nginx"}, "a", True)
    neu = werkzeuge.rufe("vi_recall", {"filter": "nginx"}, "a", True)
    assert oid in alt and oid in neu
    assert werkzeuge.bekannt("vi_recall") and werkzeuge.bekannt("vi_erinnere") and not werkzeuge.bekannt("vi_gibtsnicht")

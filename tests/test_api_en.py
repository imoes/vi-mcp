"""0.22.0: Öffentliche Schnittstelle englisch — deutsche Werkzeug-, Parameter- und Wertnamen bleiben als Aliase gültig."""
from vi_mcp import api_en, tools
from vi_mcp import memory as g


def test_every_tool_has_a_complete_english_form():
    names = [t["name"] for t in tools.listing()]
    assert len(names) == len(set(names)) and all(n.startswith("vi_") for n in names)
    assert set(api_en.TOOL_ALIASES.values()) <= set(names)  # every German alias points to an existing tool
    for t in tools.TOOLS:
        assert t["name"] not in api_en.TOOL_ALIASES, t["name"]  # the table itself is English
        assert not any(c in t["description"] for c in "äöüß"), t["name"]
        props = t["inputSchema"].get("properties", {})
        assert not set(props) & set(api_en.PARAM_ALIASES), (t["name"], set(props) & set(api_en.PARAM_ALIASES))
        for k, v in props.items():
            if isinstance(v, dict) and "enum" in v:
                assert k in api_en.STORED_VALUES and all(x in api_en.STORED_VALUES[k] for x in v["enum"]), (t["name"], k)
        assert set(t["inputSchema"].get("required", [])) <= set(props)


def test_german_aliases_map_to_existing_parameters():
    params = {k for t in tools.TOOLS for k in t["inputSchema"].get("properties", {})}
    assert set(api_en.PARAM_ALIASES.values()) <= params


def test_english_and_german_call_the_same(gd):
    outputs = tools.call_tool("vi_learn", {"text": "nginx auf web1 nur nach nginx -t neu laden", "hashtags": ["host:web1"],
                                      "source": "Betriebsregel 09.11.", "visibility": "internal", "outcome": "good"}, "a", True)
    oid = outputs.split()[1]
    o = g.load(oid)
    assert o.visibility == "intern" and o.data["quelle"] == "Betriebsregel 09.11." and o.data.get("ausgang") == "gut"
    old = tools.call_tool("vi_erinnere", {"filter": "nginx"}, "a", True)
    new = tools.call_tool("vi_recall", {"filter": "nginx"}, "a", True)
    assert oid in old and oid in new
    assert tools.known("vi_recall") and tools.known("vi_erinnere") and not tools.known("vi_gibtsnicht")

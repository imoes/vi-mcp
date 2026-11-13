"""0.62.0: the incubator — a VI matures in operation until measured criteria say it is ready to fine-tune an AI."""
import json

import pytest

from vi_mcp import evaluation, incubator, tools
from vi_mcp import memory as g


def _k(i, rated=False, **kw):
    return g.new_object("erkenntnis", f"knowledge number {i} about deploying", ["thema:deploy"],
                        {"quelle": "t", "inhalt": f"content {i}", **({"nuetzlich": {"ja": 3, "nein": 1, "n": 4}} if rated else {})},
                        visibility="intern", instance="a", **kw)


def test_a_new_vi_is_in_the_incubator_and_names_what_is_open_and_unmeasured(gd, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    for i in range(5):
        _k(i, rated=i < 2)
    st = incubator.status()
    by = {c["kriterium"]: c for c in st["kriterien"]}
    assert st["zustand"] == "im_inkubator" and "knowledge" in st["offen"]
    assert by["knowledge"]["wert"] == 5 and by["checked"]["wert"] == 0.4 and by["checked"]["zustand"] == "erfuellt"
    assert by["search"]["zustand"] == "nicht_gemessen" and by["router"]["zustand"] == "nicht_gemessen"
    assert by["hints_no_harm"]["zustand"] == "nicht_gemessen"  # never counted as met
    assert "no fixed question set yet" in by["training_data"]["hinweis"]
    text = "\n".join(incubator.lines(st))
    assert "in the incubator, open:" in text and "? search" in text
    assert "in the incubator" in tools.call_tool("vi_incubator", {}, "a", False)


def test_thresholds_from_config_measured_search_and_hatching(gd, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(incubator, "_cfg", lambda: {**incubator.DEFAULTS, "min_knowledge": 3, "min_examples": 2})
    for i in range(4):
        _k(i, rated=True)
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "verlauf.jsonl").write_text(json.dumps({"zeit": "2026-11-13T05:00", "suche": {"hybrid": {"gesamt": {"mrr": 0.73}}}}) + "\n")
    by = {c["kriterium"]: c for c in incubator.status()["kriterien"]}
    assert by["knowledge"]["zustand"] == "erfuellt" and by["search"] == {**by["search"], "zustand": "erfuellt", "wert": 0.73}
    with pytest.raises(ValueError, match="still in the incubator — open:"):
        incubator.hatch(str(tmp_path / "out"))
    m = incubator.hatch(str(tmp_path / "out"), force=True)  # forced: the datasheet names what was open
    assert m["inkubator"]["zustand"] == "im_inkubator" and m["inkubator"]["offen"]
    assert "## Incubator\nState when hatched: im_inkubator — open criteria:" in (tmp_path / "out" / "DATASHEET.md").read_text()
    assert json.loads((tmp_path / "out" / "manifest.json").read_text())["inkubator"]["offen"] == m["inkubator"]["offen"]

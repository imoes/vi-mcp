"""0.53.1: what failed on production (11.11.2026) — and the deploy scripts that left vi-mcp stopped after the update to 0.53.0.

One automatic skill collected 221 versions in one conversation (one per recovery), its data passed 400,000 characters and was replaced by a
size stub; sleep then failed on it (KeyError 'problem') six times. And nach-installation.sh restarted vi-mcp only if config.json had the key
"instanzen" — English since 0.51.0."""
import json
from pathlib import Path

import pytest

from vi_mcp import memory as g
from vi_mcp import skills, sleep_cycle, tools

ROOT = Path(__file__).resolve().parent.parent


def _skill():
    return skills.new("auto-test", ["tool:t_x", "fehler:boom"], ["t_x", "t_y"], "t_x failed and then succeeded — solution path: t_x → t_y",
                      "sleep: recovery in conversation 1", ["erfahrung:a"], "a")


def test_the_same_recovery_again_is_evidence_not_a_new_version(gd):
    o = _skill()
    for i in range(5):
        o = skills.new("auto-test", ["tool:t_x", "fehler:boom"], ["t_x", "t_y"], "t_x failed and then succeeded — solution path: t_x → t_y",
                       "sleep: recovery in conversation 1", [f"erfahrung:b{i}"], "a")
    o = g.load(o.id)
    assert o.data["version"] == 1 and o.data["bestaetigt_ohne_aenderung"] == 5 and "erfahrung:b4" in o.data["belege"]
    o = skills.new("auto-test", ["tool:t_x", "fehler:boom"], ["t_x", "t_y"], "t_x failed and then succeeded — solution path: t_x → t_y",
                   "sleep: recovery in conversation 2", ["erfahrung:c"], "a")
    assert g.load(o.id).data["version"] == 2  # another conversation is an independent line: a version


def test_versions_are_capped_first_and_newest_kept(gd):
    o = _skill()
    for i in range(skills.VERSIONS_MAX + 7):
        o = skills.evolve(g.load(o.id), [f"t_s{i}"], "", f"step {i}", [], "a")
    o = g.load(o.id)
    assert len(o.data["versionen"]) == skills.VERSIONS_MAX and o.data["versionen"][0]["version"] == 1
    assert o.data["versionen"][-1]["version"] == o.data["version"] and o.data["versionen_gekuerzt"] == 8


def test_oversized_data_loses_old_history_not_its_structure(gd, monkeypatch):
    monkeypatch.setattr(g, "DATA_MAX", 20_000)
    o = _skill()
    o.data["versionen"] += [{"version": i, "grund": "x" * 500} for i in range(2, 80)]
    g.save(o)
    o = g.load(o.id)
    assert skills.usable(o) and o.data["gekuerzt"]["versionen"] > 0 and len(json.dumps(o.data)) <= 20_000


def test_a_damaged_skill_is_skipped_and_named(gd):
    d = g.new_object("skill", "damaged", ["tool:t_x", "skill:auto-kaputt"], {"gekuerzt_zeichen": 401721, "grund": "daten over 400000 chars"},
                     instance="vi", oid="skill:auto-kaputt")
    assert not skills.usable(d)
    assert skills.fusion_proposals() == {"vorschlaege": 0}
    with pytest.raises(tools.Rejected, match="damaged"):
        tools.call_tool("vi_skill", {"id": d.id}, "a", True)
    with pytest.raises(ValueError, match="damaged"):
        skills.evolve(d, ["t_y"], "something new", "reason", [], "a")
    assert "4c_skills" not in "".join(sleep_cycle.run("Test").data.get("fehler") or [])


def test_deploy_scripts_read_both_key_names_and_start_the_memory_first():
    nach = (ROOT / "deploy/nach-installation.sh").read_text()
    system = nach[nach.index("systemctl daemon-reload"):nach.index("\nwiki)")]  # the part of "system)" that (re)starts the services
    assert "c.get('instances') or c.get('instanzen')" in system
    assert system.index("systemctl restart vi-mcp.service") < system.index("systemctl restart vi-p2p.service")  # the memory first
    assert "/gesund" in system  # and waited for
    assert "c.get('instances') or c.get('instanzen')" in (ROOT / "deploy/install.sh").read_text()
    assert "$raw.instances -or $raw.instanzen" in (ROOT / "deploy/windows/install.ps1").read_text()
    assert " db " in (ROOT / "deploy/debian/postinst").read_text()  # 0.50.0's question db is read from debconf too

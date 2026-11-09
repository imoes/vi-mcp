"""0.4.0: Selbst, Schlaf (Konsolidierung), Archiv, Potenzgesetz-Verfall."""
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import intuition, sleep_cycle, self_model, session, tools
from vi_mcp import memory as g


def _age(oid: str, days: float) -> None:
    z = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ?, zuletzt = ? WHERE id = ?", (z, z, oid))
        g.db().commit()


_n = iter(range(10_000))


def _experience(tool, host, ok, instance="a", error=None):
    """Eine echte Handlung je Aufruf: eindeutige Argumente, sonst beantwortet der Antwort-Cache ab dem 2. Mal
    aus dem Gedächtnis und zählt eine zweite Erfahrung (gewollt in der VI, hier nicht gewollt)."""
    args = {"host": host, "n": next(_n)}
    v = intuition.before(tool, args, instance)
    return intuition.after(tool, args, ok, 1, error, "ok" if ok else None, v["vorher_id"], instance)["erfahrung"]


def test_self_core_and_narrative(gd):
    k = self_model.core()
    assert k.id == self_model.CORE and k.data["version"] == 1 and k.instance == g.SERVER_INSTANCE and k.visibility == "geteilt"
    assert "Selbst v1" in k.data["erzaehlung"] and "Grenzen:" in k.data["erzaehlung"]
    assert len(k.data["erzaehlung"].split()) <= 151
    assert self_model.core().id == k.id  # idempotent
    assert len(self_model.versions()) == sum(len(v) for v in self_model.DEFAULT_TARGET.values())


def test_self_proposal_needs_evidence_and_foreign_trusted_instance(gd):
    a, b, c = session.begin("a", "t"), session.begin("b", "t"), session.begin("c", "t")
    evidence_list = []
    for i in range(3):
        o = g.new_object("erkenntnis", f"Beleg {i} für Vorsicht bei Nachtarbeit", ["thema:nacht"], {"quelle": "x"}, reason="T")
        evidence_list.append(o.id)
    with session.on_behalf(a):
        with pytest.raises(tools.Rejected, match="mindestens 3 Belege"):
            tools.call_tool("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": evidence_list[:2]}, "a", True)
        with pytest.raises(tools.Rejected, match="verschiedenen Tagen"):
            tools.call_tool("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": evidence_list}, "a", True)
    _age(evidence_list[0], 2)
    with session.on_behalf(a):
        r = tools.call_tool("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": evidence_list}, "a", True)
    vid = r.split()[1]
    assert g.load(vid).mode == "test" and self_model.core().data["version"] == 1
    with session.on_behalf(a), pytest.raises(tools.Rejected, match="Selbstbestätigung"):
        tools.call_tool("vi_bestaetige", {"id": vid, "grund": "ich selbst"}, "a", True)
    with session.on_behalf(b), pytest.raises(tools.Rejected, match="nicht vertraut"):
        tools.call_tool("vi_bestaetige", {"id": vid, "grund": "finde ich gut"}, "b", False)
    with session.on_behalf(c):
        r = tools.call_tool("vi_bestaetige", {"id": vid, "grund": "vom Menschen freigegeben"}, "c", True)
    assert "Version 2" in r
    k = self_model.core()
    assert k.data["version"] == 2 and any("Nachts keine" in s["satz"] for s in k.data["soll"]["werte"])
    assert "Nachts keine" in k.data["erzaehlung"] and g.load(vid).mode == "aktiv"
    assert self_model.versions()[0][3] == "werte" and "vom Menschen freigegeben" in self_model.versions()[0][5]
    assert "Version 2" in tools.call_tool("vi_selbst", {"versionen": True}, "a", True)


def test_self_in_initialize_and_repetition(gd):
    s = session.begin("a", "t")
    with session.on_behalf(s):
        for i in range(self_model.REPEAT_PER - 1):
            assert not any(h.startswith("[Selbst]") for h in intuition.before("Bash", {"i": i}, "a", False)["hinweise"])
        assert any(h.startswith("[Selbst]") for h in intuition.before("Bash", {}, "a", False)["hinweise"])
    assert self_model.hint().startswith("[Selbst] Ich bin die VI")


def test_decay_power_law(gd):
    o = g.new_object("erkenntnis", "alt aber wichtig", ["thema:v"], {"quelle": "x"}, reason="T")
    assert g.recall("thema:v", viewer=None)[0][2]["aktualitaet"] == 1.0
    _age(o.id, 30)
    a30 = g.recall("thema:v", viewer=None)[0][2]["aktualitaet"]
    assert 0.12 < a30 < 0.16  # (1+720)^-0.3 ≈ 0.139; exponentiell wären es 0,03
    _age(o.id, 365)
    assert g.recall("thema:v", viewer=None)[0][2]["aktualitaet"] > 0.06


def test_sleep_abstraction_schema_conflict_and_report(gd):
    # Cluster (host:web5, skill:checkmk): 4 Handlungen an 2 Tagen, alle ok → Erkenntnis (test) mit Belegkanten
    ids = [_experience("checkmk_get_host", "web5", True) for _ in range(4)]
    _age(ids[0], 1); _age(ids[1], 1)
    assert sleep_cycle.due(datetime(2026, 11, 9, 3, 5, tzinfo=timezone.utc)) == "Nachtlauf 03:00 UTC (kein Schlaf in 24 h)"
    assert sleep_cycle.due(datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)) is None  # Wichtigkeit 0, keine Nacht
    b = sleep_cycle.run("Test")
    assert b.kind == "schlaf" and "zustand:fertig" in b.hashtags and b.data["schritte"]["4_abstraktion"] == 1
    e = [o for _, o, _g in g.recall("herkunft:schlaf", viewer=None)][0]
    assert e.mode == "test" and e.data["ausgang"] == "gut" and "web5" in e.text and len(e.edges()) == 4
    assert b.text.startswith("Schlaf fertig") and sleep_cycle.last().id == b.id
    # zweiter Lauf, derselbe Cluster mit gegenteiligem Ausgang → Konflikt, keine stille Änderung
    for _ in range(3):
        _experience("checkmk_get_host", "web5", False, error="Timeout: 30 s")
    b2 = sleep_cycle.run("Test 2")
    assert b2.data["schritte"]["3_schema"]["konflikte"] == 1 and b2.data["schritte"]["4_abstraktion"] == 0
    e = g.load(e.id)
    assert "konflikt:offen" in e.hashtags and e.mode == "test" and e.data["konflikte"][0]["ausgang"] == "schlecht"
    # Schlaf-Bestätigung zählt nicht als fremde Instanz
    assert e.foreign_confirmations() == 0
    assert "Schlaf fertig" in tools.call_tool("vi_status", {}, "a", True)
    assert "Konflikte" in tools.call_tool("vi_schlaf", {}, "a", True)
    with pytest.raises(tools.Rejected, match="nicht vertraut"):
        tools.call_tool("vi_schlaf", {"jetzt": True}, "b", False)


def test_sleep_self_actual(gd):
    for i in range(5):
        _experience("netbox_get_vms", "h9", i < 4)
    sleep_cycle.run("Test")
    actual = self_model.core().data["ist"]
    assert actual["kompetenz"][0] == {"bereich": "skill:netbox", "erfahrungen": 5, "erfolgsquote": 0.8, "zeitraum": "30 d"}
    assert "Erfahren in: skill:netbox (5 Handlungen, 80 % ok, 30 d)" in self_model.core().data["erzaehlung"]


def test_night_run_only_after_24_h_without_sleep(gd):
    """0.20.3: Ein Schlaf am selben Kalendertag (00:28) ließ den Nachtlauf still ausfallen; jetzt ist der Nachtlauf Sicherheitsnetz für ruhige Tage."""
    b = sleep_cycle.run("Wichtigkeit")
    now = datetime.fromisoformat(b.ts)
    at_three = now.replace(hour=3, minute=5) if now.hour >= 3 else now.replace(hour=3, minute=5)
    assert sleep_cycle.due(at_three + timedelta(days=0 if at_three > now else 1)) is None  # Schlaf liegt < 24 h zurück
    assert sleep_cycle.due(at_three + timedelta(days=2)).startswith("Nachtlauf")       # > 24 h ohne Schlaf



def test_sleep_at_most_every_two_hours(gd):
    """0.21.1: 45 Schläfe in 24 h mit zusammen 3 neuen Erkenntnissen — Schwelle 80 und Mindestabstand 120 min."""
    from datetime import datetime, timedelta, timezone
    for i in range(30):
        g.new_object("erfahrung", f"Handlung {i}", ["tool:x"], {}, importance=3, reason="T")
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    assert sleep_cycle.due(now) is not None  # 90 ≥ 80, noch nie geschlafen
    g.new_object("schlaf", "Schlaf fertig", ["zustand:fertig"], {}, reason="T")
    assert sleep_cycle.due(now) is None  # gerade geschlafen

"""German aliases of the MCP interface (English since 0.22.0).

Tool names, parameter names and descriptions are English in `tools.TOOLS`. Clients registered before 0.22.0 (hook, bridges,
other people's setups) still call the German names — this module translates them on the way in:
- `canonical_name`: German tool name → English name; English and unknown names pass through.
- `canonical_args`: German parameter names → English names; English enum values → the stored value.

Enum values are stored data (database, hashtags, network format) and stay German there, e.g. visibility "shared" is stored as
"geteilt". German values are accepted as they are.
"""
from __future__ import annotations

#: German tool name → English tool name
TOOL_ALIASES: dict[str, str] = {
    "vi_vorher": "vi_before", "vi_nachher": "vi_after", "vi_frage": "vi_ask", "vi_antwort": "vi_answer", "vi_fragen": "vi_questions",
    "vi_selbst": "vi_self", "vi_selbst_vorschlag": "vi_self_propose", "vi_schlaf": "vi_sleep", "vi_lager": "vi_archive",
    "vi_lager_hole": "vi_archive_restore", "vi_modell": "vi_model", "vi_geloest": "vi_solved", "vi_skill_fusion": "vi_skill_merge",
    "vi_netz_ausgang": "vi_net_outbox", "vi_netz_eingang": "vi_net_inbox", "vi_netz_status": "vi_net_status",
    "vi_quarantaene": "vi_quarantine", "vi_freigabe": "vi_release", "vi_netz_token": "vi_net_token", "vi_netz_vergiss": "vi_net_forget",
    "vi_netz_vorschau": "vi_net_preview", "vi_lerne": "vi_learn", "vi_statistik": "vi_stats", "vi_erinnere": "vi_recall",
    "vi_objekt": "vi_object", "vi_markiere": "vi_tag", "vi_bestaetige": "vi_confirm", "vi_widerlege": "vi_refute", "vi_vergiss": "vi_forget",
    "vi_erfahrung": "vi_experience", "vi_loesche_gespraech": "vi_delete_conversation", "vi_gespraech": "vi_conversation",
    "vi_suche_lerne": "vi_learn_search", "vi_vertiefe": "vi_drilldown", "vi_reflex_lerne": "vi_reflex_learn",
    "vi_reflex_liste": "vi_reflex_list", "vi_reflex_schalte": "vi_reflex_switch",
}

#: German parameter name → English parameter name (names that are the same in both languages are not listed)
PARAM_ALIASES: dict[str, str] = {
    "aktion": "action", "alle": "all", "an": "to", "anleitung": "instructions", "art": "kind", "ausgang": "outcome", "belege": "evidence",
    "bereich": "area", "beschreibung": "description", "dauer_ms": "duration_ms", "eintraege": "entries", "ergebnis": "result", "fehler": "error",
    "geschichte": "story", "grund": "reason", "hinzu": "add", "inhalt": "content", "jetzt": "now", "kontext_hashtags": "context_hashtags",
    "lesend": "read_only", "modus": "mode", "netz": "network", "projekt": "project", "stand": "state", "quelle": "source", "reize": "triggers", "satz": "sentence", "schritte": "steps", "semantisch": "semantic",
    "sicht": "visibility", "stufen": "levels", "stunden": "hours", "suche": "search", "tage": "days", "versionen": "versions",
    "vorher_id": "before_id", "weg": "remove", "wichtigkeit": "importance",
}

#: English parameter → {English enum value: stored value}. The tool schemas show the English values.
STORED_VALUES: dict[str, dict[str, str]] = {
    "area": {"values": "werte", "goals": "ziele", "style": "stil", "limits": "grenzen"},
    "action": {"approve": "freigeben", "discard": "verwerfen", "state": "state", "sync": "sync",
               "plan": "plan", "guide": "guide", "record": "record",  # 0.62.0: vi_finetune — not stored, the same in both languages
               "check": "check", "ask": "ask", "rate": "rate", "save": "save", "objects": "objects"},  # 0.62.0: vi_logic, likewise (objects 0.63.0)
    "visibility": {"shared": "geteilt", "internal": "intern", "private": "privat"},
    "outcome": {"good": "gut", "bad": "schlecht"},
    "format": {"text": "text", "vil": "vil"},  # 0.62.0: vi_recall answer format — not stored, the same in both languages
    "kind": {"tool": "werkzeug", "before": "vorher", "after": "nachher", "projekt": "projekt", "spezial": "spezial"},
    "mode": {"test": "test", "active": "aktiv", "off": "aus"},
}


def canonical_name(name: str) -> str:
    """German alias → English tool name; English and unknown names (e.g. vi_reflex_<name>) pass through unchanged."""
    return TOOL_ALIASES.get(name, name)


def canonical_args(args: dict) -> dict:
    """German parameter names → English; English enum values → stored values. German values pass through unchanged."""
    out = {}
    for k, v in (args or {}).items():
        k = PARAM_ALIASES.get(k, k)
        if isinstance(v, str) and k in STORED_VALUES:
            v = STORED_VALUES[k].get(v, v)
        out[k] = v
    return out

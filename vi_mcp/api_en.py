"""German aliases of the MCP interface (English since 0.22.0).

Tool names, parameter names and descriptions are English in `tools.TOOLS`. Clients registered before 0.22.0 (hook, bridges,
other people's setups) still call the German names — this module translates them on the way in:
- `canonical_name`: German tool name → English name; English and unknown names pass through.
- `canonical_args`: German parameter names → English names; English enum values → the stored value.

Enum values: since 0.67.0 the stored values are English too (vi_mcp/names.py); a German value of an older client is read as its
English form here (visibility "geteilt" → "shared"). Values that are still stored German (reflex kinds) are mapped the other way.
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

#: English parameter → {accepted value: stored value}. The tool schemas show the English values; German values of older clients map to the
#: same stored value (0.67.0: stored values are English, except the reflex kinds werkzeug/vorher/nachher until their data step).
STORED_VALUES: dict[str, dict[str, str]] = {
    "knowledge_kind": {"company-docs": "company-docs", "external-docs": "external-docs", "manual": "manual"},  # 0.69.0 vi_doc_sync
    "answers": {v: v for v in ("how", "why", "what", "who", "where", "rule")},  # 0.69.3 vi_qualify
    "certainty": {v: v for v in ("low", "medium", "high")},  # 0.69.3 vi_rate
    "memory": {v: v for v in ("fact", "procedure", "episode", "rule")},
    "area": {"values": "values", "goals": "goals", "style": "style", "limits": "limits",
             "werte": "values", "ziele": "goals", "stil": "style", "grenzen": "limits"},
    "action": {"approve": "freigeben", "discard": "verwerfen", "state": "state", "sync": "sync",
               "create": "create", "status": "status", "execute": "execute", "snapshot": "snapshot", "restore": "restore",
               "fork": "fork", "teach": "teach", "import": "import", "verify": "verify",
               "inspect": "inspect", "configure": "configure", "context": "context", "loop": "loop", "device": "device", "observe": "observe",
               "plan": "plan", "guide": "guide", "record": "record", "skill": "skill", "card": "card",  # 0.62.0: vi_finetune (skill: 0.68.0) — not stored, the same in both languages
               "check": "check", "ask": "ask", "rate": "rate", "save": "save", "objects": "objects", "propose": "propose", "learn": "learn", "answer": "answer",
               "list": "list", "show": "show", "evaluate": "evaluate", "install": "install", "use": "use", "bound": "bound", "explain": "explain", "export": "export", "suggest": "suggest", "kit": "kit"},  # 0.66.0: vi_philosophy, likewise  # 0.62.0: vi_logic, likewise (objects 0.63.0)
    "visibility": {"shared": "shared", "internal": "internal", "private": "private", "geteilt": "shared", "intern": "internal", "privat": "private"},
    "outcome": {"good": "gut", "bad": "schlecht"},
    "format": {"text": "text", "vil": "vil"},  # 0.62.0: vi_recall answer format — not stored, the same in both languages
    "kind": {"tool": "werkzeug", "before": "vorher", "after": "nachher", "project": "project", "special": "special",
             "projekt": "project", "spezial": "special"},
    "mode": {"test": "test", "active": "active", "off": "off", "aktiv": "active", "aus": "off"},
}


def canonical_name(name: str) -> str:
    """German alias → English tool name; English and unknown names (e.g. vi_reflex_<name>) pass through unchanged."""
    return TOOL_ALIASES.get(name, name)


def canonical_args(args: dict) -> dict:
    """German parameter names → English; enum values → their stored form (STORED_VALUES)."""
    out = {}
    for k, v in (args or {}).items():
        k = PARAM_ALIASES.get(k, k)
        if isinstance(v, str) and k in STORED_VALUES:
            v = STORED_VALUES[k].get(v, v)
        out[k] = v
    return out

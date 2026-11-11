"""0.53.0 (proposed by a Claude Code session after a day next to the right manuals, approved by the user, 11.11.2026):
A — after a failed action the memory searches for the tool and the error text itself (rule 3) and hands the best hits back with vi_after.
B — which skills exist, which system each serves, its tools and its manual: one table, at the first prompt of a session and via
vi_capabilities; the instructions index names it in one line."""
import json

from vi_mcp import capabilities, index, intuition, session, tools
from vi_mcp import memory as g


def _fail(tool, args, error, instance="a"):
    v = intuition.before(tool, args, instance, False)
    return intuition.after(tool, args, False, 5, error, None, v["vorher_id"], instance, False)["hinweise"]


# ---- A

def test_a_failed_action_brings_what_the_memory_knows_about_the_error(gd):
    k = g.new_object("erkenntnis", "jira_search answers 401 Unauthorized when the PAT expired — renew the token in the skill config",
                     ["tool:jira_search", "skill:jira", "fehler:http_401"], {"quelle": "test 11.11.2026"}, instance="b")
    g.new_object("erkenntnis", "Graylog streams are paused at night", ["skill:graylog"], {"quelle": "test"}, instance="b")
    hints = _fail("jira_search", {"jql": "project = X"}, "HTTP 401 Unauthorized: token expired")
    assert len(hints) == 1 and k.id in hints[0] and hints[0].startswith("After this error — known in the VI:")


def test_no_hint_without_a_real_match(gd):
    g.new_object("erkenntnis", "nginx reload needs a config test first", ["tool:Bash", "thema:nginx"], {"quelle": "test"}, instance="b")
    assert _fail("Bash", {"command": "uptime"}, "Exit 1: something unrelated broke") == []


def test_a_shell_error_matches_on_words_and_host_not_on_the_tool(gd):
    k = g.new_object("erkenntnis", "web1 refuses ssh without BatchMode: Permission denied (publickey) until the key file is given",
                     ["host:web1.example", "tool:Bash", "thema:ssh"], {"quelle": "test"}, instance="b")
    g.new_object("erkenntnis", "Bash heredocs need quoted EOF to avoid expansion", ["tool:Bash"], {"quelle": "test"}, instance="b")
    hints = _fail("Bash", {"command": "ssh web1.example uptime"}, "Permission denied (publickey).")
    assert len(hints) == 1 and k.id in hints[0]


def test_refuted_and_quarantined_knowledge_is_not_offered(gd):
    k = g.new_object("erkenntnis", "jira_search 401 Unauthorized means the PAT expired", ["tool:jira_search", "skill:jira"], {"quelle": "x"}, instance="b")
    k.mode = "widerlegt"
    g.save(k)
    assert _fail("jira_search", {}, "HTTP 401 Unauthorized") == []


def test_success_brings_no_error_hints(gd):
    g.new_object("erkenntnis", "jira_search 401 Unauthorized means the PAT expired", ["tool:jira_search", "skill:jira"], {"quelle": "x"}, instance="b")
    v = intuition.before("jira_search", {}, "a", False)
    assert intuition.after("jira_search", {}, True, 5, None, "ok", v["vorher_id"], "a", False)["hinweise"] == []


# ---- B

def _overview(doc, prefix, text, visibility=None):
    return g.new_object("erkenntnis", f"Vollständige Doku zu {doc}: vi_erinnere doku:{doc}. {text}", ["art-wissen:ueberblick", f"doku:{doc}", f"skill:{prefix}"],
                        {"quelle": "skills folder"}, instance="alice", visibility=visibility)


def test_table_joins_overviews_measured_tools_and_manual_tools(gd):
    ov = _overview("gitlab-api", "gitlab", "Verbindet sich mit GitLab und führt API-Aufrufe aus (Projekte, Pipelines, z.B. CI-Variablen).")
    g.new_object("erkenntnis", "[gitlab-api › MCP-Tools] gitlab_get_tree lists a directory, gitlab_get_file reads a file",
                 ["art_wissen:handbuch", "doku:gitlab-api"], {"quelle": "skills folder", "inhalt": "gitlab_get_tree(project, path) · gitlab_get_file(project, path)"},
                 instance="alice")
    for _ in range(3):
        g.new_object("erfahrung", "gitlab_list_projects run", ["tool:gitlab_list_projects", "ok:ja"], {}, instance="a")
    _overview("agents", "agents", "(Abschnitte: Skills Documentation, API Skills, Other Skills)")
    rows = {r["skill"]: r for r in capabilities.table("a")}
    assert rows["gitlab-api"]["id"] == ov.id and rows["gitlab-api"]["tools"][0] == "gitlab_list_projects"  # measured first
    assert {"gitlab_get_tree", "gitlab_get_file"} <= set(rows["gitlab-api"]["tools"])  # then what the manual names
    assert rows["agents"]["description"].startswith("sections: Skills Documentation")
    t = capabilities.text("a")
    assert t.startswith("[Skills] 2 skill manuals") and "No such tool available" in t and f"→ [{ov.id}]" in t


def test_table_respects_visibility(gd):
    _overview("intern-api", "intern", "Internal system.", visibility="intern")
    assert [r["skill"] for r in capabilities.table("a")] == ["intern-api"]
    assert capabilities.table("offen") == []  # the tokenless instance never sees internal manuals


def test_tool_and_index_line(gd):
    _overview("graylog-api", "graylog", "Verbindet sich mit Graylog.")
    assert "graylog-api" in tools.call_tool("vi_capabilities", {}, "a", True)
    assert "[Skills] 1 skill manuals (system, tools, manual id): vi_capabilities" in index.text("a")
    capabilities._cache.clear()
    for _, o, _g in g.recall("art-wissen:ueberblick", viewer=None):
        o.mode = "widerlegt"
        g.save(o)
    assert tools.call_tool("vi_capabilities", {}, "a", True).startswith("no skill manuals")

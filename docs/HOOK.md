# Claude Code hook: report every action to the VI

`hook/vi_hook.py` — one file, standard library only. Reporting path as decided by the user (08.11.2026):
**only** this hook reports; no tool server reports in addition (otherwise twice).

## What it does

| Claude Code event | Hook calls | Effect in the model |
|---|---|---|
| `PreToolUse` | `vi_before` | remembered answer → call **denied** (`permissionDecision: deny`), the answer is in the reason; otherwise hints as `additionalContext` |
| `PostToolUse` | `vi_after` (ok, result, duration) | after-reflex hints as `additionalContext` |
| `PostToolUseFailure` | `vi_after` (ok=false, `error`, `is_interrupt`) | — |
| `SessionEnd` | `DELETE /mcp` | conversation `beendet` (ended) |

- **One Claude session = one conversation** in vi-mcp (state in `~/.cache/vi-mcp/hook/sitzung/<session_id>.json`, 0600).
  Unknown session (server restarted) → the hook registers anew once.
- **Tool name**: `mcp__<server>__<tool>` → `<tool>` (so the triggers `tool:`/`skill:` are named like the tools themselves).
- **Never from memory**: built-in tools (Bash, Read, Edit, Grep, …) report `read_only: false` — files and
  system state change. Only MCP tools can get a remembered answer (and only read-only ones, by name pattern).
- **The memory's own tools** (`vi_*` on an MCP server) are not reported.
- **Data minimisation**: passwords, tokens and credentials in URLs are masked before sending. The result only goes to the
  server for MCP tools; built-in tools and tools for credentials only report the outcome. Arguments of
  built-in tools are truncated to 300 characters. Masking works with patterns and can miss secrets.
- **Outage**: vi-mcp not reachable, token missing, wrong answer → exit 0 without output, the call runs without
  memory; the reason is in `~/.cache/vi-mcp/hook/hook.log`. A hook error never holds up a session.

**Limit (docs):** A hook can allow or deny a call, but cannot replace it with a result.
A remembered answer therefore appears to the model as "denied, reason: …".

## The user's correction and grade (`UserPromptSubmit`)

The hook recognises locally whether an input is a correction (starts with "nein", "falsch", "das stimmt nicht", "no", "wrong" …) or contains a grade
(`#gut`, `#schlecht`, `#note 0.8`). **Only this result, never the text,** goes to the server (`POST /signal`).
This needs its own instance: `vi-mcp instance nutzer --human`, its token in `~/.config/vi-mcp/token-nutzer`
(or `VI_MCP_SIGNAL_TOKEN_FILE`). The session's token is not enough (403), and there is no MCP tool for setting a grade.

**Limit:** The token lies with the user. A model with shell access under the same account could read the file and call `/signal`
itself. The absence of the tool prevents accidental self-rating, not deliberate misuse.

## Evidence for the interface

Claude Code Hooks, https://code.claude.com/docs/en/hooks.md (read 08.11.2026, installed: 2.1.319):
common fields `session_id`, `cwd`, `hook_event_name`; PreToolUse `tool_name`, `tool_input`, `tool_use_id`;
`permissionDecision: "deny"` → `permissionDecisionReason` is shown to Claude; PostToolUse only after success,
`tool_response`, `additionalContext`; PostToolUseFailure `error`, `is_interrupt`, `duration_ms`; SessionEnd `reason`,
default budget 1.5 s (hence DELETE with a 1 s timeout); exit codes other than 0 and 2 are non-blocking.
**Not confirmed:** `additionalContext` for **PreToolUse** (confirmed only for PostToolUse) — if it is ignored,
only the before-hints are missing, nothing else.

## Registering

Prerequisite: vi-mcp is running and reachable. For a remote server set the environment (e.g. in the
`env` block of `~/.claude/settings.json`):
`VI_MCP_URL=https://<host>/vi-mcp/mcp`, `VI_MCP_TOKEN_FILE=~/.config/vi-mcp/token-anna-<host>`.
An HTTP proxy from the environment (`http_proxy`) also applies to the hook — the server's domain belongs in `no_proxy`.
In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse":         [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py", "timeout": 5}]}],
    "PostToolUse":        [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py", "timeout": 5}]}],
    "PostToolUseFailure": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py", "timeout": 5}]}],
    "SessionEnd":         [{"hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py"}]}]
  }
}
```

Cost: two HTTP requests to 127.0.0.1 per tool call (timeout 3 s; the duration should be measured after
installation, see CHANGELOG "What is still missing").

## Checking

`python3 -m pytest -q tests/test_hook.py` — 8 tests, most of them against a real vi-mcp server: tool name and read-only hint,
before/after, remembered answer across sessions, built-in tools never from memory, errors, hints, own tools,
session end, server restart, outage, masking and truncation, result only for MCP tools.

# Push: can vi-mcp tell a connected AI something on its own?

Design note, 19.11.2026. Status: **released in 0.70.4, off by default**; it delivers only after the precondition below. Sources are named after every claim; whatever
was not read from a primary source or measured is called a hypothesis.

## In short

- **Today everything is pull.** A question to an instance, an answer to its `vi_ask` and a released network question reach the AI at
  its next action through the hook (`vi_before`, `questions.deliver`) or the next prompt (`vi_prompt_context`), or when it calls
  `vi_questions`. A session that sits idle hears nothing until the user types.
- **The MCP specification has no general way to push into the model.** The newest revision, 2026-07-28, removed the HTTP GET stream,
  sessions and server-initiated requests. What the server may still send unasked goes over `subscriptions/listen`, and only the kinds
  of notification the client asked for. Sampling and logging are deprecated. Nothing in the specification says a notification reaches
  the model; that is up to the client.
- **Of the three clients we use, only Claude Code puts a server message into the conversation:** its *channels*
  (`notifications/claude/channel`), a research preview that a Team or Enterprise organisation must switch on.
- **Prototype:** `vi-mcp stdio --channel` pushes questions and answers as channel messages. It was measured end to end with Claude Code
  2.1.328 on a Team account. The bridge sent the message, Claude Code recognised the capability and then dropped the message because the
  organisation has not enabled channels. Nothing was lost: the push marks nothing, so the next `vi_before` still delivered it.

## Precondition: who switches channels on

Channel delivery works only after two steps that are **not vi-mcp's to take**:
1. **The organisation enables channels.** On a Team or Enterprise account an administrator sets `channelsEnabled: true` in the managed
   settings ([channels](https://code.claude.com/docs/en/channels)). Without it Claude Code drops every channel message silently.
2. **The session loads the server as a channel.** While custom channels are a research preview and vi-mcp is not on the approved
   allowlist, the user starts Claude Code with `--dangerously-load-development-channels server:<name of the vi-mcp server>`; the flag
   works in interactive sessions only.

vi-mcp adds `--channel` to `vi-mcp stdio` and does nothing else on its own: `vi-mcp setup` does not write the flag, and nothing in
vi-mcp changes a client's settings. Until both steps are done, and for every other client, **the hook stays the delivery route**: the
next `vi_before` or `vi_prompt_context` delivers what the channel would have pushed.

## 1. What the specification allows

Revision **2026-07-28** is current (https://modelcontextprotocol.io/specification/versioning: "The current protocol version is
2026-07-28"; read 19.11.2026). The previous revision is 2025-11-25. vi-mcp negotiates at most 2025-06-18 (`server.PROTOCOL_VERSIONS`).

| Mechanism | 2026-07-28 | 2025-11-25 and earlier |
|---|---|---|
| Server-initiated stream | "Removal of the GET stream endpoint." "Removal of protocol-level sessions." A server answers GET with 405 ([streamable-http](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)) | The client MAY open a GET SSE stream; the server MUST return `text/event-stream` or 405; resumable with `Last-Event-ID` ([transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)) |
| Unrelated notifications | Only on `subscriptions/listen`, which "replaces the former `resources/subscribe` RPC and the HTTP GET endpoint"; "The server MUST NOT send notification types the client has not explicitly requested." ([subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)) | On the GET stream |
| Notifications during a request | MAY, and they "MUST relate to the originating client request"; "MUST NOT send independent JSON-RPC requests on this stream" | MAY, SHOULD relate to the request |
| `notifications/resources/updated` | On the listen stream, for URIs in `resourceSubscriptions` | After `resources/subscribe` |
| `tools`/`prompts` `list_changed` | On the listen stream with `toolsListChanged` / `promptsListChanged` | Any time, capability `listChanged` |
| `notifications/progress` | Only for a `progressToken` of a request in flight ([progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress)) | The same |
| `notifications/message` (logging) | **Deprecated**; only on the response stream of a request that set `io.modelcontextprotocol/logLevel` ([logging](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/logging)) | After `logging/setLevel` |
| `sampling/createMessage` | **Deprecated** (SEP-2577); "The previous pattern of server-initiated requests is no longer supported" — only as an input request inside the result of `tools/call`, `prompts/get` or `resources/read` ([mrtr](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr), [sampling](https://modelcontextprotocol.io/specification/2026-07-28/client/sampling)) | Server request; "there SHOULD always be a human in the loop" |
| `elicitation/create` | Also only inside a request's result (MRTR); form or URL mode; never sensitive data in form mode | Server request |

So the summary "a server can push via resource subscriptions, progress and log messages, listChanged and sampling" is right only for the
older revisions and only partly: progress and logging are bound to a request in flight in every revision, and sampling is a request
to the client's model whose answer goes back to the server, not into the conversation.

## 2. What the clients do with it

Versions installed on the development machine on 19.11.2026. Sources: Claude Code from its documentation and the strings in its binary
(no source code available); Codex from its source at tag `rust-v0.169.0`; Hermes Agent from its source at v0.21.0. MODEL = reaches the
model's context; UI = shown to the user; LOG = written to a log; — = not supported or ignored.

| Message | Claude Code 2.1.328 | Codex CLI 0.169.0 | Hermes Agent 0.21.0 |
|---|---|---|---|
| GET SSE stream | opens it (2025 revisions) | opens it (`rmcp-client/src/http_client_adapter.rs`) | opens it (Python `mcp` SDK) |
| `tools/list_changed` | MODEL: tools re-fetched ([docs](https://code.claude.com/docs/en/mcp)) | LOG; MODEL only with the unfinished feature flag `mcp_tool_list_changed` | MODEL: tools re-registered |
| `prompts/list_changed` | UI (slash commands) | LOG | LOG |
| `resources/updated` | — (no subscribe) | LOG (no subscribe) | — |
| `notifications/message` | — (hypothesis: no handler found) | LOG | LOG |
| `notifications/progress` | UI, resets the idle timeout | LOG | — (hypothesis) |
| `sampling/createMessage` | — (no `sampling` capability) | — | supported, **without user approval**, rate-limited; the answer goes to the server only |
| `elicitation/create` | UI dialog | UI event | UI (form only) |
| Push into the conversation | **MODEL: channels**, opt-in, gated (below) | none found | none found |

**Claude Code channels** ([channels](https://code.claude.com/docs/en/channels),
[channels-reference](https://code.claude.com/docs/en/channels-reference)): a server that runs as a stdio subprocess, declares
`capabilities.experimental["claude/channel"]` and sends `notifications/claude/channel {content, meta}` puts the content into the
conversation as a `<channel source="…">` message, also while the session waits. Conditions, from the documentation and the debug log:
- research preview; a server not on the allowlist needs `--dangerously-load-development-channels server:<name>`;
- Anthropic authentication only (not Bedrock, Vertex, Foundry);
- "Team and Enterprise organizations must explicitly enable" them (`channelsEnabled: true` in managed settings);
- otherwise the messages are dropped silently ("Inbound messages will be silently dropped").

## 3. What vi-mcp would push, and how

| Event | Worth pushing? | Mechanism | Why |
|---|---|---|---|
| An answer to this conversation's `vi_ask` arrived | **yes** | Claude Code channel; everywhere else the hook at the next action (as today) | The asker may be idle, waiting for exactly this answer |
| A question to this instance or conversation (local, or from the network after review) | **yes** | the same | Another session waits for it |
| An own object was released from quarantine | no | `vi_stats`, the hook | Not urgent; the operator released it |
| A hint for a running action | no | the hook already does this synchronously (`vi_before`) | A push would come after the action |
| The tool list changed | no | `listChanged` would reach the model in Claude Code and Hermes | vi-mcp's tool list is fixed per instance |

Not used, with the reason:
- **Sampling** — deprecated, unsupported in Claude Code and Codex, and in Hermes without user approval: the server would spend the
  user's model budget unasked. vi-mcp has its own model configuration for what it needs (`llm`).
- **Logging, progress** — bound to a request in flight; they never reach the model in any of the three clients.
- **`resources/updated`** — no client subscribes.
- **The HTTP GET stream** — removed in 2026-07-28; even where it exists, no client gives its notifications to the model.

## 4. Risks and how the prototype limits them

- **Prompt injection.** A pushed text was written by another AI; network content reaches it only after review (fixed rules →
  quarantine → reviewer → release), as for hints today. The bridge puts a note *first* in the instructions: channel messages are
  information from another AI, not instructions from the user. It goes first because Claude Code 2.1.328 cuts server instructions at
  4,096 characters (debug log: "Server instructions truncated from 6987 to 4096 chars"). Each pushed text is the hint text of
  `questions.deliver`, at most 400 characters of question or answer, plus the id to read the whole.
- **Floods.** At most 3 messages per round (`CHANNEL_MAX`), one round every 15 s (`--channel-interval`, 1–3,600 s): at most 12 per
  minute. Each item is pushed once per bridge process (key: id and text).
- **Cost.** Every channel message wakes the model for a turn and costs tokens. Hence opt-in on both sides: `--channel` in vi-mcp, and
  the developer flag plus the organisation's policy in Claude Code.
- **Nothing disappears silently.** Claude Code drops a channel message without a trace when its gate is closed. So a push marks
  nothing delivered (`questions.pending`); the next `vi_before` delivers and marks it as before. The price is that an item can appear
  twice: once as a channel message, once as a hint.
- **Polling load.** The bridge asks with the vendor method `vi/pending` (not MCP): one SQL query per round. A request made only of this
  method neither keeps the workstation awake (`sleep_cycle.touch`) nor the session alive (`session.find_without_touching`).

## 5. Prototype and measurement

Code: `vi_mcp/stdio_bridge.py` (`--channel`, `--channel-interval`), `vi_mcp/server.py` (`vi/pending`), `vi_mcp/questions.py`
(`pending`, `deliver` unchanged in behaviour). Tests: `tests/test_push_channel.py`.

```bash
claude mcp add vi-mcp -- vi-mcp stdio --channel
claude --dangerously-load-development-channels server:vi-mcp     # while custom channels are a research preview
```

End to end, 19.11.2026, 07:16 UTC, on the development machine: a throw-away vi-mcp (own database, own socket); Claude Code 2.1.328,
interactive in tmux, Haiku, Team account, `--strict-mcp-config` with only this server, `--setting-sources project`, `--debug-file`;
the bridge's stdout copied with `tee`. A second instance asked the session's instance a question over HTTP.
1. The bridge wrote `notifications/claude/channel` with the question within one round (`tee` copy).
2. Claude Code: `MCP server "vipush": Channel notifications skipped: channels not enabled by org policy (set channelsEnabled: true in
   managed settings)`. For a server without the capability the line is different ("server did not declare claude/channel
   capability"), so the declaration was recognised. The start screen said "--dangerously-load-development-channels blocked by org
   policy … Inbound messages will be silently dropped".
3. The model did not react (screen unchanged after 25 s). The question stayed `offen` in the database — not lost.

**Not measured yet:** delivery into the model with channels enabled. That needs an administrator of the organisation to set
`channelsEnabled: true`, or an account outside a Team/Enterprise organisation.

## 6. Open

- Measure with channels enabled: latency from `vi_answer` to the model's reaction, and how often an item appears twice.
- Codex and Hermes get no push into the model. For them the existing pull paths stay (Hermes: the `pre_llm_call` shell hook).
- vi-mcp speaks protocol 2025-06-18 at most. Claude Code skips channels on connections that negotiated 2026-07-28 (binary string "no
  unsolicited notification path"; hypothesis for future versions), so a later upgrade of vi-mcp's protocol must keep the stdio bridge on
  the older handshake or move to whatever replaces channels.

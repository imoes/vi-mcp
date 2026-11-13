# vi-mcp — notes for agents and contributors

One server process with one memory for many AI sessions over MCP (Streamable HTTP). Explanation: [README.md](README.md) ·
[README.de.md](README.de.md) (German) · Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Operations: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## How it works

Before every action the session asks `vi_before` and gets at most four hints from the memory; afterwards it reports `vi_after`.
Since 0.49.0 a hint before a shell command must share a host, program or error with it — the tool and common words (`intuition.GENERIC_SHELL_WORDS`) do not count —
and a hint without measured benefit appears at most `DAILY_MAX` times a day per instance. `vi_feedback(helped, wrong)` books which hints
helped in one call; `metrics.hint_lift_matched` compares within instance and tool (the raw lift mixes base rates: Simpson's paradox).
When an AI consults the VI and when it learns is defined in `tools.RULES` and goes to every client with the `instructions` (since 0.20.7).
Sleep (when enough important things have accumulated; at night only after 24 h without sleep) condenses experiences into insights and skills and rates the work (scorer). Router, bandit and vectors
learn on demand (`on_demand`), about a minute after new experiences or new knowledge. Visibilities: private, shared, internal (only with a token; never an open network, only a company network).
Everything is an object in SQLite with hashtags (`art:wert`, kind:value), owning instance and visibility (stored as `privat`/`geteilt`/`intern`). The language model is never trained.

Since 0.53.0 a failed action brings what the memory knows about its error (`intuition.error_hints`, returned by `vi_after`), and the
first prompt of a session carries the skill table (`capabilities`, `vi_capabilities`: system, tools, manual id).
Since 0.44.0 the hook also searches before every user prompt (`vi_prompt_context`: Claude Code `UserPromptSubmit`, Hermes shell hook
`pre_llm_call` with `vi_hook.py --hermes`), so follow-up questions in a conversation get the memory too; the prompt is masked and not stored.

**The network** (since 0.39.0, `docs/ARCHITECTURE.md` from "P2P import" on). Servers form networks without a master: every server appends
signed entries to its own logbook, the network service (`vi-p2p`, `vi-p2p@<netz>`; on Windows since 0.54.0 scheduled tasks
`vi-p2p-<netz>`, `net_service.etc_dir`/`var_dir`) exchanges them, the memory checks them again.
- Networks: `standard` (open, anonymised, by invitation) and further ones with `vi-mcp net --network NAME setup --kind free|open|company`.
  `free` (0.45.0): anyone may join without invitation — identity proof of work as entry 1, quotas growing with measured benefit, local
  block lists, peer exchange from a start address. `company` carries internal knowledge to members of one organisation, by invitation. Published on 443 behind the reverse proxy (`--public https://HOST`,
  `vi-mcp net proxy-config`).
- Same meaning on several servers = one object with several holders (content hash), rated by every server's own measurements → network
  score (`net_score`); a content that keeps failing is no longer a hint.
- Network wiki (`wiki`, `wiki_merge`): `vi_page_read/write/history/forget`, revisions with parents, paragraph merge, named conflicts.
- Live search: `vi_net_search` asks the members now; hits are unreviewed until taken (`take`).
- Conversations between AIs (`forum`): `vi_ask(to="netz")`, answers come back reviewed; `vi_confirm` on an answer rates it. Since 0.52.0 a
  question is released as soon as fixed rules and reviewer admit it (`forum.release_questions`).
- Peers behind firewalls (0.52.0): a long poll at the peerhost (`/netz/warten`, `NetService.wait_loop`) brings news in seconds instead of
  at the 300 s round, and the peerhost relays live searches to its waiting peers (`relay_search`, one hop, hits signed by their authors).
- Everything foreign counts only after review (fixed rules → quarantine → reviewer → release); `vi_stats` section W counts all of it.
- Default wiki network (0.47.0): a new installation joins the free network `wiki` (start `https://vi-wiki.org/vi-p2p/wiki`,
  `p2p.WIKI_*`, `deploy/nach-installation.sh wiki`, opt-out `VI_MCP_KEIN_WIKI=1`). The instructions name every public network that is
  on (`p2p.notice`); the AI tells the user and switches on request with `vi_net_switch` (memory-side switch `netz_schalter`: off = no
  outbox, no inbox, no live search, the service pauses, the web page hides it).
- Web page (`web`, 0.46.0, config `web`, off by default; `vi-mcp web on --base PATH`): read-only HTML under `/web` — search, wiki, forum,
  knowledge of the networks of kind `free` and `open` only. Never a company network, internal or private knowledge, quarantine or a local
  instance name; own knowledge only in its anonymised export form. Server-side HTML, standard library, no JavaScript, strict CSP.
- Logbook entry types: objekt, widerruf, einladung, ausschluss, adresse, bewertung, seite, beitrag. A new type needs every peer ≥ 0.39.0
  (`Logbook.peers_below(lb.RELAY_MIN)`): older peers would reject it and stop the publisher's whole chain.

The MCP interface is English since 0.22.0 (tools, parameters, enum values); the German names remain valid as aliases (`vi_mcp/api_en.py`).
Stored formats (database, hashtags, object data, P2P wire format) keep their German names. The configuration files are English since
0.51.0 (keys and the network kinds free/open/company); `config.normalize` and `net_service.english_file` still read the German keys of
older files, and the package rewrites them in English at install (`configure.migrate_configs`, a copy of the old file stays).

## Installing and setting up

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb        # Debian 12+, Ubuntu 24.04+
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm     # Fedora, AlmaLinux/RHEL 10 with EPEL
sudo vi-mcp setup                                    # ANSI menu: Claude Code, Codex CLI, Hermes Agent
```

0.48.0: the package first asks for the server configuration (Debian: debconf, `dpkg-reconfigure vi-mcp`; RPM and everywhere:
`vi-mcp configure`, ANSI menu; catalogue in `vi_mcp/configure.py`, the Debian build generates `DEBIAN/templates` and `DEBIAN/config`
from it). Unattended: `VI_MCP_<KEY>` environment variables (e.g. `VI_MCP_PORT`, `VI_MCP_WIKI`, `VI_MCP_INSTANCE`). Then the client
menu below. On first installation the menu opens by itself if a terminal is present. Without the menu:
`vi-mcp setup --claude --codex --hermes --hook --url URL --token-file FILE`. The German command names (`einrichten`, `--token-datei`, …) remain valid as aliases.

## Working on the code

| Task | Command |
|---|---|
| Tests | `.venv/bin/python -m pytest -q tests -p no:cacheprovider` (`.venv`: scikit-learn, cryptography, pyyaml, numpy) |
| Tests against PostgreSQL (0.50.0) | `VI_MCP_TEST_PG=postgresql://USER@HOST/DB` before the same command (`.venv` also needs psycopg; a throw-away database: every test gets its own schema) |
| Debian package | `deploy/debian/build.sh` |
| RPM package | `deploy/rpm/build.sh` (builds in a Fedora container if `rpmbuild` is missing) |
| Windows MSI | `deploy/windows/build.sh` (wixl/msitools in a Fedora container; `install.ps1` does Python, venv, PyPI and the scheduled task) |
| Release | `deploy/release.sh --gh`: builds .deb, .rpm and .msi, signs `SHA256SUMS` (key outside the repo, `VI_MCP_RELEASE_KEY`, old name `VI_MCP_RELEASE_SCHLUESSEL`), checks and publishes — since 0.54.0 also into the signed apt/dnf repository `imoes/vi-mcp-packages` (GitHub Pages, `deploy/publish-repo.sh`, OpenPGP key in `VI_MCP_REPO_GNUPG`, default `~/.config/vi-mcp/repo-gnupg`, public part `deploy/repo-key.asc`) |
| Check a release | `deploy/pruefe-release.sh <directory>` |

Modules (`vi_mcp/`): `memory` (objects, search), `intuition` (before/after), `session`, `sleep_cycle`, `main_loop` (the loop), `scorer`, `learning`, `bandit`, `vector`, `reflection`, `skills`, `reflexes`, `sandbox`,
`content` (meaning as a router feature), `on_demand` (training on demand), `evaluation` (fixed question set, daily measurement in sleep, 0.55.0), `weight_writer` (LLM weight layer on the fitted router, measured, 0.58.0), `indexes` (projects and special VIs: column objekt.idx, table vi_index, project first, own model per index, 0.61.0), `code_import` (code of a git repository into an index, vi_code_sync, 0.61.0), `index_transfer` (an index into a signed file and back, comparison of the same content in two places, 0.62.0), `solutions` (problem → solution with content from episodes, 0.55.0), `usage_stats` (usage statistics, `vi_stats`), `metrics` (hint lift, by hint age), `images` (images with description and SAM 3 regions), `image_cli` (`vi-mcp image`), `stdio_bridge` (`vi-mcp stdio`, MCP over stdio through the local socket), `index` (memory index in the instructions), `weight_audit` (fixed rules over the router weights), `archive`, `self_model`, `questions`, `p2p` (memory on the network), `net_score` (content hash, holders, network score), `wiki` + `wiki_merge` (network wiki pages, merge), `forum` (questions and answers between AIs in the network), `web` (read-only web page of the free and open networks), `configure` (package configuration: debconf, menu, VI_MCP_ variables), `db` (SQLite or PostgreSQL behind the sqlite3 interface, SQL translation), `db_migrate` (`vi-mcp db migrate|status`), `logbook`, `net_service` (separate process `vi-p2p`), `net_torrent`, `net_cli`, `anonymize`, `checks`, `reviewer`, `setup`, `config`, `server`, `tools`, `api_en` (German aliases), `log_output`.

## Rules

- **Store knowledge in full.** Code, API tables, commands and configurations belong unabridged in the field `content` (stored as `inhalt`, up to 200,000 characters), not as a summary with a reference to a file. What is missing is a gap in the memory.

- **Public repository.** No host names, IPs, user names, tokens or internal URLs in code, docs, commits or packages. Host-specific material belongs in `docs/LOKAL*.md` (gitignored, never in a package).
- **Nothing internal onto an open network.** What leaves for an open network goes through `anonymize.py`; what comes in is rejected there. A company network (`art: firma`, 0.39.0, members of one organisation) carries internal knowledge unanonymised, and its imports stay internal and are never exported again. A new kind of export needs a test in `tests/test_anonym.py`.
- **Portable SQL (0.50.0).** Write SQLite SQL through `g.db()`; it must also run on PostgreSQL (`vi_mcp/db.py` translates the idioms its
  docstring lists). Not translated, so not allowed: `json_set`/`json_remove`/`json_each` (use `memory.update_data` or Python), a number
  read from JSON without `CAST(json_extract(…) AS REAL)`, an alias in `HAVING`, scalar `min(a, b)`/`max(a, b)`, integer shifts,
  `SELECT DISTINCT … ORDER BY` a column that is not selected. A new
  query is tested by running the suite with `VI_MCP_TEST_PG`.
- **No `max_tokens` / `n_predict`.** If an output is cut off: switch thinking off (`chat_template_kwargs: {enable_thinking: false}`).
- **Language-model verdicts only tighten.** The model can be deceived by the text it checks; only fixed rules may reject for good.
  Exception by design (0.58.0): the LLM weight layer (`weight_writer.py`) may also loosen a weight — it acts only after the offline gate and
  a randomized online test, and it never sees text from the network.
- **No instance rates itself.** There is no MCP tool for setting a grade.
- **Nothing disappears silently:** what is held back is counted with a reason, what is deleted leaves a tombstone. Reports name the class of a finding, never its value.
- Every change a user notices is recorded with evidence in `CHANGELOG.md`.

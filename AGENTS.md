# vi-mcp — notes for agents and contributors

One server process with one memory for many AI sessions over MCP (Streamable HTTP). Explanation: [README.md](README.md) ·
[README.de.md](README.de.md) (German) · Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Operations: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## How it works

Before every action the session asks `vi_before` and gets at most four hints from the memory; afterwards it reports `vi_after`.
When an AI consults the VI and when it learns is defined in `tools.RULES` and goes to every client with the `instructions` (since 0.20.7).
Sleep (when enough important things have accumulated; at night only after 24 h without sleep) condenses experiences into insights and skills and rates the work (scorer). Router, bandit and vectors
learn on demand (`on_demand`), about a minute after new experiences or new knowledge. Visibilities: private, shared, internal (only with a token, never on the network).
Everything is an object in SQLite with hashtags (`art:wert`, kind:value), owning instance and visibility (stored as `privat`/`geteilt`/`intern`). The language model is never trained.

The MCP interface is English since 0.22.0 (tools, parameters, enum values); the German names remain valid as aliases (`vi_mcp/api_en.py`).
Stored formats (database, hashtags, object data, P2P wire format, config keys) keep their German names.

## Installing and setting up

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb        # Debian 12+, Ubuntu 24.04+
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm     # Fedora, AlmaLinux/RHEL 10 with EPEL
sudo vi-mcp setup                                    # ANSI menu: Claude Code, Codex CLI, Hermes Agent
```

On first installation the menu opens by itself if a terminal is present. Without the menu:
`vi-mcp setup --claude --codex --hermes --hook --url URL --token-file FILE`. The German command names (`einrichten`, `--token-datei`, …) remain valid as aliases.

## Working on the code

| Task | Command |
|---|---|
| Tests | `.venv/bin/python -m pytest -q tests -p no:cacheprovider` (`.venv`: scikit-learn, cryptography, pyyaml, numpy) |
| Debian package | `deploy/debian/build.sh` |
| RPM package | `deploy/rpm/build.sh` (builds in a Fedora container if `rpmbuild` is missing) |
| Windows MSI | `deploy/windows/build.sh` (wixl/msitools in a Fedora container; `install.ps1` does Python, venv, PyPI and the scheduled task) |
| Release | `deploy/release.sh --gh`: builds .deb, .rpm and .msi, signs `SHA256SUMS` (key outside the repo, `VI_MCP_RELEASE_KEY`, old name `VI_MCP_RELEASE_SCHLUESSEL`), checks and publishes |
| Check a release | `deploy/pruefe-release.sh <directory>` |

Modules (`vi_mcp/`): `memory` (objects, search), `intuition` (before/after), `session`, `sleep_cycle`, `main_loop` (the loop), `scorer`, `learning`, `bandit`, `vector`, `reflection`, `skills`, `reflexes`, `sandbox`,
`content` (meaning as a router feature), `on_demand` (training on demand), `usage_stats` (usage statistics, `vi_stats`), `metrics` (hint lift, by hint age), `weight_audit` (fixed rules over the router weights), `archive`, `self_model`, `questions`, `p2p` (memory on the network), `logbook`, `net_service` (separate process `vi-p2p`), `net_torrent`, `net_cli`, `anonymize`, `checks`, `reviewer`, `setup`, `config`, `server`, `tools`, `api_en` (German aliases), `log_output`.

## Rules

- **Store knowledge in full.** Code, API tables, commands and configurations belong unabridged in the field `content` (stored as `inhalt`, up to 200,000 characters), not as a summary with a reference to a file. What is missing is a gap in the memory.

- **Public repository.** No host names, IPs, user names, tokens or internal URLs in code, docs, commits or packages. Host-specific material belongs in `docs/LOKAL*.md` (gitignored, never in a package).
- **Nothing internal onto the network.** What leaves for the network goes through `anonymize.py`; what comes in is rejected there. A new kind of export needs a test in `tests/test_anonym.py`.
- **No `max_tokens` / `n_predict`.** If an output is cut off: switch thinking off (`chat_template_kwargs: {enable_thinking: false}`).
- **Language-model verdicts only tighten.** The model can be deceived by the text it checks; only fixed rules may reject for good.
- **No instance rates itself.** There is no MCP tool for setting a grade.
- **Nothing disappears silently:** what is held back is counted with a reason, what is deleted leaves a tombstone. Reports name the class of a finding, never its value.
- Every change a user notices is recorded with evidence in `CHANGELOG.md`.

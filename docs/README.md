# vi-mcp documentation

Where to find what. Start with the [README](../README.md) ([deutsch](../README.de.md)); everything below goes deeper.

| Document | For | What it holds |
|---|---|---|
| [README](../README.md) · [README.de](../README.de.md) | everyone | What vi-mcp is, installing (package repository, packages, Windows), configuring, connecting clients, the network, privacy, the tool overview |
| [REFERENCE](REFERENCE.md) | administrators, client authors | **Generated from the code**: every MCP tool with every parameter, the command line, both configuration files, the configuration catalogue (`VI_MCP_<KEY>`), environment variables, HTTP endpoints, modules |
| [OPERATIONS](OPERATIONS.md) | administrators | Debian/RPM package, user service, configuration, PostgreSQL, embedding service, ports, Windows, backup, uninstalling |
| [ARCHITECTURE](ARCHITECTURE.md) | developers | Design: memory, intuition (hints), sleep, scorer, router and bandit, the network (logbook, gossip, long poll, network score, wiki, forum, live search), open wiki mode |
| [PAPER](PAPER.md) | people and AIs | Technical report: how the memory learns, how a VI matures in the incubator, how its language VIL is built (symbols and weights), measurements, errors found, limitations, references |
| [HOOK](HOOK.md) | client setup | The Claude Code / Hermes hook: what it reports before and after every action and prompt, and why |
| [AGENTS](../AGENTS.md) | AI agents and contributors working on the code | How it works in short, commands, modules, the rules (no internal names in the repository, portable SQL, nothing disappears silently …) |
| [CHANGELOG](../CHANGELOG.md) | everyone | What changed in each version, with evidence, and what is still missing |
| [TRAINING](TRAINING.md) (German) | research | How an AI is trained and how vi-mcp stores its data for that |
| [FORSCHUNG](FORSCHUNG.md) (German) | research | How people remember, and what vi-mcp takes from it |
| [erzaehlung.html](erzaehlung.html) (German) | everyone | "Lernen ohne Fine-Tuning" — the idea told as a story |

The package repository for updates with `apt upgrade` / `dnf upgrade`: https://imoes.github.io/vi-mcp-packages/ (README, "Install").
The public wiki network's server: https://vi-wiki.org/.

`docs/REFERENCE.md` is regenerated with `python3 scripts/gen_reference.py`; `tests/test_reference.py` fails when it is out of date or when
the code has a configuration key, network field, environment variable, endpoint or tool parameter without a description.

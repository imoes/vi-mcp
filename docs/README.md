# vi-mcp documentation

Where to find what. Start with the [README](../README.md) ([deutsch](../README.de.md)); everything below goes deeper.

| Document | For | What it holds |
|---|---|---|
| [README](../README.md) · [README.de](../README.de.md) | everyone | What vi-mcp is, installing (package repository, packages, Windows), configuring, connecting clients, the network, privacy, the tool overview |
| [REFERENCE](REFERENCE.md) | administrators, client authors | **Generated from the code**: every MCP tool with every parameter, the command line, both configuration files, the configuration catalogue (`VI_MCP_<KEY>`), environment variables, HTTP endpoints, modules |
| [OPERATIONS](OPERATIONS.md) | administrators | Debian/RPM package, user service, configuration, PostgreSQL, embedding service, ports, Windows, backup, uninstalling |
| [CLAUDE_REVIEW](CLAUDE_REVIEW.md) | reviewers | VI assessment, implemented audit fixes, execution and training evidence, independent review checklist |
| [KNN_LM](KNN_LM.md) | inference operators and developers | Real kNN token interpolation, mutable context-state datastore, pretrained-model evidence and VI backend integration |
| [SUMMARY_Z11](SUMMARY_Z11.md) · [RESULTS_Z11](RESULTS_Z11.md) · [RESULTS_Z11_2](RESULTS_Z11_2.md) · [RESULTS_Z11_3](RESULTS_Z11_3.md) · [RESULTS_Z11_4](RESULTS_Z11_4.md) | research | Goal Z11 (closed 24.11.2026): the kNN-LM token store next to frozen weights against LoRA and RAG — knowledge carried, forget by document, provenance readout, edit preview; summary first |
| [PREREG_Z11](PREREG_Z11.md) · [A1](PREREG_Z11_A1.md) · [A2](PREREG_Z11_A2.md) · [A3](PREREG_Z11_A3.md) · [A4](PREREG_Z11_A4.md) · [D1](PREREG_Z11_D1.md) · [D2](PREREG_Z11_D2.md) · [D3](PREREG_Z11_D3.md) · [PREREG_Z11_2](PREREG_Z11_2.md) · [Z11_2_A1](PREREG_Z11_2_A1.md) · [PREREG_Z11_3](PREREG_Z11_3.md) · [Z11_3_R1](PREREG_Z11_3_R1.md) · [PREREG_Z11_4](PREREG_Z11_4.md) | research | The frozen pre-registrations of Z11, its amendments and deviations, each with a sha256 file next to it |
| [INSTANCE_RUNTIME](INSTANCE_RUNTIME.md) | agents and inference operators | Complete instance state, controlled MCP loop, model/device permissions, coherent neural checkpoints and boot |
| [VIRTUAL_MACHINE](VIRTUAL_MACHINE.md) | agents and developers | Executable VIL machine contract, mutable worlds, snapshots, isolation, model-generated programs and reference-checked training |
| [ARCHITECTURE](ARCHITECTURE.md) | developers | Design: memory, intuition (hints), sleep, scorer, router and bandit, the network (logbook, gossip, long poll, network score, wiki, forum, live search), open wiki mode |
| [PAPER](PAPER.md) | people and AIs | Technical report: how the memory learns, how a VI matures in the incubator, how its language VIL is built (symbols and weights), measurements, errors found, limitations, references |
| [HOOK](HOOK.md) | client setup | The Claude Code / Hermes hook: what it reports before and after every action and prompt, and why |
| [PUSH](PUSH.md) | client setup, developers | Can the server tell a connected AI something on its own: what the MCP specification allows (2026-07-28), what Claude Code, Codex and Hermes do with each notification, the channel prototype `vi-mcp stdio --channel` and its measurement |
| [AGENTS](../AGENTS.md) | AI agents and contributors working on the code | How it works in short, commands, modules, the rules (no internal names in the repository, portable SQL, nothing disappears silently …) |
| [PREREG_Z7_HINT_UTILITY](PREREG_Z7_HINT_UTILITY.md) · [PREREG_Z7B_WITHIN_ACTION](PREREG_Z7B_WITHIN_ACTION.md) | research | Pre-registered offline tests of the hint router (goal Z7): which label carries hint signal, the label-source artefact, the within-action test — hypotheses, results, post-hoc checks |
| [CHANGELOG](../CHANGELOG.md) | everyone | What changed in each version, with evidence, and what is still missing |
| [TRAINING](TRAINING.md) (German) | research | How an AI is trained and how vi-mcp stores its data for that |
| [CODE_FACTS](CODE_FACTS.md) | developers who import code into an index | Code structure as facts (calls, imports, table writes, raises, tests, history) read by clingo-object; the architecture-rules philosophy `code`; the measurement against plain search |
| [PHILOSOPHY](PHILOSOPHY.md) | anyone who wants an AI to work by principles | Philosophy packages: principles in prose plus a checked clingo-object seed with test worlds; check, install, train, measure (generated from the code) |
| [IMPORT](IMPORT.md) | administrators and AIs that bring documentation into a VI | The documentation import access (0.69.0): an import instance, the pages file (JSON Lines), `vi-mcp docs import`, what the server does with each page (one object, hashtags and triggers at once, links, the old shape archived), checks and limits |
| [FINETUNING](FINETUNING.md) | anyone who wants to fine-tune a model with a VI's knowledge | From zero: how knowledge is stored training-ready, the kit, the container, the recipe that worked, the knowledge probe, limits and next improvements |
| [EXAPTATION_PAPER](EXAPTATION_PAPER.md) | people and AIs who want a memory to transfer solutions across contexts | Working paper: exaptation (a mechanism built for one purpose that helps another) in an agent memory — the unified-shader case, prior art on analogy and vectors, pre-registered measurements (hints outside their context, embedding offsets), what the VI adds |
| [FINETUNING_PAPER](FINETUNING_PAPER.md) | people and AIs who train a model on a philosophy | Working paper: thirty fine-tuning runs that teach a 0.6B model the seed, scored by the solver — findings with sources, status against the targets, corrected measurement errors, open points |
| [CLINGO_SKILL](CLINGO_SKILL.md) | any AI that writes logic programs with vi_logic | The initial skill manual clingo: notation, workflow, the six answers, norms, soft rules, rules over memory objects, measured mistakes — every example checked against the engine; generated from `vi_mcp/clingo_skill.py`, in the server as the initial skill `insight:skill-clingo` (knowledge_kind:skill, `vi_object`) |
| [FINETUNING_SKILL](FINETUNING_SKILL.md) | any AI (also small models) that fine-tunes a model for a person | The step-by-step runbook to fine-tune any open model with vi-mcp: rules first, one command and one check per step, tables for GPU memory and settings — generated from `vi_mcp/finetune_skill.py`, also `vi_finetune(action="skill")` |
| [TRAINING_PREFLIGHT](TRAINING_PREFLIGHT.md) | model trainers and reviewers | Complete-target token audit, real trainer checks without training, standalone evaluation and limits |
| [FORSCHUNG](FORSCHUNG.md) (German) | research | How people remember, and what vi-mcp takes from it |
| [erzaehlung.html](erzaehlung.html) (German) | everyone | "Lernen ohne Fine-Tuning" — the idea told as a story |

The package repository for updates with `apt upgrade` / `dnf upgrade`: https://imoes.github.io/vi-mcp-packages/ (README, "Install").
The public wiki network's server: https://vi-wiki.org/.

`docs/REFERENCE.md` is regenerated with `python3 scripts/gen_reference.py`; `tests/test_reference.py` fails when it is out of date or when
the code has a configuration key, network field, environment variable, endpoint or tool parameter without a description.

# vi-mcp — notes for agents and contributors

One server process with one memory for many AI sessions over MCP (Streamable HTTP). Explanation: [README.md](README.md) ·
[README.de.md](README.de.md) (German) · Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Operations: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## How it works

Before every action the session asks `vi_before` and gets at most four hints from the memory; afterwards it reports `vi_after`.
Since 0.49.0 a hint before a shell command must share a host, program or error with it — the tool and common words (`intuition.GENERIC_SHELL_WORDS`) do not count —
and a hint without measured benefit appears at most `DAILY_MAX` times a day per instance. `vi_feedback(helped, wrong)` books which hints
helped in one call (0.71.0: the hook asks per action for `vi_feedback(before_id, used, wrong)` → outcome-free `data.declared`, counted as `data.feedback_asked`); `metrics.hint_lift_matched` compares within instance and tool (the raw lift mixes base rates: Simpson's paradox).
When an AI consults the VI and when it learns is defined in `tools.RULES` and goes to every client with the `instructions` (since 0.20.7); since 0.70.6 `RULES` is a short core under Claude Code's 4,096-character cut, the complete text `RULES_FULL` is the initial skill vi-rules, and `tests/test_instructions_budget.py` holds the budget.
Sleep (when enough important things have accumulated; at night only after 24 h without sleep) condenses experiences into insights and skills and rates the work (scorer). Router, bandit and vectors
learn on demand (`on_demand`), about a minute after new experiences or new knowledge. Visibilities: private, shared, internal (only with a token; never an open network, only a company network).
Everything is an object in SQLite with hashtags (`art:wert`, kind:value), owning instance and visibility (stored as `privat`/`geteilt`/`intern`). vi-mcp trains no model by itself; fine-tuning an AI with a VI's knowledge is a person's explicit action (`vi_finetune`, `vi-mcp finetune`: data, scripts and lineage — the training runs in an external program on a GPU host, 0.62.0).

0.64.0: `vi_machine` / `vi-mcp machine` executes VIL over a named instance's private mutable world, with safe clingo-object programs,
revisions, snapshots and forks. A full independent answer reference checks an execution; only explicit `teach` promotes that example
internally for training. See `docs/VIRTUAL_MACHINE.md`. The optional `vi-mcp knn` runs on the inference host, below MCP: a frozen
Transformers causal model interpolates next-token probabilities with a mutable hidden-state/target datastore. Its shards and snapshots
are private inference files, not VI SQL or network exports. `docs/KNN_LM.md`, `scripts/demo_knn_lm.py` and `tests/test_knn_lm.py` document
the real neural path; the neural test needs torch/transformers and otherwise skips. No Python from MCP callers runs in either path.

Complete instance contract `vil-instance-v1`: `clingo_object/runtime.py` is the trusted client loop, `machine_runtime` validates
context/model/device/permission state on the memory server, `machine_host` provides `vi-mcp machine run|checkpoint|boot`. Device calls
are reserved before dispatch, reported through before/after and never automatically repeated when their outcome is uncertain.
The instance host holds the datastore writer lock across a symbolic capture; boot restores private context, programs and token
memory against the current host's capabilities. Transport endpoints and credentials are not in the bundle. `docs/INSTANCE_RUNTIME.md`.

Training kits include `training_runtime.py`: render original tool messages, audit complete assistant targets, verify real trainer
tokens and refuse silent truncation. `train.py --tokenizer-only` loads no weights; `--preflight` constructs TRL/PEFT and checks one
no-grad loss with unchanged parameters and zero optimizer steps. Neither starts training. The optional integration tests are
`tests/test_training_runtime_neural.py`; setup and boundaries: `docs/TRAINING_PREFLIGHT.md`.

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
- Wiki network (0.47.0; only with consent since 0.69.8 — issue #3: an Arch install without a terminal joined silently): the free
  network `wiki` (start `https://vi-wiki.org/vi-p2p/wiki`, `p2p.WIKI_*`) is joined only when the person says yes in `vi-mcp configure`,
  sets `VI_MCP_WIKI=1` at installation or runs `vi-mcp net wiki on`; every package's default is off. The instructions name every public network that is
  on (`p2p.notice`); the AI tells the user and switches on request with `vi_net_switch` (memory-side switch `netz_schalter`: off = no
  outbox, no inbox, no live search, the service pauses, the web page hides it).
- Web page (`web`, 0.46.0, config `web`, off by default; `vi-mcp web on --base PATH`): read-only HTML under `/web` — search, wiki, forum,
  knowledge of the networks of kind `free` and `open` only. Never a company network, internal or private knowledge, quarantine or a local
  instance name; own knowledge only in its anonymised export form. Server-side HTML, standard library, no JavaScript, strict CSP.
- Logbook entry types: objekt, widerruf, einladung, ausschluss, adresse, bewertung, seite, beitrag. A new type needs every peer ≥ 0.39.0
  (`Logbook.peers_below(lb.RELAY_MIN)`): older peers would reject it and stop the publisher's whole chain.

The MCP interface is English since 0.22.0 (tools, parameters, enum values); the German names remain valid as aliases (`vi_mcp/api_en.py`).
Stored names become English in 0.67.0 (`vi_mcp/names.py`, the one table; an old database is migrated in place when opened, after a backup
copy): tables, columns, indexes, stored values (kinds, modes, visibilities, …), hashtag kinds and system values (`topic:`, `state:open`, …)
and the data keys of the domain objects (`source`, `content`, `before`, …; `names.DATA_KEYS`, written English by `memory.save` and
`update_data`) are done. The reports of `sleep`, `model` and `self` objects (`names.REPORT_KINDS`) keep German keys until 0.68: their
modules read them fresh and stored, so they change at the source together with every reader. Object ids: existing ones keep their German prefix, new ones are English; lookups take both (`memory.load_keyed`). The P2P wire
format and content hashes stay German (signed by every server) and are translated at the boundary. The configuration files are English since
0.51.0 (keys and the network kinds free/open/company); `config.normalize` and `net_service.english_file` still read the German keys of
older files, and the package rewrites them in English at install (`configure.migrate_configs`, a copy of the old file stays).

## Installing and setting up

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb        # Debian 12+, Ubuntu 24.04+
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm     # Fedora, AlmaLinux/RHEL 10 with EPEL
sudo pacman -U ./vi-mcp-<version>-1-any.pkg.tar.zst  # Arch Linux, CachyOS (then: sudo systemctl enable --now vi-mcp.service)
sudo vi-mcp setup                                    # ANSI menu: Claude Code, Codex CLI, Hermes Agent
```

0.71.0: a client on another machine needs no package — the server serves its own Claude Code plugin (`/plugins/claude/marketplace.json`,
archive with sha256, URL and token as plugin options; `public_url` behind the reverse proxy, the archive only over https) and the hook
file (`/plugins/hook/vi_hook.py`). The routes need no token by design — only public code, never instance data, no token in any served file; `plugins: false` switches them off. Test an install end to end with an isolated `CLAUDE_CONFIG_DIR`, never against production.

0.48.0: the package first asks for the server configuration (Debian: debconf, `dpkg-reconfigure vi-mcp`; RPM and everywhere:
`vi-mcp configure`, ANSI menu; catalogue in `vi_mcp/configure.py`, the Debian build generates `DEBIAN/templates` and `DEBIAN/config`
from it). Unattended: `VI_MCP_<KEY>` environment variables (e.g. `VI_MCP_PORT`, `VI_MCP_WIKI`, `VI_MCP_INSTANCE`). Then the client
menu below. On first installation the menu opens by itself if a terminal is present. Without the menu:
`vi-mcp setup --claude --codex --hermes --hook --url URL --token-file FILE`. The German command names (`einrichten`, `--token-datei`, …) remain valid as aliases.

## Working on the code

| Task | Command |
|---|---|
| Tests | `.venv/bin/python -m pytest -q tests -p no:cacheprovider` (`.venv`: scikit-learn, cryptography, pyyaml, numpy; clingo for `tests/test_logic.py`, skipped without it) |
| Tests against PostgreSQL (0.50.0) | `VI_MCP_TEST_PG=postgresql://USER@HOST/DB` before the same command (`.venv` also needs psycopg; a throw-away database: every test gets its own schema and none is dropped — recreate the database now and then: at 21,804 schemas (9.8 GB) a container's `/dev/shm` ran full and PostgreSQL crashed mid-run, 13.11.2026) |
| Debian package | `deploy/debian/build.sh` |
| RPM package | `deploy/rpm/build.sh` (builds in a Fedora container if `rpmbuild` is missing) |
| Arch / CachyOS package | `deploy/arch/build.sh` (PKGBUILD from `deploy/arch/PKGBUILD.in`; builds in an `archlinux:base-devel` container if `makepkg` is missing; users by sysusers.d, the service is not enabled by the package) |
| macOS (Homebrew) | `deploy/macos/build.sh` → `dist/vi-mcp-<version>.tar.gz` (reproducible source archive, a release asset) and `dist/vi-mcp.rb` (formula from `deploy/macos/vi-mcp.rb.in`; the release pushes it to the tap `imoes/homebrew-vi-mcp`). Test without a Mac: a local tap in the `homebrew/brew` container (`brew update` first), url switched to `file://` |
| Windows MSI | `deploy/windows/build.sh` (wixl/msitools in a Fedora container; `install.ps1` does Python, venv, PyPI and the scheduled task) |
| Release | `deploy/release.sh --gh`: builds .deb, .rpm, the Arch package, .msi, the wheel and the macOS archive + formula (every platform, 0.68.1), signs `SHA256SUMS` (key outside the repo, `VI_MCP_RELEASE_KEY`, old name `VI_MCP_RELEASE_SCHLUESSEL`), checks and publishes — since 0.54.0 also into the signed apt/dnf repository `imoes/vi-mcp-packages` (GitHub Pages, `deploy/publish-repo.sh`, OpenPGP key in `VI_MCP_REPO_GNUPG`, default `~/.config/vi-mcp/repo-gnupg`, public part `deploy/repo-key.asc`) |
| Check a release | `deploy/pruefe-release.sh <directory>` |

Modules (`vi_mcp/`): `memory` (objects, search), `philosophy` (philosophy packages: CLI, install, tool vi_philosophy — the technique is `clingo_object/philosophy.py`), `intuition` (before/after), `session`, `sleep_cycle`, `main_loop` (the loop), `scorer`, `learning`, `bandit`, `vector`, `reflection`, `skills`, `reflexes`, `sandbox`,
`content` (meaning as a router feature), `on_demand` (training on demand), `evaluation` (fixed question set, daily measurement in sleep, 0.55.0), `weight_writer` (LLM weight layer on the fitted router, measured, 0.58.0), `indexes` (projects and special VIs: column object.idx, table vi_index, project first, own model per index, 0.61.0), `code_import` (code of a git repository into an index, vi_code_sync, 0.61.0), `philosophy_fit` (which philosophy fits which situation: declared in the package, rated per use, suggested by Thompson sampling and in the prompt context; vi_philosophy suggest/rate, 0.69.6), `knowledge_skills` (skills in the server: knowledge_kind:skill + docs:<name>, added with vi_learn key skill:<name>, listed by vi_capabilities; the initial skills clingo, finetune, philosophy written at every start; `vi-mcp skill import DIR --instance NAME`, 0.69.4), `clingo_skill` (the initial skill clingo, every example checked against the engine, 0.69.4), `agent_qualify` (the reading or storing AI qualifies in the same call: vi_qualify, and pairs/labels in vi_learn — fixed rules check them, 0.69.3), `secret_sweep` (credentials in documentation checked once per check version: at import, on access, sleep step 6c, archive; `vi-mcp secrets sweep`, 0.69.3), `qualify` (qualification on access, 0.69.2: what vi_recall / vi_object / the web search return gets missing labels and documentation triggers now — classify.on_search + doc_triggers.refresh, at most 10 per access), `doc_import` (the documentation import access, 0.69.0: `vi_doc_sync` for instances with the import right, `vi-mcp docs import FILE.jsonl` — one object per page, fixed id per source/page, hashtags and doc_triggers at import, links as edges, the old shape and removed pages archived; docs/IMPORT.md), `doc_formats` (0.70.0: documents → Markdown pages for the import — PDF via pypdf, DOCX/XLSX/PPTX and ODT/ODS/ODP with the standard library, HTML, EPUB, EML, CSV, text; DOC/XLS/PPT/RTF through LibreOffice when installed; every file converted or refused with a named class and reason; `vi-mcp docs convert|formats`), `code_facts` (structure facts of the same ast pass as fact objects, the bridge to the philosophy package `code`, `vi-mcp index code-check`), `vector_import` (vectors of an index with a search scope computed on another host: `vi-mcp vectors export|import`, checked against this server's embedding service, all or nothing, 0.70.4), `index_transfer` (an index into a signed file and back, comparison of the same content in two places, 0.62.0), `solutions` (problem → solution with content from episodes, 0.55.0), `usage_stats` (usage statistics, `vi_stats`), `metrics` (hint lift, by hint age), `images` (images with description and SAM 3 regions), `image_cli` (`vi-mcp image`), `stdio_bridge` (`vi-mcp stdio`, MCP over stdio through the local socket), `index` (memory index in the instructions), `weight_audit` (fixed rules over the router weights), `archive`, `self_model`, `questions`, `p2p` (memory on the network), `net_score` (content hash, holders, network score), `wiki` + `wiki_merge` (network wiki pages, merge), `forum` (questions and answers between AIs in the network), `web` (read-only web page of the free and open networks), `web_internal` (internal knowledge search with sign-in, 0.62.0), `plugins` (the server serves its own client integration under /plugins: Claude Code marketplace + deterministic plugin archive with sha256, the hook file; no token in any served file, 0.71.0), `vocabulary` (the words of the memory with counts, completion, why a search found nothing, 0.62.0), `vil` (VIL, the AI language: ask questions, tell answers, 0.62.0), `classify` (labels knowledge by question type and memory kind with a language model, 0.62.0), `dataset` (training data for fine-tuning: qa/kto/dpo with datasheet, hold-out and scrubbing audit, 0.62.0), `incubator` (maturity of a VI for fine-tuning, measured criteria, hatch, 0.62.0), `finetune` (the fine-tuning interface: handbook, plan, kit with TRL scripts, record with lineage, 0.62.0), `finetune_skill` (the step-by-step runbook to fine-tune any open model, written for small models — `vi_finetune(action="skill")`, `vi-mcp finetune skill`, docs/FINETUNING_SKILL.md, 0.68.0), `word_weights` (measured weight per word and question type, exchanged between memories as signed ratings, 0.62.0), `redteam` (memory-poisoning test in a throw-away memory, 0.62.0), `relevance` (a language model grades real searches 0–3 after UMBRELA — the relevance label, measured only, 0.62.0), `feature_writer` (weight-space programming turned around: a language model reads the router's weights and errors and writes feature rules, the fit writes the numbers; selected in training, tested once on the holdout, 0.68.0; external AIs propose rules the same way with `vi_feature_propose`, measured per proposer in sleep step 8k2), `hint_prior` (an LLM prior for new hints as situation tags, features only while the offline gate says on, 0.68.0), `finetune_embed` (the embedding fine-tuning kit: LoRA adapter served next to the base by llama.cpp, real pairs for evaluation, synthetic pairs for training, 0.68.0), `query_adapter` (learned embedding weights by scikit-learn: a per-dimension weighting of the query vector, stored vectors unchanged, on only while its offline gate says so, 0.68.0), `search_questions` (the classify model writes short search queries per object in the style of the logged searches, round-trip filtered — labels for the query adapter, 0.68.0), `hint_judge` (a language model judges whether a shown hint was used, used/not_used/misleading — a router label, small weight until it agrees with the agents' own feedback, 0.68.0), `logic` (rules in a Python-like notation decided by clingo: four-valued answers, reported violations, soft rules with learned weights, 0.62.0), the top-level package `clingo_object` (0.63.0, clingo-objekt; `philosophy_trace` = the solver-checked reasoning traces a model is trained to write for kollektiv 1.3.0, 0.70.1: `notation` = the language core the server runs, `expr`/`model`/`program` = real Python classes and expressions compiling to it, `client` = `Memory`, the MCP client; never imports `vi_mcp`), `configure` (package configuration: debconf, menu, VI_MCP_ variables), `db` (SQLite or PostgreSQL behind the sqlite3 interface, SQL translation), `db_migrate` (`vi-mcp db migrate|status`), `names` (stored names German → English, the migration of 0.67.0), `chunking` (structure-aware chunks of long content with their heading path — the search unit only, ported from IT-AIKB, 0.67.0), `context_budget` (which chunks reach the reader: reranker, section neighbours, a cap per object, cut at the largest score drop, 0.67.0), `collect` (the automatic collect mode of vi_recall for questions about everything of one entity, 0.67.0), `logbook`, `net_service` (separate process `vi-p2p`), `net_torrent`, `net_cli`, `anonymize`, `checks`, `reviewer`, `setup`, `config`, `server`, `tools`, `api_en` (German aliases), `log_output`.

## Importing documentation (0.69.0)

Documentation from another system (Confluence, a vendor manual, a knowledge base) goes in through the import access, never page by page
with `vi_learn`: an instance created with `vi-mcp instance NAME --import`, a JSON-Lines file of pages (`page_id` + whole `markdown`,
optional `title`, `url`, `version`, `space`, `area`, `labels`, `service`, `links`, `tags`), then
`vi-mcp docs import FILE --source NAME [--index X] [--kind company-docs|external-docs|manual] [--prune] --token-file F` (dry run first).
Since 0.70.0 FILE may also be documents and directories (PDF, DOCX, XLSX, PPTX, ODT, ODS, ODP, HTML, EPUB, EML, CSV, text; DOC/XLS/PPT/RTF
with LibreOffice): `vi-mcp docs convert DIR --out pages.jsonl` shows locally what would be sent and every refused file with its reason.
The server keeps one object per page (it chunks for search itself), sets the hashtags and the host:/topic: triggers at once, links
pages, archives the old shape of the same `source_kind:`/`page:` and pages the source dropped. An agent's token is refused.
Step by step, with checks: [docs/IMPORT.md](docs/IMPORT.md).

## Fine-tuning runbook (an agent can run it end to end)

vi-mcp trains nothing by itself. A fine-tuning run is a person's explicit decision: who decides, which host, which base model, and
which services may be paused. Ask before you start, and do not infer permission from an earlier run. Everything below was done
once end to end on 14.11.2026 (Qwen/Qwen3-0.6B, AMD Strix Halo gfx1151, ROCm). The measured numbers are from that run.

**1. Data and kit.** Never train from the live database.
- Copy the database read-only: SQLite backup API with `?mode=ro`, or `pg_dump`. Put `eval/recall.json` (the fixed question set)
  next to the copy, so the evaluation targets are held out. The kit finds it as `<db dir>/eval/recall.json`.
- Point a scratch config at the copy and build the kit:
  `VI_MCP_CONFIG=<scratch>/config.json vi-mcp finetune kit DIR --base <hf model id> --force`. `--force` is needed while the VI is
  still in the incubator.
- `run.json` → `split.stages` shows train/test/withheld rows and `test_groups` per stage. Every stage with at least 5 groups gets
  held-out groups. A stage with 0 test rows cannot be measured; say so in the report.
- The datasheet in `dataset/DATASHEET.md` lists what was held out or scrubbed and why.
- Questions: never train an object's own text as its question. The first production run did that for 96 % of its rows
  (20,066 of 20,957); the model echoed and continued Confluence pages, looped in 55 % of its answers and answered no real question
  better (blind test 14.11.2026, VI `erkenntnis:0758b794…`).
- Since 0.65.0 the server stores the training form on each knowledge object (`data.qa`: grounded pairs, one never-trained probe,
  rejections, content hash, generator version), in sleep step 8i or with `vi-mcp classify --pairs [--workers W] [--stale]`
  (`--dry-run` counts states). One definition of a good pair: `vi_mcp/qa_pairs.py`. The export trains the pairs, writes the probes
  to `probe.jsonl`, and puts every object without usable pairs into `documents.jsonl`.
- For what the server has not reached yet: `python synth_qa.py --url http://HOST/v1 --model NAME --limit N` (thinking off, no token
  cap, resumable, `synth_report.json`; it also writes one probe per document), then `vi-mcp finetune split DIR`. Measured with
  Qwen3.6-35B-A3B Q4 on the AMD gfx1151 host, 4 workers: 12 documents in 38 s, 14 pairs kept, 21 rejected.
- Check `run.json` → `split.qa_question_sources` and `split.probe` (probes of train-side objects) before training.
- The person-facing guide with every step: `docs/FINETUNING.md`.

**2. Training environment.** Use its own container on the GPU host and do not change the host's services.
- AMD: the `rocm/pytorch:<rocm>_<os>_<py>_pytorch_release_<ver>` image. Pick a tag listing your GPU arch (gfx1151 from ROCm 7.1).
  NVIDIA: a CUDA PyTorch image.
- Derive an image that installs `requirements-train.txt` with a constraints file of the image's `torch*`/`triton` versions
  (`pip freeze | grep -iE "^(torch|torchvision|torchaudio|pytorch-triton-rocm|triton)==" > keep.txt`, then
  `pip install -c keep.txt -r …`). Otherwise pip may replace the GPU torch.
- Run with the GPU devices: AMD `--device /dev/kfd --device /dev/dri --group-add <video gid> --group-add <render gid>
  --security-opt seccomp=unconfined`; NVIDIA `--gpus all`.
- Behind a proxy, pass it as build args and env. Mount a Hugging Face cache, then run training with `HF_HUB_OFFLINE=1`.
- Smoke test first:
  - `torch.cuda.is_available()` is True, also on ROCm.
  - `get_device_properties(0).gcnArchName` reports the arch.
  - An fp32 matmul agrees with a CPU fp64 reference to about 1e-3.
- Pitfalls met:
  - `docker build` failed with "permission denied" on `~/.docker/buildx/activity`. Use `DOCKER_CONFIG=<own dir>`; do not repair
    the user's files.
  - The container writes as root. Read its reports with sudo, or run it with `-u`.

**3. Memory.** On unified-memory hosts (APUs), GPU memory and RAM are one pool.
- The fp32 logits of one long example alone are `sequence × vocab × 4 bytes`: 7104 × 151936 ≈ 4.3 GB, and gradients come on top.
- Check `free -g` first. If other model servers hold the memory, stop one only with explicit permission, and only for the
  duration of the run. Record the stop: what, when, how to restart (a VI entry, `thema:offen`).
- Afterwards restart it and probe it with a trivial request, not only `/health`.

**4. Precision.** Use `--fp32` on GPUs with known bf16 problems; ROCm/TheRock issue 9198 lists bf16 bugs on gfx1151.
- The report's `precision` must say `float32`.
- A kNN-LM core also needs float32: in bfloat16 the same position's logits drift up to 0.625 between sequence lengths.
- fp32 and grouped-query models (0.69.9): transformers asks PyTorch's attention for `enable_gqa`, which in fp32 only the quadratic
  math kernel serves (+4.1 GB at 4,096 tokens). The kit repeats the key/value heads instead (`efficient_gqa_attention`, report field
  `sdpa_gqa`) — same attention, efficient kernel. Check the report says "kv heads repeated" before blaming the data for an OOM.

**5. Order of commands** (in the kit directory, inside the container):
1. `python train.py --stage sft --tokenizer-only --fp32`: no weights, a token audit of every row. Expect `rejected: {}`,
   `valid: true`.
2. `python train.py --stage sft --preflight --fp32`: the real trainer, one no-grad loss, parameters unchanged, 0 optimizer steps.
   Expect `status: preflight_passed`.
3. `python heldout_loss.py --stage sft --base-only`: optional, the base loss before training.
4. `python train.py --stage sft --fp32 --epochs E`. Choose E from the measured throughput. Later stages
   (`--stage logic|agentic|kto|dpo`) continue from `out/sft` unless `--from-base`. A kit written with `--philosophy NAME` adds the
   seed path `--stage language` (from the base) → `philosophy` (continues out/language) → `grpo` (continues out/philosophy), with
   eval/philosophy.jsonl, `phil_answers.py`, `phil_score.py` and `phil_roundtrip.py` (the prose answers by round trip with an
   independent back-translator, a control beside every number; docs/FINETUNING.md section 4b).
5. `python heldout_loss.py --stage sft`: base vs adapter on the held-out rows. This shows knowledge absorption, not task success.

Run training detached (`docker run -d …`) and watch for the end and for failures: `Traceback`, `out of memory`, `Killed`, and the
container exit code.

**6. Measured cost** (Qwen3-0.6B, LoRA r=16/α=32, fp32, batch 1, one Strix Halo GPU):
- About 310 trained tokens/s, 1–6 s per step depending on example length.
- 0.25 epoch = 5240 rows = 4.6 M tokens took 4.1 h.
- `heldout_loss.py` on 400 rows took 7 min.
- Results:
  - Held-out NLL 2.269 → 1.294 (perplexity 9.7 → 3.6).
  - Training loss 1.50 → 1.13.
  - 10.1 M trainable parameters; the adapter file is 40 MB.

Scale E to the time the person allows. A full epoch would have been about 16 h.

**7. Judging task success.** The adoption gate never uses word overlap and never uses the training loss.
- **Know what each catalog measures.** Questions about held-out documents (`eval/recall.json` targets, `split/test.jsonl`)
  measure generalization to unseen documents. Closed-book fine-tuning cannot answer them, because the model only knows what
  it trained on. Run 2 (15.11.2026) showed no gain there (p ≈ 0.1).
- **Knowledge injection is measured with a knowledge probe:** new questions about TRAINED documents that are themselves never
  trained (Allen-Zhu & Li 2309.14316; EntiGraph 2409.07431). Since 0.65.0 the kit has it: `split/probe.jsonl` (the stored probes
  of train-side objects) and `probe.py answer|judge|summarize` → `probe/probe_eval.json` (blind A/B, key apart, per-question
  writing, sign-flip test strict and lenient; the judge is named and a judge that wrote the probes is flagged).
- **What worked (run 3):** 500 trained documents, about 5 varied pairs each (`synth_qa.py --pairs 8 --more`), `--lora-rank 64`,
  4 epochs, 2,558 rows, 53 min on gfx1151 fp32.
  - Results on the 60-question probe: base 0 correct / 5 partial, run 2 (r16, 3 epochs, all rows) 4/3, run 3 7/9.
  - The sign-flip test gives strict p = 0.008 and graded p = 0.001.
  - Still: the tuned model never abstains and invents hosts and IPs (Gekhman et al. 2405.05904).
- Use a question catalog of the right kind (above). The model must never have trained on the questions themselves:
  - questions from `eval/recall.json`, whose targets and source pages are held out;
  - a seeded sample of `split/test.jsonl`;
  - a knowledge probe on trained documents.
- Write each answer pair to disk as soon as it exists, with the key in a separate file. Then a partial run can already be judged
  and a crash loses nothing.
- Keep the references with the judge; only the questions go to the GPU host.
- Generate base and tuned answers from the same loaded weights: PEFT `model.disable_adapter()` for the base.
  - Greedy decoding, thinking off, the same system prompt for both.
  - A local `generate` needs a token budget against endless loops. Mark an answer that reaches it as incomplete; never cut it
    silently.
- Randomize A/B per question and store the key apart. Judge each answer against the reference as correct, partial or wrong,
  pointwise and not as a preference. Open the key only after all judgments. Position bias and style leaks are named limits.
- Then run `evaluate.py` with the judgments: the exact clustered sign-flip test decides `decision`. The Hoeffding `lower_95` is
  only the worst-case size bound.

**8. Record and use.**
- `vi-mcp finetune record DIR` stores the run with its lineage as a model object (dataset hash, base, adapter hash, evaluation).
- To get a standalone model, run PEFT `merge_and_unload()` and save. For llama.cpp, convert to GGUF and quantize, or keep the
  adapter separate (`convert.sh` → `llama-server --lora`).
- Deploy a tuned model only with the person's approval.

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
- **The server runs no Python from callers (0.63.0).** Classes and methods of clingo-object are real Python and run where code is trusted;
  the server gets only the compiled notation. What a logic program proposes (`propose(...)`) waits in quarantine and is decided by
  someone other than its author.
- **Self-review counts, but less (0.69.3).** In an environment with one model family (only Claude) an AI must be able to check its own
  work: each instance is its own line; a confirmation of one's own object counts `memory.SELF_WEIGHT` (0.5), marked self; `vi_rate`
  stores an agent's grade of its own conversation as an agent grade (`review:self`), never a human one, and it counts for learning
  only once calibrated against human grades. The server (`vi`) never counts. Quarantine releases stay with a human or the release right.
- **Nothing disappears silently:** what is held back is counted with a reason, what is deleted leaves a tombstone. Reports name the class of a finding, never its value.
- Every change a user notices is recorded with evidence in `CHANGELOG.md`.

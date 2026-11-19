# Importing documentation into a VI

For people and for AIs. Read it top to bottom before you import anything; every step has one command and one check.
The tool behind it: `vi_doc_sync` (0.69.0). The client: `vi-mcp docs import`. The code: `vi_mcp/doc_import.py`.

## When to import, and when not

- **Import** documentation another system already keeps: a company wiki (Confluence), a vendor manual, a knowledge base's index.
  The VI then shows a page as a hint before an action it matters for, and `vi_recall` finds it.
- **Do not import** what an agent found out itself — that is `vi_learn`, one fact with its source. Do not import code — that is
  `vi-mcp index import-code`.
- **An agent never calls `vi_doc_sync`.** It needs an instance with the import right; an agent's token is refused. An agent that was
  asked to import prepares the pages file (below) and runs the client with the import token a person gave it.

## The rules the import follows (so you know what you get)

1. **One page = one object** with its whole text as Markdown. The server cuts it into search chunks itself. Only a page longer than
   200,000 characters is stored in parts ("part 2/3").
2. **The id is fixed per source and page.** Importing the same page again updates the same object; an unchanged page (same content
   hash) is skipped. It does not matter which import instance sends it.
3. **Hashtags come with the page**, so it can appear as a hint at once:
   - `source_kind:<source>`, `knowledge_kind:<company-docs|external-docs|manual>`, `page:<id>`, `space:`, `area:`;
   - the source's own labels as `label:<label>` (at most 10) and its service as `service:<name>`;
   - `host:` for hosts the VI already knows from other work and `topic:` for topics learned knowledge already uses and the title names
     — at most 5 each, derived the same way as sleep step 6b (`vi_mcp/doc_triggers.py`). No host or topic is invented.
4. **Links between pages** of the same source become edges ("doc link"), also when the linked page arrives later. At most 20 per page.
5. **The old shape is retired.** Objects of the same `source_kind:` and `page:` that this import did not write — section parts of an
   older import, a page learned with `vi_learn` — go to the long-term archive with a reason naming the new object. Nothing is deleted:
   `vi_archive` shows them, `vi_archive_restore` brings one back.
6. **Removed pages** (`--prune`, or `removed` in a sync call) are archived with a reason.
7. **Secrets are replaced** (`password=…`, keys, tokens) and counted. Visibility is always internal (never an open network).
8. **Vectors are not computed in the call.** The server's background catch-up adds them in rounds of at most `on_demand.VECTOR_MAX_S`
   seconds (and sleep step 7), not inside the import call. Search by full text works at once, by meaning once the catch-up reached the
   page. On a shared embedding service a large import still adds load for a while — import big sources outside working hours.

## Step 1 — an import instance (once, by an administrator)

```bash
sudo vi-mcp instance aikb-import --import          # prints the token ONCE; keep it in a file readable only by you (chmod 600)
sudo systemctl restart vi-mcp                       # the service reads instances at start (macOS: brew services restart vi-mcp)
```

Check: `vi-mcp docs state --source test --token-file TOKENFILE` answers `{"source": "test", "pages": 0, …}`. An agent's token answers
`vi_doc_sync needs an instance with the import right`.

## Step 2 — the pages file

One page per line (JSON Lines, UTF-8). Required: `page_id` and `markdown`. Everything else is optional but makes the page better.

```json
{"page_id": "402886068", "title": "ansible01 – inventory", "markdown": "# ansible01 – inventory\n\n## Groups\n…",
 "url": "https://wiki.example.org/pages/402886068", "version": 12, "space": "IT", "area": "it-kassel",
 "labels": ["runbook", "ansible"], "service": "ansible", "links": ["402886070"], "tags": ["topic:inventory"]}
```

- `page_id`: the source's own, stable id (a page number, an URL). Never a running number of your export: the id is how the next run
  finds the page again.
- `markdown`: the whole page. Start with `# Title`, keep the source's headings as `##`/`###`, tables as Markdown tables, code in fences.
  Do not cut the page yourself and do not add a "Source:" line — the source has its own field (`url`, `version`).
- `links`: page ids of the same source this page links to.
- `tags`: extra `kind:value` hashtags; the system kinds (`instance`, `kind`, `mode`, `source_kind`, `page`, …) are ignored.

Check: `python3 -c "import json; [json.loads(l) for l in open('pages.jsonl', encoding='utf-8')]"` raises nothing.

### Or: documents directly (0.70.0)

Instead of a pages file, give the import documents and directories; `vi-mcp docs` converts them to the same pages
(`vi_mcp/doc_formats.py`). `page_id` is the path relative to the directory, `area` its subdirectory, `labels` `format-<ext>`.

| Formats | Needs |
|---|---|
| PDF | `pypdf` (a package dependency since 0.70.0) — text per page; a scanned PDF without a text layer is refused ("needs OCR") |
| DOCX, XLSX, PPTX (Office) · ODT, ODS, ODP (OpenDocument) | nothing — read with the standard library: headings, lists, tables, links; one table per sheet, one section per slide with its notes |
| HTML, EPUB, EML (e-mail; attachments named, not imported), CSV/TSV, TXT, MD, RST | nothing |
| DOC, XLS, PPT, RTF, WPD, Pages/Numbers/Keynote | LibreOffice (`libreoffice-core-nogui` / `libreoffice-core` / `libreoffice-fresh`), converted first |

```bash
vi-mcp docs formats                                   # what is available here (pypdf? LibreOffice?)
vi-mcp docs convert ~/handbooks --out pages.jsonl     # local, no server: what would be sent, and every refused file with its reason
vi-mcp docs import ~/handbooks --source handbooks --label "Handbooks" --kind manual --token-file TOKENFILE --dry-run
```

Every file ends in one of two places: a page, or the list of refused files with a class and a reason — unknown format, needs pypdf,
needs LibreOffice, encrypted, no text, too large (over 100 MiB, or an archive that unpacks to more than 300 MiB), unreadable. The
import prints the refused files and counts them by class; `--prune` never archives the page of a file that was refused this time.
A table longer than 5,000 rows is cut and the page says so. Images are not text: `vi-mcp image FILE` stores them with a description.

## Step 3 — a dry run

```bash
vi-mcp docs import pages.jsonl --source confluence-it --label "Confluence IT" --kind company-docs \
    [--index NAME] --url https://HOST/vi-mcp/mcp --token-file TOKENFILE --dry-run
```

It prints `{"pages": …, "held_before": …, "to_send": …, "to_remove": …}` and sends nothing. `to_send` is the number of new or
changed pages. `--index` puts the pages into a special VI (e.g. `cue`, `dcx`); without it they go to `global`.

**A large external corpus** (0.70.3; e.g. a public Q&A site with hundreds of thousands of pages): mark its index as searched only when
named BEFORE the import — `vi_indexes(index="NAME", explicit=true)` — so its pages are found with `index:NAME` / `vi_recall(index=…)`
but never in a search without an index, never as a hint, and the sleep neither embeds nor labels them.

## Step 4 — the import

The same command without `--dry-run`. Add `--prune` only when the file holds the WHOLE source — every page missing from it is
archived. Add `--pause 1` on a busy server. If an older import filed the same pages under another `source_kind:` (e.g. two
manuals once imported together as `stibodx`, now the sources `cue-docs` and `dcx-docs`), name it with `--old-source-kind stibodx`, so
that their old objects are recognised as the old shape and archived. It prints the totals:

| field | meaning |
|---|---|
| `new`, `updated`, `unchanged` | page objects created, changed, skipped |
| `old_shape_archived` | older objects of the same pages retired (rule 5) |
| `removed_archived` | pages the source no longer has (rule 6) |
| `with_host`, `with_topic` | pages that got a derived `host:` / `topic:` trigger |
| `links` | edges between pages |
| `secrets_replaced` | pages in which a secret was replaced |
| `rejected` | pages refused, each with its reason (missing `page_id`, empty Markdown) |

## Step 5 — check

- `vi-mcp docs state --source confluence-it …` — `pages` equals the number of pages in your file.
- `vi_recall` with a phrase from a page finds it; `vi_object <id>` shows the whole Markdown and the hashtags.
- `vi_archive` with `filter: "source_kind:confluence-it"` lists what was retired.

## Repeat

Run the same command again whenever the source changed (a nightly job is fine): unchanged pages cost one hash comparison, changed ones
are updated in place, and with `--prune` pages deleted at the source are archived.

## After the import

Pages that are searched for or read are completed on access (0.69.2): if their triggers come from an older version, `vi_recall` and
`vi_object` derive them again at once, and the labels `answers:`/`memory:` are set or queued — what agents use is qualified first,
the rest by sleep step 6b over the following nights.

## Limits

- `topic:` triggers come from the title only (the body names too much); `tool:` triggers are never derived.
- The frequency filter of sleep step 6b (a host or topic found in too much of the documentation is no trigger) is applied at import
  only after the step ran once in the server process; until then the next sleep corrects it.
- At most 50 pages and 4,000,000 characters per call — the client batches by itself.

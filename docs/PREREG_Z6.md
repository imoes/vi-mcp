# PREREG Z6 — two-hop retrieval in the VI: title anchor + one mention hop vs today's hybrid search (goal Z6; frozen 22.11.2026 14:31 UTC by PREREG_Z6.sha256, before any test question was searched)

**How it came about (stated).** Goal Z6: questions that join two VI objects. sym-rag showed that looking up the titles a question
names plus one mention hop finds all gold paragraphs far better than embeddings (RAG-0, RAG-1c). Here the same idea is applied to the
VI on questions built from the VI's own inventory facts (vi-facts kb.lp, parsed by rules from the inventory pages, no model).
**Development (fresh questions, VMs disjoint from the test VMs):** today's search (vi_recall hybrid exactly as agents call it,
reinforce=False) finds BOTH pages in the top 4 for 7.9 % of 864 development questions (VM page 66.7 %, node page 16.0 %). Method M1
was developed in three versions on development data only, each change stated in the script:
v1 (anchor by host: hashtags) failed (node page @4 1/20) because a VM page carries its node's host tag; v2 (anchor and hop by page
titles) reached both@4 74.7 % on 864 development questions, 0 % on the English OS template; v3 (a short host name counts only when it
contains a digit — words like "system", "that" were title keys) raised that template to 84.1 % (138 development questions).
The question generator also drops VMs whose short name belongs to two inventory pages (a misspelt domain), after the split.

**Test set:** `z6_test.jsonl` — 846 questions over 141 VMs (German + English templates; relations os, gateway, ip of the VM's
Proxmox node); gold = the VM's page + the node's page. Built before any search (z6_questions.py), VMs disjoint from development.
**Arms (one private working copy of the production copy vi-prodcopy-2211, vi-mcp rel-0.70.12 code, the VI's embedding service):**
- BASE: `z6_baseline.py` — vi_recall hybrid, top 10.
- M1: `z6_hop.py` v3 — anchor = page titled with a host named in the question (digit rule), hop = pages titled with hosts
  mentioned in the anchor's text/content (≤ 5, mention order), then the hybrid list (top 30) without duplicates.
**Measure:** both gold pages in the top 4 (all-gold@4), per question.
**Hypotheses (unit = question, α 0.05; `z6_score.py`):**
- **H-Z6a (primary):** all-gold@4 M1 > BASE — exact one-sided McNemar.
- **H-Z6b (goal criterion):** M1 − BASE ≥ 10 points (point estimate), reported with the 95 % VM-clustered bootstrap CI.
- Descriptive: per relation × language; VM page @4 and node page @4 separately; @10.
**Decision:** H-Z6a and H-Z6b hold → the title-anchor + hop retrieval is a candidate for vi_recall (a vi-mcp change, the user's
decision, with its own online check); otherwise the dev gain was specific to development and Z6 needs another approach.
**Named limits:** template questions (wording close to the method's key: a named host); only inventory-page relations; gold pages
come from the same pages the method reads; one production snapshot; the digit rule fits this organisation's host naming.

**Hashes (sha256):** z6_test.jsonl 88cbd911cf303d3c9e4d4e8ee8a9f2b214a582d1d51969cb4974294821ff5b49 · z6_questions.py ff2e729c65aaf09ed16f8ed7be87e5b0dadf72e4be2bff19c85b97adb288b8f6 · z6_hop.py 3526d8b2189535e8f624f4db6b76c2b218b4634a3ea0c2cc76c4511ba39f99f2 · z6_baseline.py 17d082c188b0ae1c0f1bf293cb29591465ec4c14c6a76080abea7c350215a3d7 · z6_score.py 1df59285b36dc0b4002c4c889120e3da02d76ca30481d50c1ae160e4e105ea3c · kb.lp 0dd7f5081a83be1e7b314d73a03659feb90a24dfa19dbfabb083aa85d6c3b9c9 · vi.db 74b7d3e2a7970d3d17ddf745145a2c0db7f58e224f2025503e828e52ab89987c · 

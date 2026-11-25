# PLAN Z1 step 0b — does a ≤ 9B teacher read the facts the 0.6B readers miss? (development probe on spent fresh4)

Frozen by PLAN_Z1_step0b.sha256 before any teacher read on a GPU exists. The only teacher read so far is a CPU smoke test:
1 question, 2 paragraphs, on the 3070 host at 12:33–12:34 UTC, not part of the analysis. Coordinator OK on 25.11.2026 for 0b as a
development probe without training. The distillation itself needs the user's go.

**Why** (RESULT_Z1_step0.md): sampling the 0.6B reader re-orders values it already writes. Only 9 of 42 stated gold facts that
neither greedy reader has (21 %) appear in any of 8 samples. A stronger source of reads is the remaining lever. BabyLM allows
teachers ≤ 9B (research log, line 95).

**Questions:** the same 198 as in step 0 (groups.json 819110bb…, ids_step0.json 0ccba9b0…, in that order): 98 PREF-wrong and 100
PREF-right on fresh4.

**Teacher reader:** `q1_read_teacher.py`, a llama.cpp client using the standard library only.
- The same system message, read prompt, 2 shots, paragraphs and parser as q1_read_v2.py (d0_docs.py b70ed764).
- Temperature 0, thinking off, no token cap. The same two loop tests run on the stream; on a loop the stream is closed.
- Model: Qwen3-8B Q4_K_M (sha256 d98cdcbd…5785, as in Z5). Served by the llama.cpp server-cuda container: --n-gpu-layers 99,
  ctx 8192, parallel 1, --jinja.
- Tests:
  - A fake-server test checked the request (temperature 0, stream, no max_tokens, thinking off, 6 messages), the parsing, the loop
    stop and --stop-at.
  - The CPU smoke test gave clean fact lines without thinking traces.

**Analysis** (`eval_step0b.py`). Merges use reader_merge.py pref (b4964509); answers come from the frozen official_score.py
(7f9170e9, `--title-anchor --tiebreak shortest`). The base and R3r reads are the greedy fresh4 reads.
- **T-FIRST** (primary): pref(pref(teacher, R3r), base) — the teacher in the place a distilled reader would take.
- **M3** (descriptive): pref(pref(R3r, teacher), base).
- **T-ALONE** (descriptive): the teacher's reads only.
- **PREF** is the reference.
- **Coverage**: among the stated gold facts of the read questions that neither greedy 0.6B reader has, the share the teacher reads.
  This is the same definition as in step 0, where 42 such facts exist.
- **Self-test passed**: R3r's greedy reads given as "teacher" reproduce PREF in T-FIRST and M3 (0/98 and 100/100), with coverage 0.

**Go/no-go (fixed now; extrapolation as in step 0: gain scaled to 98, minus harm rate × 302):**
- **GO — propose the teacher distillation to the user** if all three hold: coverage ≥ 50 %, T-FIRST extrapolated net ≥ +12 per
  400, and harm ≤ 3 per 100 right.
  - Why 50 %: a distilled student at best reproduces the teacher. With less than half of the unread facts covered, the +18 that Z1
    needs is out of reach. This threshold is a judgement, stated before the data.
- **NO-GO, "teacher reads, pipeline does not convert"** if coverage ≥ 50 % but the net or harm condition fails.
- **NO-GO, teacher path closed at this size** if coverage < 50 %.
- **UNDETERMINED** if fewer than 40 questions of either group are read before the stop. The reader then resumes in a later slot.

**Hardware:** RTX 3070 slot 25.11.2026 after af's CT-S1B smoke (coordinator).
- **Start** only when all of these hold:
  - af's wait.log has "smoke runner returned" or "GAVE UP at 20:15 UTC";
  - 7a's Z4 step 0 has ended: its kit35_s43/run.log has a line matching `^(launcher exit|BUSY: |HASH-MISMATCH)` (format named by
    7a);
  - no claude-* container is running;
  - no GPU compute process except the vision server;
  - the vision server answers a chat probe.
- If none of af's lines has appeared by 20:15 UTC: do not start, and report.
- Reads stop at a question boundary at 20:45 (`--stop-at`); the slot ends by 20:50.
- EXIT trap: remove the 8B container, restart the vision server, log a chat probe.

**Limits:**
- fresh4 is spent, so this is development evidence only.
- One teacher model and quantisation (Q4) with greedy reads and the 0.6B reader's prompt; the teacher prompt is not tuned.
- The extrapolation is an estimate.
- The teacher reading a fact does not mean a 0.6B student will learn it.

**Hashes (sha256):** in PLAN_Z1_step0b.sha256, for q1_read_teacher.py, eval_step0b.py, d0_docs.py and this file.

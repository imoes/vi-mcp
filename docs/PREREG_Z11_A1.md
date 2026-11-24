# PREREG Z11-1, amendment 1: a secondary question set on the 440 non-probe documents

Status: FROZEN 22.11.2026 (date -u at commit), by `docs/PREREG_Z11_A1.sha256`, after the question set was complete and before any arm answered it.
It changes nothing in the primary pre-registration (`docs/PREREG_Z11.md`) and uses its frozen parameters.

## Why

The primary probe has n = 60 and a baseline of 7 correct. It can only detect a lead of about 6–8 questions. A second set of
never-trained questions about the other trained documents raises n for the same comparison.

## How the questions were written (before any arm answered)

- **Documents.** The 440 trained documents that have no primary probe question.
- **Writer.** Qwen3.6-35B-A3B, GGUF UD-Q4_K_XL from `unsloth/Qwen3.6-35B-A3B-GGUF` at commit a483e9e6 (LFS sha256
  707a55a8…4450), served by llama.cpp `server-cuda` (build 12627, commit 225a5345b, image digest f46a7938…) on a RunPod A40
  (pod ct5nbwy1t9t7h9, Secure, EU-SE-1). Run 3 used the same model and quantisation name, but its local file is an older upload
  (22,853,663,008 bytes vs 22,360,456,160), so the writer is not byte-identical. This is a named limit.
- **Rules.** The run-3 kit's own prompt, request body and grounding check (`kit4/synth_qa.py`, sha256 b78258af…, imported
  unchanged): 3 pairs asked per document, temperature 0.3, thinking off, no token cap. A pair is kept only if:
  - it passes `check()`: grounded, names its subject, not copied from the document's beginning;
  - its question has word Jaccard < 0.5 to every trained question of that document (the probe's hold-out rule).
- **Selection.** The first kept pair per document is the question. A document without one is asked again, at most 3 attempts
  in all (fixed at 12:53 UTC, after the first pass, before any arm answered). Script: `scripts/z11/secondary.py`.
- **Data path.** The pod held only the 440 documents, the trained questions without their answers, and the scripts. They were
  copied by scp through the jump host. The questions and references come back the same way. The pod is deleted afterwards and
  `list-pods` checks that it is gone.

## The set as written (22.11.2026 12:51–13:12 UTC)

- Pass 1: 440 documents asked, 176 kept, 622 s. Pass 2: 264 asked, 79 kept, 366 s. Pass 3: 185 asked, 42 kept, 254 s.
- Rejected over all passes:

  | Reason | Count |
  |---|---|
  | not grounded in the document | 1,492 |
  | too close to a trained question | 694 |
  | refers to the document instead of its subject | 27 |
  | length | 1 |
  | failed request (JSONDecodeError) | 21 |

- **Result:** 297 questions on 297 different documents. None is a probe document. The largest word Jaccard to a trained question
  of the same document is 0.478.
  - `secondary_questions.jsonl`: sha256 8436b156…88e37bf5c.
  - `secondary_refs.jsonl`: sha256 8155e408a5656c3dbdda3011e591791ddac1c957dd5d95d8cecfa35f8ab71dd2.
- The data directory on the pod was removed (13:12:45 UTC) and the pod deleted (13:12:50 UTC). `list-pods` no longer shows
  either Z11 pod.
- The first attempt, pod 57ro72xntxpfht (RTX 3090 Community), was deleted at 12:48:56 UTC before it wrote anything. Its host had
  no public IP, so there was no direct SSH.
- Estimated cost: about $0.02 + $0.24.
- **Deviation from the standing RunPod rule** (cheapest free Community card, and on 20.11 the user preferred waiting over
  Secure): the A40 was a Secure pod at $0.59/h. The only Community card with enough memory and stock at 12:42 UTC was the RTX
  3090, and its host had no public IP. The coordinator's condition was "no public HTTP port, transfer by scp", which needs a
  direct SSH address, and Secure hosts have public IPs. The cost of the deviation was about $0.24.

## Use

- **Arms and parameters.** The arms are B, L, K, R and KR with the frozen parameters of the primary (`frozen_params.json`).
  B3 and L3 do not exist for this set.
- **Hardware.** The answers may be generated on a rented GPU (RunPod, same rules as above: SSH through the jump host only, no
  HTTP port, data deleted with the pod, cost reported) instead of the CPU workstation. They use the identical script
  (`scripts/z11/z11.py answer`, same commit), float32, greedy decoding and the 2,048-token budget. All five arms of this set run on
  the same hardware, so a CPU/GPU difference cannot appear as an arm effect. The report names the hardware per arm and set.
- **Judging.** The same rubric and blind procedure as the primary. The reference is the writer's answer plus the document.
- **Hypotheses** (exact one-sided sign test on strict correct, α 0.05):
  - **H1s:** K > B.
  - **H3s:** KR > R.
  - K vs. L is reported two-sided.
  - The Z11 goal criterion is evaluated on the primary probe only. This set is supporting evidence, reported separately, never
    pooled into the primary test.
- **Leakage named.** The kNN parameters were tuned on 374 validation rows drawn from these same 440 documents. They were
  rows, not these questions. The tuning chose 3 numbers, not content.

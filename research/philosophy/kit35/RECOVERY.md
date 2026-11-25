# kit35 recovery (25.11.2026)

`rule_prose.py` (sha256 c1cd0a755f9be3e8…) is the translator `build_kit35.py` imports (`rp.program(code)` → literal English prose).
It was written on 20.11.2026 at 02:44:12 UTC into a session scratchpad and never committed; a host reboot on 24.11 deleted it. The
coordinating session recovered it byte for byte from its own transcript (one Write, no later edit) and it is committed here so the
kit can be rebuilt.

**Check (25.11.2026):** `build_kit35.py` (73cc9a6) with this file, kollektiv 1.2.0 from tag v0.66.0 (`clingo_object/philosophy_kollektiv.py`)
and kit34 from the GPU host rebuilds `kit35/split/train.jsonl` with sha256 `da1da2afb59c360f06a0039404bbfed2666564642afacc0dd23dfab82e9d4d04` —
exactly the `dataset_sha256` run 35's `train.log` records for stage A. Stage B (`logic.train.jsonl`) is kit34's file unchanged.
An independent reconstruction of the translator from kit34's 600 renamed-seed rows reproduces all 600 kit34 rows and all 600 kit35
synonym rows as well.

Inputs the builder expects (paths are set at the top of `build_kit35.py`): `S/src066/clingo_object/philosophy_kollektiv.py`
(= `git show v0.66.0:clingo_object/philosophy_kollektiv.py`), `kit34/` next to the builder, `syn35.json`, and `clingo_object` from a
checkout whose `clingo_prose.py` is unchanged since 18.11.2026 (8365dd0).

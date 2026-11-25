# Public sanitizing of the research branch (25.11.2026)

This branch is public. Before the push of 25.11.2026 the research history (175 local commits) was squashed into one commit, and
internal names were replaced by placeholders: the user name and session names (`<user>`, `session-NN`), scratchpad paths
(`<scratchpad>`, `<scratchpad-path>`), the admin account (`<admin>`), GPU hosts (`gpu-host-N`), VM host names (`vmhostNNNN`) and the
workstation's short name (`workstation`). Public data (2Wiki answers such as "Marvin Miller") was left unchanged.

The files below differ from the versions that frozen hash lists (prereg `.sha256` files, RAW lists) name. The original bytes and the full
commit history are kept locally (branch `sr-full-history-2511`, not pushed); a check against a frozen hash uses that copy.

| file | sha256 original (local) | sha256 public |
|---|---|---|
| `docs/GOALS.md` | 8fb44cb27652bc42… | 249156ef5aaa326a… |
| `docs/PLAN_R2.md` | 7bc96aac2ee8d358… | aa44f99268425b2e… |
| `docs/PREREG_G8d1.md` | f19c4382cb323c48… | 1919c3692003fb5d… |
| `docs/SYMBOLIC_REGRESSION.md` | 2788d1f59e31ea68… | 0c5252de0181eb9c… |
| `research/philosophy/kit35/build_kit35.py` | 1356a1833742c0e2… | bd5057b3128efaff… |
| `research/philosophy/kit35/rule_prose.py` | c1cd0a755f9be3e8… | 68408f8929494411… |
| `research/symbolic_regression/a2/PROTOCOL_A2_amendment1.md` | d4acbe6ef0588fe4… | 6279b925349a4bdd… |
| `research/symbolic_regression/g8d/d1_collect.json` | a7f9b618e63fce49… | b4d9e0dffb7e8c45… |
| `research/symbolic_regression/g8d/d1_collect_final.json` | 7ab270be8f79b37c… | 258815043b39cf01… |
| `research/symbolic_regression/q1/results_levers_fresh.json` | 52582e4585e66f49… | b8cbf7d81d539b18… |
| `research/symbolic_regression/q1/stated_recall_dev400.json` | 42c37f719ec5d534… | 54607f9a3b9a871f… |
| `research/z6/z6_hop.py` | 3526d8b2189535e8… | f125094a125164dd… |

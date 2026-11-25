"""PREREG_binder amendment 1, H-BR3: binder_cover on fresh kinship tasks (fresh arm, random symbols) — one-sided 95 % Clopper-Pearson
lower bound of the solved share > 0.90. usage: binder_cover_test.py COVER_OUTPUT.json (binder_cover.py's printed JSON)"""
import json
import sys

import binder_test as T

d = json.load(open(sys.argv[1]))["all"]
lo = T.cp_lower(d["solved"], d["n"])
print(json.dumps({"H_BR3": {"solved": d["solved"], "n": d["n"], "cp_lower_95": lo, "holds": lo > 0.90, "mean_calls": d["mean_calls"]}}))

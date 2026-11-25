"""Kit 36 (docs/PREREG_kit36.md, goal Z4): kit35 plus two row groups.

A  member-cue contrast rows (stage B, logic.train.jsonl): run 35 reads the held-out sentence "Speaking for claim sN: member X,
   source O." as author(sN, X) when X is also sN's author (FINETUNING_PAPER §5.34). In kit34's training text "member" marks author
   3,112 times and line 1,312 times. A row of group A is an existing judge/pressure training row of a self-supporting world (X is the
   author of sN AND gives a line on sN) in which BOTH sentences are rewritten with a new "member" phrasing family M — the author
   sentence with an M-author template and the line sentence with an M-line template — so the cue word "member" occurs on both sides
   of the decision in one situation (Kaushik et al. 1909.12434: both sides of a minimal pair in training). The assistant target is
   the original row's target unchanged (the facts do not change, only their wording). The original row stays in the kit.
   The held-out test template (RENDER_TEST line "Speaking {w1} claim {0}: member {3}, source {2}.") and its generator are never
   used: no M template contains "Speaking", the colon pattern "claim {0}:", or any RENDER_TEST template (asserted below).
B  P7 counterfactual blocks (stage A, train.jsonl): run 35 keeps P7 at 5/8 on p67ablate — when one member of the definitional pair
   verified/unverified is renamed, the model writes the seed's own pair. A row of group B is the P7 block with the SEED's names but
   one minimal edit to one rule (drop or add a negation, swap the two arguments of verified/unverified, replace source by
   another P7 predicate, or flip obligatory <-> forbidden), translated literally by rule_prose.program — the prose must follow the
   edited rule, not the remembered seed. No edited rule equals a seed rule or any rule in an eval file (EVAL_FORBIDDEN as kit35).
Row seeds 3612 (A) and 3613 (B); 300 rows each (B: 150 explain + 150 write). Training as kit35 (rank 64, fp32, lr 2e-4, 2 epochs).
usage: python3 build_kit36.py KIT35_DIR OUT_DIR   (KIT35_DIR: the rebuilt kit35, stage A sha256 da1da2af…)"""
import json
import random
import re
import shutil
import sys
from pathlib import Path

FT = Path(__file__).parent
sys.path.insert(0, str(FT.parent / "kit35"))
import rule_prose as rp  # noqa: E402  (committed in kit35/, sha256 c1cd0a75…)

SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
SYSTEM = "You are a member of an AI collective and work strictly by its philosophy."
N_A, N_B = 300, 300
WORDS = {"pos": "for", "neg": "against"}
M_AUTHOR = ["Member {1} made statement {0}.", "Statement {0} is by member {1}.", "Member {1} is the one who stated {0}."]
M_LINE = ["Member {3} gives evidence {w1} statement {0}, drawn from origin {2}.", "Member {3} argues {w1} {0}; the origin is {2}.",
          "On {0}, member {3} testifies {w1} it, citing origin {2}."]
HELD_OUT_LINE = "Speaking {w1} claim {0}: member {3}, source {2}."
for t in M_AUTHOR + M_LINE:
    assert "Speaking" not in t and "claim {0}:" not in t and t != HELD_OUT_LINE, t

P7 = ["counts(S, P, R) <= source(S, P, R, K) & verified(R, S)",
      "unverified(R, S) <= source(S, P, R, K) & ~verified(R, S)",
      "obligatory(verify(R, S)) <= unverified(R, S)",
      "forbidden(cite(R, S)) <= unverified(R, S)"]
SEED_P7 = set(P7)


def fact_lines(text):
    return {int(m.group(1)): re.sub(r"\s", "", m.group(2))
            for m in re.finditer(r"^\s*\[(\d+)\]\s*(.+)$", text.split("Statements:")[0], re.M)}


def group_a(rows, rnd):
    cands = []
    for r in rows:
        if r["meta"].get("task") not in ("judge", "pressure"):
            continue
        u, a = r["messages"][1]["content"], r["messages"][2]["content"]
        facts = fact_lines(a)
        authors = {}
        for i, f in facts.items():
            m = re.fullmatch(r"author\((\w+),(\w+)\)", f)
            if m:
                authors.setdefault((m.group(1), m.group(2)), i)
        pairs = []
        for i, f in facts.items():
            m = re.fullmatch(r"line\((\w+),(pos|neg),(\w+),(\w+)\)", f)
            if m and (m.group(1), m.group(4)) in authors:
                pairs.append((authors[(m.group(1), m.group(4))], i, m.groups()))
        if pairs:
            cands.append((r, pairs))
    out = []
    for r, pairs in rnd.sample(cands, N_A):
        ai, li, (s, p, o, x) = rnd.choice(pairs)
        u = r["messages"][1]["content"]
        new_a = rnd.choice(M_AUTHOR).format(s, x)
        new_l = rnd.choice(M_LINE).format(s, p, o, x, w1=WORDS[p])
        u2 = re.sub(rf"^\[{ai}\] .+$", f"[{ai}] {new_a}", u, count=1, flags=re.M)
        u2 = re.sub(rf"^\[{li}\] .+$", f"[{li}] {new_l}", u2, count=1, flags=re.M)
        assert u2 != u and u2.count("\n") == u.count("\n")
        row = json.loads(json.dumps(r))
        row["messages"][1]["content"] = u2
        row["meta"] = {**r["meta"], "h15": "member_cue_contrast", "seed": 3612}
        out.append(row)
    return out


def p7_edits():
    """Every single minimal edit of one P7 rule (deterministic list)."""
    edits = []
    for k, rule in enumerate(P7):
        variants = set()
        if "~verified" in rule:
            variants.add(rule.replace("~verified", "verified"))
        elif "& verified" in rule:
            variants.add(rule.replace("& verified", "& ~verified"))
        variants.add(re.sub(r"(?<![a-z_])verified\(R, S\)", "verified(S, R)", rule))   # not inside "unverified"
        variants.add(re.sub(r"(?<![a-z_])unverified\(R, S\)", "unverified(S, R)", rule))
        variants.add(rule.replace("source(S, P, R, K)", "counts(S, P, R)"))
        if rule.startswith("obligatory("):
            variants.add(rule.replace("obligatory(", "forbidden(", 1))
        if rule.startswith("forbidden("):
            variants.add(rule.replace("forbidden(", "obligatory(", 1))
        for v in sorted(variants):
            head_pred = re.match(r"(?:\w+\()?(\w+)\(", v.split("<=")[0].strip()).group(1)
            if v != rule and not re.search(rf"(?<![a-z_]){head_pred}\(", v.split("<=")[1]):   # no self-referential rule
                edits.append((k, v))
    return edits


def group_b(rnd, forbidden):
    from clingo_object import notation as n
    from clingo_object.clingo_prose import normal_rule
    edits = [(k, v) for k, v in p7_edits() if normal_rule(v) not in forbidden and v not in SEED_P7]
    rows = []
    for i in range(N_B):
        k, v = rnd.choice(edits)
        rules = list(P7)
        rules[k] = v
        if rnd.random() < 0.5:
            rules = rules[rnd.randint(0, 1):]          # a shorter block keeps the edited rule's neighbours varied
            if v not in rules:
                rules = [v] + rules
        code = "\n".join(rules)
        n.translate(code)
        prose = rp.program(code)
        task = "explain_rules" if i < N_B // 2 else "write_rules"
        user = (f"[EXPLAIN_RULES]\nTranslate these clingo-object rules into plain English:\n{code}" if task == "explain_rules"
                else f"[WRITE_RULES]\nWrite these rules in clingo-object notation:\n{prose}")
        rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                                  {"role": "assistant", "content": prose if task == "explain_rules" else code}],
                     "meta": {"task": task, "h15": "p7_counterfactual_block", "edit_rule": k, "seed": 3613}})
    return rows, len(edits)


def eval_forbidden(src):
    from clingo_object.clingo_prose import normal_rule
    out = set()
    for f in sorted((src / "eval").glob("*.jsonl")):
        for line in open(f):
            e = json.loads(line)
            for t in [m["content"] for m in e.get("messages", [])] + [json.dumps(e.get("meta", {}))]:
                for x in re.split(r"\\n|\n", t):
                    if "<=" in x:
                        try:
                            out.add(normal_rule(x.strip().strip('"')))
                        except Exception:  # noqa: BLE001
                            pass
    return out


def main():
    forbidden = eval_forbidden(SRC)
    a_rows = group_a([json.loads(l) for l in open(SRC / "split/logic.train.jsonl")], random.Random(3612))
    b_rows, n_edits = group_b(random.Random(3613), forbidden)
    eval_text = "".join(open(f).read() for f in sorted((SRC / "eval").glob("*.jsonl")))
    leak_a = sum(r["messages"][1]["content"] in eval_text for r in a_rows)
    assert leak_a == 0, leak_a
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT, ignore=shutil.ignore_patterns("out", "*.log", "*_answers.jsonl", "run.log", "launcher.out"))
    base_a = [json.loads(l) for l in open(SRC / "split/train.jsonl")]
    base_b = [json.loads(l) for l in open(SRC / "split/logic.train.jsonl")]
    mixed_a, mixed_b = base_a + b_rows, base_b + a_rows
    random.Random(362).shuffle(mixed_a)
    random.Random(363).shuffle(mixed_b)
    (OUT / "split/train.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in mixed_a), encoding="utf-8")
    (OUT / "split/logic.train.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in mixed_b), encoding="utf-8")
    b = json.loads((OUT / "BUILD31.json").read_text())
    b["h15"] = {"group_a_rows_stage_b": len(a_rows), "group_b_rows_stage_a": len(b_rows), "p7_edits_allowed": n_edits,
                "stage_a_rows": len(mixed_a), "stage_b_rows": len(mixed_b), "row_seeds": [3612, 3613],
                "m_author": M_AUTHOR, "m_line": M_LINE, "held_out_line_template_unused": HELD_OUT_LINE}
    (OUT / "BUILD31.json").write_text(json.dumps(b, indent=1, ensure_ascii=False))
    print(json.dumps(b["h15"], indent=1))
    print("--- A example\n" + a_rows[0]["messages"][1]["content"][-600:])
    print("--- B example\n" + b_rows[0]["messages"][1]["content"] + "\n-> " + b_rows[0]["messages"][2]["content"])


if __name__ == "__main__":
    main()

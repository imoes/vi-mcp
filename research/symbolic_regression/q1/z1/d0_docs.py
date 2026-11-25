"""D0 — can the (untrained) model understand a Wikipedia paragraph and give it back? Baseline before any training.
Items: 2WikiMultiHopQA dev (Ho et al. 2020, Apache-2.0): every gold supporting paragraph with the evidence triples whose subject is
that paragraph's entity. Three steps per paragraph, Qwen3-0.6B, greedy, thinking off, the same system prompt:
  1 READ    paragraph → facts   `relation("Subject", "Object").` over the 34 relations of the data set (listed in the prompt)
  2 WRITE   own facts → English text
  3 REREAD  that text → facts again
Scores (score_d0 below):
  understand = recall/precision of the gold triples in READ (predicate equal, object equal after normalisation)
  reproduce  = recall of the gold triples in REREAD (the facts survive the round trip document → facts → text → facts)
  stable     = Jaccard of (predicate, object) between READ and REREAD (the model's own round trip)
Generation budget 384 new tokens per call; an output that reaches it is marked "incomplete" (never cut silently).
usage: d0_docs.py DEV.json OUT.jsonl [--n 200] [--seed 7] [--model Qwen/Qwen3-0.6B] [--adapter DIR]   (then: d0_docs.py --score OUT.jsonl)"""
import argparse
import json
import random
import re
import sys
import time
import unicodedata

RELS = ['director', 'date of birth', 'father', 'date of death', 'publication date', 'country of citizenship', 'place of birth', 'spouse',
        'mother', 'place of death', 'country of origin', 'country', 'performer', 'composer', 'educated at', 'place of burial', 'employer',
        'inception', 'award received', 'child', 'sibling', 'cause of death', 'founded by', 'producer', 'publisher', 'occupation', 'creator',
        'has part', 'editor', 'presenter', 'manufacturer', 'student of', 'doctoral advisor', 'record label']
PRED = {r: r.replace(" ", "_") for r in RELS}
SYSTEM = "You translate between English text and logic facts precisely. Never invent facts that the text does not state."
# two worked examples from the TRAIN split (written by hand from the paragraph; every fact is stated in the text) — --shots 2
SHOTS = [
    ("The Love Route", "The Love Route is a 1915 American Western silent film directed and written by Allan Dwan based upon a play by "
     "Edward Henry Peple. The film stars Harold Lockwood, Winifred Kingston, Donald Crisp, Jack Pickford, Dick La Reno, and Juanita "
     "Hansen. The film was released on February 25, 1915, by Paramount Pictures.",
     'director("The Love Route", "Allan Dwan").\npublication_date("The Love Route", "February 25, 1915").\n'
     'country_of_origin("The Love Route", "United States").',
     "The Love Route is a film from the United States directed by Allan Dwan and released on February 25, 1915."),
    ("Diane Gilliam Fisher", "Diane Gilliam Fisher( born 1957) is an American poet. She is author of several poetry collections, most "
     "recently,\" Kettle Bottom\"( Perugia Press, 2004). Fisher was born and raised in Columbus, Ohio. She earned her bachelor's and "
     "master's degrees in Spanish and a Ph.D. in romance languages from Ohio State University, and an M.F.A. in creative writing from "
     "Warren Wilson College. She lives in Brimfield, Ohio.",
     'date_of_birth("Diane Gilliam Fisher", "1957").\ncountry_of_citizenship("Diane Gilliam Fisher", "American").\n'
     'occupation("Diane Gilliam Fisher", "poet").\nplace_of_birth("Diane Gilliam Fisher", "Columbus, Ohio").\n'
     'educated_at("Diane Gilliam Fisher", "Ohio State University").\neducated_at("Diane Gilliam Fisher", "Warren Wilson College").',
     "Diane Gilliam Fisher, born in 1957 in Columbus, Ohio, is an American poet. She was educated at Ohio State University and at "
     "Warren Wilson College."),
]
FACT = re.compile(r'([a-z_]+)\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)')


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def facts(text):
    return {(p, norm(o)) for p, _s, o in FACT.findall(text) if p in PRED.values()}


def items(dev_path, n, seed):
    d = json.load(open(dev_path))
    rnd = random.Random(seed)
    rnd.shuffle(d)
    out, seen = [], set()
    for x in d:
        ctx = {t: " ".join(s) for t, s in x["context"]}
        for title in dict.fromkeys(t for t, _ in x["supporting_facts"]):
            if title in seen or title not in ctx:
                continue
            ent = norm(title)
            gold = [(PRED[r], norm(o)) for s, r, o in x["evidences"] if r in PRED and (norm(s) in ent or ent in norm(s))]
            if not gold:
                continue
            seen.add(title)
            out.append({"id": f"{x['_id']}:{title}", "title": title, "text": ctx[title], "gold": sorted(set(gold))})
            if len(out) >= n:
                return out
    return out


def score(path):
    rows = [json.loads(l) for l in open(path)]
    tot = {"n": len(rows), "gold": 0, "read_hit": 0, "read_facts": 0, "read_ok": 0, "reread_hit": 0, "incomplete": 0, "jacc": 0.0}
    for r in rows:
        g = {tuple(x) for x in r["gold"]}
        a, b = facts(r["read"]), facts(r["reread"])
        tot["gold"] += len(g); tot["read_hit"] += len(g & a); tot["reread_hit"] += len(g & b)
        tot["read_facts"] += len(a)
        golds_obj = {o for _, o in g}
        tot["read_ok"] += sum(1 for p, o in a if (p, o) in g)
        tot["jacc"] += (len(a & b) / len(a | b)) if (a | b) else 1.0
        tot["incomplete"] += sum(r.get("incomplete", {}).values())
    res = {"paragraphs": tot["n"], "gold_facts": tot["gold"],
           "understand_recall": round(tot["read_hit"] / max(1, tot["gold"]), 4),
           "understand_precision_vs_gold_only": round(tot["read_ok"] / max(1, tot["read_facts"]), 4),
           "reproduce_recall": round(tot["reread_hit"] / max(1, tot["gold"]), 4),
           "own_round_trip_jaccard": round(tot["jacc"] / max(1, tot["n"]), 4), "incomplete_outputs": tot["incomplete"]}
    # speed and size per step (user 20.11.2026: tokens/second and the number of tokens per question/answer belong in every statistic)
    def dist(v):
        v = sorted(v)
        return {"mean": round(sum(v) / len(v), 2), "median": v[len(v) // 2], "p90": v[int(0.9 * (len(v) - 1))], "max": v[-1]} if v else {}
    perf = {}
    for step in ("read", "write", "reread"):
        st = [r["stats"][step] for r in rows if "stats" in r]
        if st:
            perf[step] = {"prompt_tokens": dist([s["prompt_tokens"] for s in st]), "answer_tokens": dist([s["answer_tokens"] for s in st]),
                          "tokens_per_second": dist([s["tokens_per_second"] for s in st if s["tokens_per_second"]]),
                          "seconds": dist([s["seconds"] for s in st])}
    if perf:
        allst = [r["stats"][k] for r in rows if "stats" in r for k in ("read", "write", "reread")]
        perf["all_calls"] = {"calls": len(allst), "answer_tokens_total": sum(s["answer_tokens"] for s in allst),
                             "seconds_total": round(sum(s["seconds"] for s in allst), 1),
                             "tokens_per_second_overall": round(sum(s["answer_tokens"] for s in allst) / max(1e-9, sum(s["seconds"] for s in allst)), 2)}
        res["performance"] = perf
    print(json.dumps(res))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dev", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--n", type=int, default=200); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--model", default="Qwen/Qwen3-0.6B"); ap.add_argument("--adapter", default="")
    ap.add_argument("--score", default="")
    ap.add_argument("--shots", type=int, default=2, help="worked examples from the train split in the prompt (0 or 2)")
    a = ap.parse_args()
    if a.score:
        score(a.score); return
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float32).to("cuda" if torch.cuda.is_available() else "cpu")
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()
    rels = ", ".join(PRED.values())

    def read_prompt(text, title):
        return (f"Text:\n{text}\n\nWrite every fact the text states about \"{title}\" as lines "
                f"relation(\"Subject\", \"Object\"). using only these relations: {rels}. Nothing else.")

    def write_prompt(facts_):
        return f"Facts:\n{facts_}\n\nWrite a short English paragraph that states exactly these facts and nothing else."

    def ask(user, kind):
        msgs = [{"role": "system", "content": SYSTEM}]
        for title, text, fx, para in SHOTS[:a.shots]:
            if kind == "read":
                msgs += [{"role": "user", "content": read_prompt(text, title)}, {"role": "assistant", "content": fx}]
            else:
                msgs += [{"role": "user", "content": write_prompt(fx)}, {"role": "assistant", "content": para}]
        msgs.append({"role": "user", "content": user})
        text = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, tokenize=False)
        ids = tok(text, return_tensors="pt", add_special_tokens=False).to(model.device)  # as the kit's phil_answers_file.py
        if model.device.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=384, do_sample=False, eos_token_id=tok.eos_token_id)
        if model.device.type == "cuda":
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        new = out[0, ids["input_ids"].shape[1]:]
        stat = {"prompt_tokens": int(ids["input_ids"].shape[1]), "answer_tokens": int(len(new)), "seconds": round(dt, 4),
                "tokens_per_second": round(len(new) / dt, 2) if dt else None}
        return tok.decode(new, skip_special_tokens=True).strip(), len(new) >= 384, stat
    done = set()
    try:
        done = {json.loads(l)["id"] for l in open(a.out)}
    except FileNotFoundError:
        pass
    with open(a.out, "a") as f:
        for it in items(a.dev, a.n, a.seed):
            if it["id"] in done:
                continue
            read, i1, s1 = ask(read_prompt(it["text"], it["title"]), "read")
            text, i2, s2 = ask(write_prompt(read), "write")
            reread, i3, s3 = ask(read_prompt(text, it["title"]), "read")
            f.write(json.dumps({**it, "read": read, "written": text, "reread": reread,
                                "incomplete": {"read": i1, "write": i2, "reread": i3},
                                "stats": {"read": s1, "write": s2, "reread": s3}}, ensure_ascii=False) + "\n")
            f.flush()
    score(a.out)


if __name__ == "__main__":
    main()

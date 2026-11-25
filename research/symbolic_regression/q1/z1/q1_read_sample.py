"""Z1 step 0 (25.11.2026, development probe on spent fresh4; PROPOSAL_Z1.md): q1_read_v2.py (sha 5c6e9c6d…) with SAMPLED reads.
Changes against q1_read_v2.py, nothing else: (1) --ids FILE restricts the questions to a JSON list of ids and reads them in that list's order; (2) per paragraph K samples in ONE generate call (num_return_sequences=K, do_sample=True, temperature,
top_p, top_k from the command line, torch seed derived from sha256(seed|id|title)), so K reads cost about one batched call; (3) the
loop detector stops each sequence on its own (a per-row bool tensor; finished rows are padded), the same two loop tests as before;
(4) output per question: {"id","type","samples":[{"k":k,"reads":[...]}]} with k = 1..K, each read in q1_read_v2's format.
Still: thinking off, NO token cap (bounded only by max_position_embeddings), the same prompt, system message, shots and parser.
Original docstring:
Q1 step 3, stage A (GPU): READ the gold supporting paragraphs of 2Wiki dev questions into facts with Qwen3-0.6B, so stage B
(q1_pipeline_score.py, clingo on another host) answers the questions from READ facts instead of gold evidence.
Sample: N questions per type (compositional, comparison, inference, bridge_comparison), seed fixed. Per question every gold
supporting paragraph is read with the D0/R1 read prompt (byte-identical to d0_docs.py) about its title.
Generation: greedy, thinking off, NO token cap — bounded only by the model's context size (max_position_embeddings). The one stop
besides EOS is a LOOP detector, not a budget: when one complete output line appears for the third time the model is cycling (the
untrained D0 reader listed all 34 relations with "not specified" and repeated lines in 15 of its 28 capped reads); such a stop is
recorded as stopped_repetition. Stats per call: prompt tokens, answer tokens, seconds, tokens/s.
--goal-relations: the read prompt lists only the relations of the question's goal (from the gold evidence, as everywhere in step 3)
instead of all 34 — goal-directed reading, same prompt format.
usage: q1_read.py DEV.json OUT.jsonl [--per-type 100] [--seed 11] [--adapter DIR] [--shots 0|2] [--model Qwen/Qwen3-0.6B] [--goal-relations]
usage (this file): q1_read_sample.py DEV.json OUT.jsonl --ids IDS.json --samples K --temperature T --top-p P --top-k N --sample-seed S [same options]"""
import argparse
import hashlib
import json
import random
import time

from d0_docs import FACT, PRED, SHOTS, SYSTEM

INV = {v: k for k, v in PRED.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dev"); ap.add_argument("out")
    ap.add_argument("--per-type", type=int, default=100); ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--adapter", default=""); ap.add_argument("--shots", type=int, default=0)
    ap.add_argument("--model", default="Qwen/Qwen3-0.6B")
    ap.add_argument("--goal-relations", action="store_true")
    ap.add_argument("--ids", required=True); ap.add_argument("--samples", type=int, required=True)
    ap.add_argument("--temperature", type=float, required=True); ap.add_argument("--top-p", type=float, required=True)
    ap.add_argument("--top-k", type=int, required=True); ap.add_argument("--sample-seed", type=int, required=True)
    a = ap.parse_args()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    DEV = "cuda" if torch.cuda.is_available() else "cpu"
    sync = torch.cuda.synchronize if DEV == "cuda" else (lambda: None)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float32).to(DEV)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()
    ctx = model.config.max_position_embeddings
    from transformers import StoppingCriteria, StoppingCriteriaList

    class LineLoop(StoppingCriteria):
        """stop when a complete output line occurs for the 3rd time (checked every 16 tokens)"""
        def __init__(self, start, rows):
            self.start, self.hit = start, [False] * rows

        def looped(self, row_ids):
            text = tok.decode(row_ids, skip_special_tokens=True)
            tail = text[-6000:]  # 21.11.2026: a loop INSIDE one line (block of 8-2000 chars repeated 3x at the end) is a loop too
            if any(tail[-L:] == tail[-2 * L:-L] == tail[-3 * L:-2 * L] for L in range(8, min(2000, len(tail) // 3) + 1)):
                return True
            lines = text.split("\n")[:-1]
            c = {}
            for l in lines:
                l = l.strip()
                if l:
                    c[l] = c.get(l, 0) + 1
                    if c[l] >= 3:
                        return True
            return False

        def __call__(self, input_ids, scores, **kw):
            done = torch.zeros(input_ids.shape[0], dtype=torch.bool, device=input_ids.device)
            n = input_ids.shape[1] - self.start
            if n == 0 or n % 16:
                return done
            for r in range(input_ids.shape[0]):
                if not self.hit[r] and self.looped(input_ids[r, self.start:]):
                    self.hit[r] = True
                done[r] = self.hit[r]
            return done
    rels = ", ".join(PRED.values())

    def read_prompt(text, title, relations=None):
        return (f"Text:\n{text}\n\nWrite every fact the text states about \"{title}\" as lines "
                f"relation(\"Subject\", \"Object\"). using only these relations: {relations or rels}. Nothing else.")

    def read(text, title, relations=None, seed=0):
        msgs = [{"role": "system", "content": SYSTEM}]
        for t_, x_, fx, _p in SHOTS[:a.shots]:
            msgs += [{"role": "user", "content": read_prompt(x_, t_)}, {"role": "assistant", "content": fx}]
        msgs.append({"role": "user", "content": read_prompt(text, title, relations)})
        s = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, tokenize=False)
        ids = tok(s, return_tensors="pt", add_special_tokens=False).to(DEV)
        loop = LineLoop(ids["input_ids"].shape[1], a.samples)
        torch.manual_seed(seed)
        sync(); t0 = time.perf_counter()
        with torch.no_grad():
            out = model.generate(**ids, max_length=ctx, do_sample=True, temperature=a.temperature, top_p=a.top_p, top_k=a.top_k,
                                 num_return_sequences=a.samples, eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id,
                                 stopping_criteria=StoppingCriteriaList([loop]))  # no token cap
        sync(); dt = time.perf_counter() - t0
        res = []
        for r in range(a.samples):
            new = out[r, ids["input_ids"].shape[1]:]
            new = new[new != tok.pad_token_id] if tok.pad_token_id is not None else new
            txt = tok.decode(new, skip_special_tokens=True).strip()
            res.append((txt, {"prompt_tokens": int(ids["input_ids"].shape[1]), "answer_tokens": int(len(new)),
                              "seconds_batch": round(dt, 4), "stopped_repetition": loop.hit[r], "seed": seed}))
        return res

    d = json.load(open(a.dev))
    rnd = random.Random(a.seed)
    pick = []
    for typ in ("compositional", "comparison", "inference", "bridge_comparison"):
        pool = [x for x in d if x["type"] == typ]
        pick += rnd.sample(pool, a.per_type)
    order = {i: n for n, i in enumerate(json.load(open(a.ids)))}      # read in the (shuffled) order of the ids file
    pick = sorted((x for x in pick if x["_id"] in order), key=lambda x: order[x["_id"]])
    done = set()
    try:
        done = {json.loads(l)["id"] for l in open(a.out)}
    except FileNotFoundError:
        pass
    with open(a.out, "a") as f:
        for x in pick:
            if x["_id"] in done:
                continue
            ctxt = {t: " ".join(s) for t, s in x["context"]}
            samples = [{"k": k + 1, "reads": []} for k in range(a.samples)]
            for title in dict.fromkeys(t for t, _ in x["supporting_facts"]):
                if title not in ctxt:
                    continue
                goal_rels = ", ".join(dict.fromkeys(PRED[r] for _s, r, _o in x["evidences"] if r in PRED)) if a.goal_relations else None
                seed = int(hashlib.sha256(f"{a.sample_seed}|{x['_id']}|{title}".encode()).hexdigest()[:8], 16)
                for k, (txt, st) in enumerate(read(ctxt[title], title, goal_rels, seed)):
                    triples = [[s_, INV[p], o] for p, s_, o in FACT.findall(txt) if p in INV]
                    samples[k]["reads"].append({"title": title, "raw": txt, "triples": triples, "stats": st})
            f.write(json.dumps({"id": x["_id"], "type": x["type"], "samples": samples}, ensure_ascii=False) + "\n"); f.flush()


if __name__ == "__main__":
    main()

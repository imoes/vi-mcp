"""Z11 — virtualised LLM: knowledge in a kNN-LM token store vs. knowledge burned into LoRA weights (run 3).

Runs on our own hosts only (VI documents are internal). Data directory: $Z11_DATA (required; private, never committed).
Pre-registration: docs/PREREG_Z11.md (frozen by docs/PREREG_Z11.sha256 before any probe measurement).

The datastore is the real vi_mcp.knn_lm.Datastore (one source per training row, "<document id>#<row>"), so replace/forget/
snapshot are the library's. For speed this runner differs from KNNLanguageModel in two places, both checked by `verify`:
- decoding uses the model's KV cache (one token per step) instead of recomputing the whole context per token;
- exact squared-L2 search runs as one float32 matrix product over all active entries held in memory
  (|k|^2 - 2 k.q + |q|^2) instead of float64 blocks; `verify` compares neighbours and probabilities with Datastore.distribution.

Subcommands: build | verify | valsplit | tune | answer | nll | edit | sizes
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vi_mcp.knn_lm import Datastore, TransformersCore, interpolate  # noqa: E402

DATA = Path(os.environ.get("Z11_DATA", "z11-data"))
MODEL, REVISION = "Qwen/Qwen3-0.6B", "c1899de289a04d12100db370d81485cdf75e47ca"
# The instruction run 3 used for base and tuned answers (kit4/gen_answers.py), unchanged for every arm.
INSTRUCTION = "Answer the question factually and concisely. If you do not know the answer, say so."
GEN_BUDGET = 2048  # run 3's decoding budget; an answer reaching it is marked "budget", never cut silently
EOS_TEXT = "<|im_end|>"


def jl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def write_jl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def train_rows():
    rows = jl(DATA / "kit4/split/train.jsonl")
    for n, r in enumerate(rows):
        r["row"] = n
        r["doc"] = r["meta"]["id"]
        r["source"] = f"{r['doc']}#{n}"
        r["question"] = r["messages"][0]["content"]
        r["answer"] = r["messages"][1]["content"]
    return rows


def probe_questions():
    return [{"id": c["id"], "doc": c["id"].split("probe:", 1)[1], "question": c["question"]}
            for c in jl(DATA / "kit4/probe/catalog.jsonl")]


def words(text):
    return set(re.findall(r"\w+", text.lower()))


def jaccard(a, b):
    a, b = words(a), words(b)
    return len(a & b) / max(1, len(a | b))


# ---------------------------------------------------------------- model + prompts

def load_core():
    import torch
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    return TransformersCore.load(MODEL, revision=REVISION, device="cpu", dtype="float32")


def user_content(question, context_docs=()):
    if not context_docs:
        return question
    blocks = "\n\n".join(f"[Document {i + 1}]\n{d}" for i, d in enumerate(context_docs))
    return f"Context documents:\n\n{blocks}\n\nQuestion: {question}"


def prompt_text(core, question, context_docs=()):
    return core.chat_prompt([{"role": "system", "content": INSTRUCTION},
                             {"role": "user", "content": user_content(question, context_docs)}])


# ---------------------------------------------------------------- store

def build(args):
    core = load_core()
    store_dir = DATA / args.store
    store = Datastore(store_dir, identity=core.identity)
    rows = train_rows()
    t0, entries = time.time(), 0
    done = set(store.view()["documents"])
    for r in rows:
        if hashlib.sha256(r["source"].encode()).hexdigest() in done:
            continue
        prompt = prompt_text(core, r["question"])
        prefix = core.encode(prompt)
        full = core.encode(prompt + r["answer"] + EOS_TEXT)
        if full[:len(prefix)] != prefix or len(full) <= len(prefix):
            raise SystemExit(f"tokenizer boundary refused for {r['source']}")
        states, _ = core.forward_all(full)
        store.replace(r["source"], states[len(prefix) - 1:-1], full[len(prefix):])
        entries += len(full) - len(prefix)
        if r["row"] % 200 == 0:
            print(f"{r['row'] + 1}/{len(rows)} entries {entries} {time.time() - t0:.0f} s", flush=True)
    view = store.view()
    total = sum(d["entries"] for d in view["documents"].values())
    print(json.dumps({"store": str(store_dir), "sources": len(view["documents"]), "entries": total, "revision": view["revision"],
                      "seconds": round(time.time() - t0), "weights_sha256": core.identity["weights_sha256"]}))


class Memory:
    """All active entries of one datastore revision in memory; exact squared-L2 top-k by one float32 matrix product."""

    def __init__(self, store_dir, identity=None):
        import torch
        self.torch = torch
        self.store = Datastore(store_dir, identity=identity) if identity else None
        st = self.store or Datastore(store_dir)
        self.view = st.view()
        docs = sorted(self.view["documents"].items())
        total = sum(d["entries"] for _, d in docs)
        dim = st.identity["dimension"] if st.identity else 1024
        # Deviation 2: the key matrix is a memory-mapped file (same float32 values, written once per revision), so its pages
        # are reclaimable file cache instead of 1.1 GB of anonymous memory under the 6 GB scope limit.
        cache = Path(store_dir) / f"z11_keys_rev{self.view['revision']}_{total}x{dim}.f32"
        fresh = not cache.exists()
        keys = np.memmap(cache, dtype=np.float32, mode="w+" if fresh else "c", shape=(total, dim))
        self.tokens = np.empty(total, dtype=np.int64)
        self.owner = np.empty(total, dtype=np.int64)
        self.sources = []
        at = 0
        for _, d in docs:
            t = st._array(d, "tokens")
            if fresh:
                keys[at:at + len(t)] = st._array(d, "keys")
            self.tokens[at:at + len(t)] = t
            self.owner[at:at + len(t)] = len(self.sources)
            self.sources.append(d["source"])
            at += len(t)
        if fresh:
            keys.flush()
            keys = np.memmap(cache, dtype=np.float32, mode="c", shape=(total, dim))
        self.keys = torch.from_numpy(keys)
        norms = np.empty(total, dtype=np.float64)
        for s in range(0, total, 65536):
            block = keys[s:s + 65536].astype(np.float64)
            norms[s:s + 65536] = np.einsum("ij,ij->i", block, block)
        self.norms = torch.from_numpy(norms.astype(np.float32))
        self.source_index = {s: i for i, s in enumerate(self.sources)}
        self.revision = self.view["revision"]
        self.bytes = int(self.keys.numel() * 4 + self.tokens.nbytes)

    def topk(self, queries, k, exclude=()):
        """queries: (n, d) float32 → (distances (n,k) float64, entry indices (n,k)) ascending; excluded sources masked out."""
        torch = self.torch
        q = torch.as_tensor(np.asarray(queries, dtype=np.float32))
        d = self.norms[None, :] - 2.0 * (q @ self.keys.T) + (q.double() ** 2).sum(1).float()[:, None]
        if exclude:
            idx = [self.source_index[s] for s in exclude if s in self.source_index]
            if idx:
                mask = torch.from_numpy(np.isin(self.owner, idx))
                d[:, mask] = float("inf")
        kk = min(k, d.shape[1])
        vals, ind = torch.topk(d, kk, dim=1, largest=False, sorted=True)
        return vals.double().clamp_min(0).numpy(), ind.numpy()

    def distribution(self, dist_row, ind_row, k, temperature, vocab):
        dist, ind = dist_row[:k], ind_row[:k]
        ok = np.isfinite(dist)
        dist, ind = dist[ok], ind[ok]
        p = np.zeros(vocab, dtype=np.float64)
        if len(ind):
            w = np.exp(-(dist - dist[0]) / temperature)
            w /= w.sum()
            np.add.at(p, self.tokens[ind], w)
        return p


def verify(args):
    """Fast search vs. the library's Datastore.distribution on held-out query states: same neighbours, same probabilities."""
    core = load_core()
    mem = Memory(DATA / args.store, identity=core.identity)
    store = Datastore(DATA / args.store, identity=core.identity)
    rng = np.random.default_rng(1122)
    rows = train_rows()
    worst, same = 0.0, 0
    picks = rng.choice(len(rows), size=args.n, replace=False)
    for i in picks:
        r = rows[int(i)]
        states, _ = core.forward_all(core.encode(prompt_text(core, r["question"])))
        q = states[-1]
        for k, temp in ((8, 1.0), (64, 100.0)):
            lib, info = store.distribution(q, k=k, temperature=temp, exclude_sources=[r["source"]])
            dist, ind = mem.topk(q[None], k, exclude=[r["source"]])
            mine = mem.distribution(dist[0], ind[0], k, temp, core.identity["vocab_size"])
            worst = max(worst, float(np.abs(lib - mine).max()))
            same += int(np.argmax(lib) == np.argmax(mine))
    # Generation: the KV-cache runner against the library's KNNLanguageModel.generate (full recomputation per token).
    from vi_mcp.knn_lm import KNNLanguageModel
    temp = float(np.median([mem.topk(core.forward_all(core.encode(prompt_text(core, rows[int(i)]["question"])))[0][-1][None], 1)[0][0, 0]
                            for i in picks[:5]]))
    lm = KNNLanguageModel(core, store, weight=0.5, k=8, temperature=temp)
    gen = Generator(core)
    equal = []
    for i in picks[:3]:
        prompt = prompt_text(core, rows[int(i)]["question"])
        a = lm.generate(prompt, steps=24)["tokens"]
        b = gen.run(prompt, mem=mem, k=8, temperature=temp, weight=0.5, budget=24)
        equal.append(core.tokenizer.decode(a, skip_special_tokens=True).strip() == b["text"])
    print(json.dumps({"queries": len(picks) * 2, "argmax_equal": same, "max_abs_probability_difference": worst,
                      "entries": int(len(mem.tokens)), "bytes_in_memory": mem.bytes,
                      "generation_equal_to_library": equal, "generation_check_temperature": temp}))


# ---------------------------------------------------------------- validation split (non-probe documents only)

def valsplit(args):
    """One held-out training row per non-probe document whose question is not a near-paraphrase of a sibling
    (word Jaccard < 0.5 to every other question of the document, the probe's own hold-out rule); seeded choice."""
    rows = train_rows()
    probe_docs = {p["doc"] for p in probe_questions()}
    by_doc = defaultdict(list)
    for r in rows:
        by_doc[r["doc"]].append(r)
    rng = np.random.default_rng(2211)
    chosen = []
    for doc in sorted(by_doc):
        if doc in probe_docs or len(by_doc[doc]) < 2:
            continue
        cand = [r for r in by_doc[doc] if all(jaccard(r["question"], o["question"]) < 0.5 for o in by_doc[doc] if o is not r)]
        if cand:
            r = cand[int(rng.integers(len(cand)))]
            chosen.append({"source": r["source"], "doc": doc, "row": r["row"], "question": r["question"], "answer": r["answer"]})
    write_jl(DATA / "val.jsonl", chosen)
    print(json.dumps({"validation_rows": len(chosen), "non_probe_documents": len(set(by_doc) - probe_docs),
                      "sha256": sha256(DATA / "val.jsonl")}))


# ---------------------------------------------------------------- BM25 retrieval over the 500 documents

class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.ids = [d["meta"]["id"] for d in docs]
        self.text = {d["meta"]["id"]: d["document"] for d in docs}
        toks = [re.findall(r"\w+", d["document"].lower()) for d in docs]
        self.tf = [Counter(t) for t in toks]
        self.len = np.array([len(t) for t in toks], dtype=float)
        df = Counter(w for t in self.tf for w in t)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.k1, self.b, self.avg = k1, b, self.len.mean()

    def search(self, query, k):
        q = re.findall(r"\w+", query.lower())
        scores = np.zeros(len(self.ids))
        for j, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[j] / self.avg))
            scores[j] = s
        order = np.argsort(-scores, kind="stable")[:k]
        return [self.ids[j] for j in order]


def load_bm25():
    return BM25(jl(DATA / "kit4/documents500.jsonl"))


def context_for(bm25, question, k, exclude_doc=None):
    if not k:
        return []
    ids = [i for i in bm25.search(question, k + (1 if exclude_doc else 0)) if i != exclude_doc][:k]
    return [bm25.text[i] for i in ids], ids


# ---------------------------------------------------------------- teacher-forced scoring (validation tuning and probe NLL)

def answer_states(core, prompt, answer):
    prefix = core.encode(prompt)
    full = core.encode(prompt + answer + EOS_TEXT)
    if full[:len(prefix)] != prefix:
        raise ValueError("tokenizer boundary")
    import torch
    keep = len(full) - len(prefix) + 1  # logits only where the answer is predicted (long RAG prompts: 6 GB scope limit)
    with torch.inference_mode():
        out = core.model(input_ids=torch.tensor([full]), output_hidden_states=True, use_cache=False, return_dict=True,
                         logits_to_keep=keep)
    states = out.hidden_states[-1][0, len(prefix) - 1:len(full) - 1].float().numpy()
    logits = out.logits[0, :-1].float().numpy()
    return states, logits, np.array(full[len(prefix):])


def log_softmax(logits):
    m = logits.max(axis=1, keepdims=True)
    return logits - m - np.log(np.exp(logits - m).sum(axis=1, keepdims=True))


def tune(args):
    """Grid over (weight, neighbours, temperature) on the validation rows: teacher-forced NLL of the held-out reference answer,
    the row's own source excluded from retrieval. Neighbours are searched once at the largest k and reused for every cell."""
    core = load_core()
    mem = Memory(DATA / args.store, identity=core.identity)
    val = jl(DATA / "val.jsonl")
    kmax = 128
    cache = []
    t0 = time.time()
    for v in val:
        states, logits, targets = answer_states(core, prompt_text(core, v["question"]), v["answer"])
        dist, ind = mem.topk(states, kmax, exclude=[v["source"]])
        lp = log_softmax(logits.astype(np.float64))[np.arange(len(targets)), targets]
        hit = (mem.tokens[ind] == targets[:, None])  # which neighbours carry the target token
        cache.append((dist, hit, lp))
    nn = np.concatenate([c[0][:, 0] for c in cache])
    scale = float(np.median(nn))
    temps = [scale * f for f in (0.03, 0.1, 0.3, 1.0, 3.0)]
    grid = []
    base_nll = -np.concatenate([c[2] for c in cache]).mean()
    for k in (8, 16, 32, 64, 128):
        for ti, temp in enumerate(temps):
            pk = []
            for dist, hit, lp in cache:
                d = dist[:, :k]
                w = np.exp(-(d - d[:, :1]) / temp)
                w /= w.sum(1, keepdims=True)
                pk.append((w * hit[:, :k]).sum(1))
            pk = np.concatenate(pk)
            pb = np.exp(np.concatenate([c[2] for c in cache]))
            for wgt in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
                nll = -np.log(np.maximum((1 - wgt) * pb + wgt * pk, np.finfo(float).tiny)).mean()
                grid.append({"k": k, "temperature": temp, "temperature_factor": (0.03, 0.1, 0.3, 1.0, 3.0)[ti], "weight": wgt,
                             "nll": float(nll)})
    best = min(grid, key=lambda g: (g["nll"], g["k"], g["weight"]))
    out = {"validation_rows": len(val), "tokens": int(sum(len(c[2]) for c in cache)), "base_nll": float(base_nll),
           "median_nearest_squared_l2": scale, "best": best, "seconds": round(time.time() - t0), "store_revision": mem.revision}
    json.dump({"summary": out, "grid": grid}, open(DATA / f"tune_{args.store}.json", "w"), indent=1)
    print(json.dumps(out))


def tune_rag(args):
    """RAG top-k on the validation rows: teacher-forced NLL of the reference answer with k BM25 documents in the prompt."""
    core = load_core()
    bm25 = load_bm25()
    val = jl(DATA / "val.jsonl")
    res = {}
    for k in (0, 1, 2, 3):
        tot, n, hits = 0.0, 0, 0
        for v in val:
            docs, ids = context_for(bm25, v["question"], k) if k else ([], [])
            hits += int(v["doc"] in ids)
            _, logits, targets = answer_states(core, prompt_text(core, v["question"], docs), v["answer"])
            tot -= log_softmax(logits.astype(np.float64))[np.arange(len(targets)), targets].sum()
            n += len(targets)
        res[k] = {"nll": tot / n, "tokens": n, "own_document_retrieved": hits}
        print(k, res[k], flush=True)
    json.dump(res, open(DATA / "tune_rag.json", "w"), indent=1)


# ---------------------------------------------------------------- generation (KV cache)

class Generator:
    def __init__(self, core, adapter=None):
        import torch
        self.core, self.torch = core, torch
        self.model = core.model
        if adapter:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(core.model, str(adapter)).eval()
        self.eos = core.tokenizer.convert_tokens_to_ids(EOS_TEXT)
        # Deviation 2: the key state is taken from the final norm's output by a hook (bitwise equal to hidden_states[-1],
        # checked 22.11.2026), so the prefill no longer returns the hidden states of all 29 layers.
        self.state = {}
        core.model.model.norm.register_forward_hook(lambda mod, inp, out: self.state.__setitem__("last", out))

    def run(self, prompt, mem=None, k=32, temperature=1.0, weight=0.0, budget=GEN_BUDGET):
        torch = self.torch
        ids = self.core.encode(prompt)
        vocab = self.core.identity["vocab_size"]
        out, past, step_ids = [], None, ids
        t0 = time.time()
        sources = Counter()
        finish = "budget"
        with torch.inference_mode():
            for _ in range(budget):
                # logits_to_keep=1: only the last position's logits (the same numbers; a 3-document RAG prefill would
                # otherwise hold prompt length x vocab float32 logits and exceed the 6 GB limit — deviation 1, 22.11.2026).
                o = self.model(input_ids=torch.tensor([step_ids]), past_key_values=past, use_cache=True,
                               output_hidden_states=False, return_dict=True, logits_to_keep=1)
                past = o.past_key_values
                logits = o.logits[0, -1].float().numpy()
                if mem is not None and weight > 0:
                    state = self.state["last"][0, -1].float().numpy()
                    dist, ind = mem.topk(state[None], k)
                    pk = mem.distribution(dist[0], ind[0], k, temperature, vocab)
                    mixed, _ = interpolate(logits[:vocab], pk, weight)
                    tok = int(mixed.argmax())
                    sources[mem.sources[int(mem.owner[ind[0][0]])].split("#")[0]] += 1
                else:
                    tok = int(np.argmax(logits))
                if tok == self.eos:
                    finish = "stop"
                    break
                out.append(tok)
                step_ids = [tok]
                if len(ids) + len(out) >= self.core.window:
                    finish = "context"
                    break
        return {"text": self.core.tokenizer.decode(out, skip_special_tokens=True).strip(), "finish": finish,
                "tokens": len(out), "seconds": round(time.time() - t0, 2), "nearest_documents": sources.most_common(3)}


def answer(args):
    """Answers of one arm to one question set, written per question as soon as it exists (resumable)."""
    core = load_core()
    params = json.load(open(DATA / "frozen_params.json")) if args.arm in ("K", "KR", "KD") else {}
    rag_k = json.load(open(DATA / "frozen_params.json"))["rag_k"] if args.arm in ("R", "KR") else 0
    gen = Generator(core, adapter=DATA / "kit4/out/sft" if args.arm == "L" else None)
    mem = None
    if args.arm in ("K", "KR"):
        mem = Memory(DATA / (args.store or "store_qa"), identity=core.identity)
    bm25 = load_bm25() if rag_k else None
    qs = jl(DATA / args.questions) if args.questions.endswith(".jsonl") else probe_questions()
    out_path = DATA / args.out
    done = {r["id"] for r in jl(out_path)} if out_path.exists() else set()
    with open(out_path, "a", encoding="utf-8") as f:
        for q in qs:
            if q["id"] in done:
                continue
            docs, ids = context_for(bm25, q["question"], rag_k) if rag_k else ([], [])
            kw = {}
            if mem is not None:
                kw = {"mem": mem, "k": params["k"], "temperature": params["temperature"], "weight": params["weight"]}
            r = gen.run(prompt_text(core, q["question"], docs), **kw)
            r.update({"id": q["id"], "arm": args.arm, "retrieved": ids, "store_revision": mem.revision if mem else None})
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(q["id"], r["finish"], r["tokens"], r["seconds"], flush=True)


def nll(args):
    """Secondary metric: teacher-forced NLL of the 60 probe reference answers per arm (B, L, K, R, KR)."""
    core = load_core()
    params = json.load(open(DATA / "frozen_params.json"))
    # The judge's reference is "answer\n\n--- document ---\n<document>"; the NLL is of the reference ANSWER only (PREREG).
    refs = {r["id"]: r["reference"].split("\n\n--- document ---\n", 1)[0].strip()
            for r in jl(DATA / "judged/references_probe.jsonl")}
    qs = probe_questions()
    mem = Memory(DATA / "store_qa", identity=core.identity)
    bm25 = load_bm25()
    res = {}
    for arm in ("B", "K", "R", "KR", "L"):
        if arm == "L":
            from peft import PeftModel
            core.model = PeftModel.from_pretrained(core.model, str(DATA / "kit4/out/sft")).eval()
        tot, n = 0.0, 0
        for q in qs:
            docs = context_for(bm25, q["question"], params["rag_k"])[0] if arm in ("R", "KR") else []
            states, logits, targets = answer_states(core, prompt_text(core, q["question"], docs), refs[q["id"]])
            lp = log_softmax(logits.astype(np.float64))[np.arange(len(targets)), targets]
            if arm in ("K", "KR"):
                dist, ind = mem.topk(states, params["k"])
                pb = np.exp(lp)
                d = dist[:, :params["k"]]
                w = np.exp(-(d - d[:, :1]) / params["temperature"])
                w /= w.sum(1, keepdims=True)
                pk = (w * (mem.tokens[ind] == targets[:, None])).sum(1)
                lp = np.log(np.maximum((1 - params["weight"]) * pb + params["weight"] * pk, np.finfo(float).tiny))
            tot -= lp.sum()
            n += len(targets)
        res[arm] = {"nll": tot / n, "perplexity": math.exp(tot / n), "tokens": n}
        print(arm, res[arm], flush=True)
    json.dump(res, open(DATA / "probe_nll.json", "w"), indent=1)


# ---------------------------------------------------------------- blind judging and scoring

STORED = {"B3": "base", "L3": "tuned"}  # run-3 GPU answers, sides resolved with the run-3 key


def stored_answers():
    key = {r["id"]: r for r in jl(DATA / "judged/ab_key_probe3.jsonl")}
    out = {"B3": {}, "L3": {}}
    for a in jl(DATA / "judged/answers_probe3.jsonl"):
        for side in "AB":
            arm = "L3" if key[a["id"]][side] == "tuned" else "B3"
            out[arm][a["id"]] = {"text": a[side], "finish": a[side + "_finish"]}
    return out


def judgepack(args):
    """Blocks of 20 questions; per question all arms' answers in a seeded order under letters; the key in a separate file."""
    arms = args.arms.split(",")
    answers = stored_answers()
    for arm in arms:
        if arm not in answers:
            answers[arm] = {r["id"]: {"text": r["text"], "finish": r["finish"]} for r in jl(DATA / f"answers_{arm}.jsonl")}
    refs = {r["id"]: r for r in jl(DATA / args.refs)}
    qs = probe_questions() if args.questions == "probe" else jl(DATA / args.questions)
    out_dir = DATA / args.out
    out_dir.mkdir(exist_ok=True)
    key = []
    blocks = defaultdict(list)
    for n, q in enumerate(qs):
        present = [a for a in arms if q["id"] in answers[a]]
        order = sorted(present, key=lambda a: hashlib.sha256(f"z11:{args.out}:{q['id']}:{a}".encode()).hexdigest())
        letters = "ABCDEFGHIJ"
        item = {"n": n, "question": q["question"], "reference_and_document": refs[q["id"]]["reference"],
                "answers": {letters[i]: (answers[a][q["id"]]["text"] + (" [BUDGET REACHED: answer incomplete]"
                                                                    if answers[a][q["id"]]["finish"] == "budget" else ""))
                            for i, a in enumerate(order)}}
        blocks[n // 20].append(item)
        key.append({"n": n, "id": q["id"], "letters": {letters[i]: a for i, a in enumerate(order)}})
    for b, items in blocks.items():
        write_jl(out_dir / f"block{b}.jsonl", items)
    write_jl(DATA / f"{args.out}_KEY.jsonl", key)
    print(json.dumps({"blocks": len(blocks), "questions": len(key), "arms": arms}))


def sign_test(wins, losses):
    n = wins + losses
    if not n:
        return 1.0
    return sum(math.comb(n, i) for i in range(wins, n + 1)) / 2 ** n


def score(args):
    """Open the key only after all grade files exist: counts per arm, exact sign tests, agreement with the run-3 grades."""
    out_dir = DATA / args.out
    grades = {}
    for f in sorted(out_dir.glob("grades*.jsonl")):
        for g in jl(f):
            grades[g["n"]] = g["grades"]
    key = jl(DATA / f"{args.out}_KEY.jsonl")
    if len(grades) != len(key):
        raise SystemExit(f"{len(grades)} of {len(key)} questions graded — the key stays closed")
    per = defaultdict(dict)
    for k in key:
        for letter, arm in k["letters"].items():
            per[arm][k["id"]] = grades[k["n"]][letter]
    counts = {a: dict(Counter(v.values())) for a, v in per.items()}
    value = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}
    graded = {a: sum(value[g] for g in v.values()) for a, v in per.items()}
    tests = {}
    for x, y in (("K", "B"), ("K", "L"), ("KR", "R"), ("R", "L"), ("R", "K"), ("L", "B"), ("KR", "L")):
        if x in per and y in per:
            ids = set(per[x]) & set(per[y])
            w = sum(1 for i in ids if per[x][i] == "correct" and per[y][i] != "correct")
            lo = sum(1 for i in ids if per[y][i] == "correct" and per[x][i] != "correct")
            tests[f"{x}>{y}"] = {"wins": w, "losses": lo, "p_one_sided": sign_test(w, lo),
                                 "p_two_sided": min(1.0, 2 * min(sign_test(w, lo), sign_test(lo, w)))}
    agreement = {}
    old_key = {r["id"]: r for r in jl(DATA / "judged/ab_key_probe3.jsonl")}
    ans = jl(DATA / "judged/answers_probe3.jsonl")
    old = jl(DATA / "judged/judgments_probe3.jsonl")
    old_grade = {"B3": {}, "L3": {}}
    for o in old:
        a = ans[o["i"]]
        for side in "AB":
            old_grade["L3" if old_key[a["id"]][side] == "tuned" else "B3"][a["id"]] = o[side]
    for arm in ("B3", "L3"):
        if arm in per:
            pairs = [(old_grade[arm][i], per[arm][i]) for i in per[arm]]
            agree = sum(1 for a, b in pairs if a == b) / len(pairs)
            cats = ["correct", "partial", "wrong"]
            pe = sum((sum(1 for a, _ in pairs if a == c) / len(pairs)) * (sum(1 for _, b in pairs if b == c) / len(pairs)) for c in cats)
            agreement[arm] = {"agree": agree, "kappa": (agree - pe) / (1 - pe) if pe < 1 else None}
    res = {"counts": counts, "graded_score": graded, "tests": tests, "agreement_with_run3": agreement}
    json.dump(res, open(DATA / f"{args.out}_SCORE.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["build", "verify", "valsplit", "tune", "tune_rag", "answer", "nll", "judgepack", "score"])
    p.add_argument("--arms", default="B,L,K,R,KR,B3,L3")
    p.add_argument("--refs", default="judged/references_probe.jsonl")
    p.add_argument("--store", default="store_qa")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--arm")
    p.add_argument("--questions", default="probe")
    p.add_argument("--out")
    a = p.parse_args()
    globals()[a.cmd](a)


if __name__ == "__main__":
    main()

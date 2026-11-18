"""Independent target/mask, boundary and whole-example checks without optional ML dependencies."""
import json

from vi_mcp.training_runtime import prepare, verify_prepared


class Tokenizer:
    chat_template = "fixture"
    eos_token = "<end>"
    def __call__(self, text, **kwargs):
        assert not kwargs.get("truncation")
        return {"input_ids": list(text.encode())}
    def apply_chat_template(self, messages, *, add_generation_prompt, **kwargs):
        out = ""
        if kwargs.get("tools"):
            out += json.dumps(kwargs["tools"])
        for m in messages:
            out += m["role"] + ":" + (m.get("content") or "")
            if m.get("tool_calls"):
                out += json.dumps(m["tool_calls"], sort_keys=True)
            out += self.eos_token
        return out + ("assistant:" if add_generation_prompt else "")


def test_only_assistant_tokens_are_targets_and_argument_shapes_do_not_merge():
    def example(arguments):
        return {"messages": [{"role": "user", "content": "private input"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "vi_logic", "arguments": arguments}}]},
            {"role": "tool", "content": "private observed result"}, {"role": "assistant", "content": "checked answer"}]}
    rows, audit = prepare([example({"source": 'ans("safe")'}), example({"filters": ["service:api"]})], Tokenizer(), "logic", 2000)
    assert audit["valid"] and len(rows) == 4
    for row in rows:
        target = bytes(t for t in row["labels"] if t != -100).decode()
        assert "private input" not in target and "private observed result" not in target
        assert all(t == -100 for t in row["labels"][:row["labels"].index(next(t for t in row["labels"] if t != -100))])
    targets = [bytes(t for t in row["labels"] if t != -100).decode() for row in rows]
    assert '"filters"' not in targets[0] and '"source"' not in targets[2] and "null" not in "".join(targets)


def test_an_oversized_episode_is_never_partially_trained_or_silently_cut():
    small = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "safe"}]}
    large = {"messages": small["messages"] + [{"role": "user", "content": "x" * 300}, {"role": "assistant", "content": "program tail"}]}
    rows, audit = prepare([small, large], Tokenizer(), "logic", 100)
    assert len(rows) == 1 and not audit["valid"] and audit["rejected"] == {"oversize": 1}
    rows, audit = prepare([small, large], Tokenizer(), "logic", 100, skip_oversize=True)
    assert audit["valid"] and len(rows) == 1


def test_template_prefix_mismatch_refuses_instead_of_training_a_changed_context():
    class Changed(Tokenizer):
        def apply_chat_template(self, messages, **kwargs):
            return ("changed" if kwargs["add_generation_prompt"] else "actual") + super().apply_chat_template(messages, **kwargs)
    _, audit = prepare([{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}], Changed(), "sft", 100)
    assert not audit["valid"] and audit["rejected"] == {"template_prefix_mismatch": 1}


def test_preference_type_and_token_audit_is_strict():
    _, audit = prepare([{"prompt": "q", "completion": "a", "label": 1}], Tokenizer(), "kto", 100)
    assert not audit["valid"] and audit["rejected"] == {"binary_label": 1}
    _, audit = prepare([{"prompt": "q", "chosen": "a", "rejected": "a"}], Tokenizer(), "dpo", 100)
    assert not audit["valid"] and audit["rejected"] == {"identical_preference": 1}


def test_library_token_or_mask_mutation_is_detected():
    import pytest
    expected = [{"input_ids": [1, 2, 3], "labels": [-100, 2, 3]}]
    for actual in ([{"input_ids": [1, 2], "labels": [-100, 2]}], [{"input_ids": [1, 2, 3], "labels": [1, 2, 3]}]):
        trainer = type("Trainer", (), {"train_dataset": actual})()
        with pytest.raises(ValueError, match="changed audited"):
            verify_prepared(trainer, expected, Tokenizer(), "sft", 10)


def test_preference_prompts_are_rendered_in_the_chat_template_like_sft():
    """Review 14.11.2026 (Claude), agreed by Codex: KTO/DPO rows are plain strings and TRL applies no chat template to strings, so
    preference learning saw a format the chat model never sees at inference. The prompt is now rendered with the model's chat
    template (generation prompt, thinking off) before the token audit, exactly as the SFT stages render theirs."""
    rows, audit = prepare([{"prompt": "Which port?", "completion": 'ans("80")', "label": False}], Tokenizer(), "kto", 200)
    assert audit["valid"] and audit["preference_format"] == "chat_template"
    assert rows[0]["prompt"] == "user:Which port?<end>assistant:" and rows[0]["completion"] == 'ans("80")'
    rows, audit = prepare([{"prompt": "Which port?", "chosen": 'ans("80")', "rejected": 'ans("8")'}], Tokenizer(), "dpo", 200)
    assert rows[0]["prompt"] == "user:Which port?<end>assistant:"
    class Plain(Tokenizer):
        chat_template = None
    rows, audit = prepare([{"prompt": "Which port?", "completion": "a", "label": True}], Plain(), "kto", 200)
    assert audit["valid"] and audit["preference_format"] == "plain (tokenizer has no chat template)" and rows[0]["prompt"] == "Which port?"


def test_fp32_attention_uses_the_efficient_kernel_for_grouped_query_models(monkeypatch):
    """0.69.9 (measured 18.11.2026): transformers calls SDPA with enable_gqa=True, which in fp32 falls back to the quadratic math kernel
    (+4.1 GB at 4,096 tokens; out of memory on 8 GB). In fp32 the kit repeats the kv heads instead — same attention, efficient kernel."""
    import sys
    import types
    from vi_mcp import training_runtime as tr
    fake_pkg = types.ModuleType("transformers")
    fake_int = types.ModuleType("transformers.integrations")
    fake = types.ModuleType("transformers.integrations.sdpa_attention")
    fake.use_gqa_in_sdpa = lambda attention_mask, key, value: attention_mask is None
    fake_int.sdpa_attention = fake
    fake_pkg.integrations = fake_int
    monkeypatch.setitem(sys.modules, "transformers", fake_pkg)
    monkeypatch.setitem(sys.modules, "transformers.integrations", fake_int)
    monkeypatch.setitem(sys.modules, "transformers.integrations.sdpa_attention", fake)
    assert tr.efficient_gqa_attention(fp32=False).startswith("library default")
    assert fake.use_gqa_in_sdpa(None, None, None) is True  # bf16/fp16 keep the library's choice (flash supports GQA there)
    assert tr.efficient_gqa_attention(fp32=True).startswith("kv heads repeated")
    assert fake.use_gqa_in_sdpa(None, None, None) is False
    del fake.use_gqa_in_sdpa
    assert tr.efficient_gqa_attention(fp32=True) == "library default (no use_gqa_in_sdpa)"
    src = (tr.__file__ and open(tr.__file__).read())
    # set before the trainer of every stage is built, GRPO too (its branch follows right after)
    assert ('report["sdpa_gqa"] = efficient_gqa_attention(fp32=bool(o.fp32) and not o.cpu)\n'
            '        from trl import SFTConfig, SFTTrainer, KTOConfig, KTOTrainer, DPOConfig, DPOTrainer\n'
            '        if o.stage == "grpo":') in src

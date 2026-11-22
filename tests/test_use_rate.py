"""Z7: the agents' use rate per hint (vi_mcp/use_rate.py) — the within-action label, the score, the per-conversation arm and its
place in intuition.before. Offline evidence: docs/PREREG_Z7B_WITHIN_ACTION.md; online test: docs/PREREG_Z7C_ONLINE_AB.md."""
import json

from vi_mcp import config, intuition, session, use_rate
from vi_mcp import memory as g


def _k(text, tags, kind="insight"):
    return g.new_object(kind, text, tags, {"source": "test 22.11.2026"}, instance="b")


def _exp(shown, used=None, inst="a"):
    d = {"before": {"shown": shown}}
    if used is not None:  # the agent's declaration, as intuition.declare_used writes it
        d["declared"] = {"used": used, "unused": [h for h in shown if h not in used], "ignored": []}
    return g.new_object("experience", "Bash uptime", ["tool:Bash", "ok:yes"], d, instance=inst)


def test_only_mixed_actions_with_two_shown_hints_are_labels(gd):
    a = _k("uptime lies after a suspend on the build host", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time", ["tool:Bash", "topic:uptime"])
    c = _k("w shows who is logged in", ["tool:Bash", "topic:uptime"])
    _exp([a.id, b.id], [a.id])          # label: a used, b not
    _exp([a.id, c.id], [a.id])          # label: a used, c not
    _exp([a.id, b.id], [a.id, b.id])    # all used: says nothing about which — not a label
    _exp([b.id], [b.id])                # one shown hint: no choice — not a label
    _exp([a.id, b.id])                  # no report — not a label
    r = use_rate.recompute()
    assert r["actions"] == 2 and r["hints"] == 3
    assert use_rate.counter(g.load(a.id)) == (2, 2)
    assert use_rate.counter(g.load(b.id)) == (0, 1) and use_rate.counter(g.load(c.id)) == (0, 1)


def test_counters_without_labels_are_dropped_and_counted(gd):
    a = _k("uptime lies after a suspend", ["tool:Bash", "topic:uptime"])
    stale = _k("an old hint", ["tool:Bash", "topic:uptime"])
    g.update_data(stale.id, lambda d: d.__setitem__("use_rate", {"used": 3, "shown": 4, "method": use_rate.METHOD_ID}))
    g.db().commit()
    r = use_rate.recompute()
    assert r["dropped"] == 1 and "use_rate" not in g.load(stale.id).data
    assert use_rate.counter(g.load(a.id)) == (0, 0)


def test_score_is_the_beta_posterior_with_the_kind_as_prior(gd):
    a = _k("uptime lies after a suspend", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time", ["tool:Bash", "topic:uptime"])
    s = _k("solution: reboot the build host", ["tool:Bash", "topic:uptime"], kind="skill")
    for _ in range(3):
        _exp([s.id, a.id], [s.id])
    _exp([a.id, b.id], [a.id])
    use_rate.recompute()
    per_kind, overall = use_rate.kind_rates()
    assert per_kind["skill"] == (3 + 1) / (3 + 2) and per_kind["insight"] == (1 + 1) / (5 + 2)
    m = per_kind["insight"]
    assert use_rate.score(g.load(a.id)) == (m * use_rate.PRIOR_S + 1) / (use_rate.PRIOR_S + 4)
    fresh = _k("a new insight nobody reported yet", ["tool:Bash", "topic:uptime"])
    assert use_rate.score(g.load(fresh.id)) == m  # unseen: the rate of its kind
    order = [o.id for o in use_rate.arrange([g.load(b.id), g.load(a.id), g.load(s.id)])]
    assert order == [s.id, a.id, b.id]  # skill (4/5 prior, 3 of 3 used) > a (1 of 4 used) > b (0 of 1, prior pulls it to 0.238)
    assert use_rate.score(g.load(s.id)) > use_rate.score(g.load(a.id))


def test_arm_is_stable_per_conversation_and_off_by_default(monkeypatch):
    assert use_rate.SHARE == 0.0 and use_rate.arm("c1") is None  # default: no test
    monkeypatch.setattr(use_rate, "SHARE", 0.3)
    assert use_rate.arm(None) is None
    arms = [use_rate.arm(f"conv-{i}") for i in range(4000)]
    assert arms == [use_rate.arm(f"conv-{i}") for i in range(4000)]  # deterministic
    assert abs(arms.count("use_rate") / len(arms) - 0.3) < 0.03 and set(arms) == {"use_rate", "bandit"}


def _before(cmd, conv):
    s = session.begin("a", conv)
    with session.on_behalf(s):
        return intuition.before("Bash", {"command": cmd}, "a", False)


def test_the_use_rate_arm_ranks_and_logs_and_the_bandit_arm_only_logs(gd, monkeypatch):
    a = _k("uptime lies after a suspend on the build host", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time on the build host", ["tool:Bash", "topic:uptime"])
    for _ in range(4):
        _exp([a.id, b.id], [b.id])  # the agents use b, not a
    use_rate.recompute()
    # session.begin gives each conversation a new serial, so the arm is steered by the share: 1.0 → always use_rate, 1e-12 → bandit
    monkeypatch.setattr(use_rate, "SHARE", 1.0)
    z = _before("uptime", "c1")["zugriff"]
    assert z["router"] == "use_rate" and z["use_rate_arm"] == "use_rate"
    assert z["shown"][0] == b.id and set(z["use_rate_scores"]) >= {a.id, b.id}
    assert z["use_rate_scores"][b.id] > z["use_rate_scores"][a.id]
    assert all(p == 1.0 for h, p in z["offer"].items() if h in z["shown"])  # deterministic ranking: the propensities stay those of ε
    monkeypatch.setattr(use_rate, "SHARE", 1e-12)
    z = _before("uptime", "c2")["zugriff"]
    assert z["router"] != "use_rate" and z["use_rate_arm"] == "bandit" and b.id in z["use_rate_scores"]  # shadow scores


def test_off_nothing_changes_in_before(gd):
    _k("uptime lies after a suspend on the build host", ["tool:Bash", "topic:uptime"])
    z = _before("uptime", "c1")["zugriff"]
    assert "use_rate_arm" not in z and "use_rate_scores" not in z and z["router"] != "use_rate"


def test_config_bounds_the_share(tmp_path):
    p = tmp_path / "c.json"
    for raw, want in ((0.3, 0.3), (0.9, 0.5), (-1, 0.0), ("x", 0.0)):
        p.write_text(json.dumps({"use_rate_share": raw}))
        assert config.load(p).use_rate_share == want
    p.write_text("{}")
    assert config.load(p).use_rate_share == 0.0


def test_the_implicit_adoption_heuristic_is_no_label(gd):
    """data.used is intuition.adopted's token-reuse heuristic (stored English name of genutzt) — it failed its placebo check
    (held-back hints adopted as often as shown ones, PREREG_Z7B amendment) and must not count."""
    a = _k("uptime lies after a suspend", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time", ["tool:Bash", "topic:uptime"])
    g.new_object("experience", "Bash uptime", ["tool:Bash", "ok:yes"], {"before": {"shown": [a.id, b.id]}, "used": [a.id]}, instance="a")
    assert use_rate.recompute()["actions"] == 0 and use_rate.counter(g.load(a.id)) == (0, 0)

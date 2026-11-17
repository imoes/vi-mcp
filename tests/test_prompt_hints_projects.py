"""0.69.9 (issue #3, point 5): prompt and error hints from unrelated projects. Reported on CachyOS: in a session of project A, 4 of 5
prompt hints came from four other projects' "open points" sections and history, because two ordinary shared words were enough and the
project index only broke ties. Learning across projects must stay possible: an identifier or a hashtag value still carries a hint."""
from vi_mcp import indexes, intuition
from vi_mcp import memory as g


def _k(text, tags, idx, **kw):
    return g.new_object("insight", text, tags, {"source": "test 17.11.2026"}, instance="a", index=idx, **kw)


def _in(idx, fn):
    t = g.current_index.set(idx)
    try:
        return fn()
    finally:
        g.current_index.reset(t)


def test_project_of_maps_history_indexes():
    assert indexes.project_of("cue-print-history") == "cue-print" and indexes.project_of("cue-print") == "cue-print"
    assert indexes.is_history("x-archive") and not indexes.is_history("x") and not indexes.is_history(None)
    assert indexes.project_of("-history") == "-history"  # nothing left: not a history of anything


def test_other_projects_need_more_than_two_ordinary_words(gd):
    _k("project a: install the update before the open points are closed", ["topic:release"], "proj-a")
    other = _k("open points: update the installer and install the new certificates", ["topic:todo"], "proj-b")
    prompt = "what are the open points for the update"  # three ordinary words shared with both
    assert _in("proj-a", lambda: other.id not in intuition.prompt_hints(prompt, "a")["ids"])
    # without a project (or in a directory that holds no knowledge) nothing is foreign — three ordinary words are enough
    assert _in("global", lambda: other.id in intuition.prompt_hints(prompt, "a")["ids"])
    assert _in("code", lambda: other.id in intuition.prompt_hints(prompt, "a")["ids"])


def test_an_identifier_still_carries_knowledge_across_projects(gd):
    _k("proj-a builds with make", ["topic:build"], "proj-a")
    k = _k("db01.example.org runs out of disk every sunday: the backup writes to /var", ["host:db01.example.org"], "proj-b")
    assert _in("proj-a", lambda: intuition.prompt_hints("why is db01.example.org full again", "a")["ids"]) == [k.id]


def test_only_ordinary_words_need_three(gd):
    k = _k("the update of the installer needs a restart", ["topic:x"], "global")
    assert intuition.prompt_hints("does the update need anything", "a")["ids"] == []  # one plain word
    assert intuition.prompt_hints("does the installer update work", "a")["ids"] == []  # two plain words: 0.69.8 showed it
    assert intuition.prompt_hints("does the installer update need a restart", "a")["ids"] == [k.id]  # three


def test_history_and_done_knowledge_is_not_offered_but_still_found(gd):
    h = _k("proj-a history: the restart of the installer update was fixed", ["topic:release"], "proj-a-history")
    d = _k("the restart of the installer update was slow", ["topic:release", "state:done"], "proj-a")
    prompt = "the installer update needs a restart"
    assert _in("proj-a", lambda: intuition.prompt_hints(prompt, "a")["ids"]) == []
    found = [o.id for _s, o, _p in g.recall("installer restart", limit=10)]
    assert h.id in found and d.id in found


def test_the_history_index_counts_as_the_project_for_priority(gd):
    class O:
        idx, data = "proj-a-history", {}
    assert indexes.first(O, "proj-a") and not indexes.first(O, "proj-b")
    assert not indexes.foreign_project(O, "proj-a", {})


def test_special_vis_and_global_knowledge_are_never_foreign(gd):
    indexes.describe("ansible", "Ansible conventions", kind="special")
    s = _k("install a role with ansible-galaxy and pin the update version", ["tool:ansible"], "ansible")
    gl = _k("install the update and the installer with the package manager", ["topic:x"], "global")
    _k("proj-a code", ["topic:y"], "proj-a")
    kinds = {k: v["art"] for k, v in indexes.registry().items()}
    assert not indexes.foreign_project(s, "proj-a", kinds) and not indexes.foreign_project(gl, "proj-a", kinds)
    ids = _in("proj-a", lambda: intuition.prompt_hints("how do I install the update with the installer", "a")["ids"])
    assert gl.id in ids


def test_error_hints_from_other_projects_need_a_host_program_or_error_tag(gd):
    _k("proj-a builds with make", ["topic:build"], "proj-a")
    words_only = _k("timeout while waiting for the lock file of the build cache, deleted the stale lock", ["topic:cache"], "proj-b")
    err = "timeout while waiting for the lock file"
    assert _in("global", lambda: any(words_only.id in h for h in intuition.error_hints("Bash", {"command": "make all"}, err, "a")))
    assert _in("proj-a", lambda: not any(words_only.id in h for h in intuition.error_hints("Bash", {"command": "make all"}, err, "a")))

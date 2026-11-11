"""0.41.0: the view of a wiki page — heads, common ancestor, three-way merge on paragraphs, conflicts, deletion. Pure."""
import itertools
import random

from vi_mcp import wiki_merge as wm


def R(rev, parents, text, **kw):
    return wm.Rev(rev, list(parents), text, title=kw.pop("title", "Backup"), author=kw.pop("author", rev[:3]), **kw)


BASE = "Intro paragraph.\n\nStep one: stop the service.\n\nStep two: run borg.\n\nStep three: start the service."


def _dag(*revs):
    return {r.rev: r for r in revs}


def test_single_head_is_the_page():
    revs = _dag(R("r1", [], BASE), R("r2", ["r1"], BASE + "\n\nNote: check the log."))
    v = wm.view(revs, {"r1", "r2"})
    assert v.heads == ["r2"] and v.state == "current" and v.text.endswith("Note: check the log.")


def test_pending_revision_is_not_a_head():
    revs = _dag(R("r1", [], BASE), R("r2", ["r1"], "vandalised"))
    v = wm.view(revs, {"r1"})
    assert v.heads == ["r1"] and v.text == "\n\n".join(wm.paragraphs(BASE))


def test_changes_in_different_paragraphs_merge_silently():
    a = BASE.replace("Step one: stop the service.", "Step one: stop the service with systemctl stop app.")
    b = BASE.replace("Step three: start the service.", "Step three: start the service and check /health.")
    revs = _dag(R("r1", [], BASE), R("ra", ["r1"], a, author="alice"), R("rb", ["r1"], b, author="bob"))
    v = wm.view(revs, {"r1", "ra", "rb"})
    assert v.state == "merged" and v.merged_silently and not v.conflicts
    assert "systemctl stop app" in v.text and "check /health" in v.text


def test_neighbouring_paragraphs_merge_too():
    a = BASE.replace("Step one: stop the service.", "Step one: STOP.")
    b = BASE.replace("Step two: run borg.", "Step two: run borg create.")
    revs = _dag(R("r1", [], BASE), R("ra", ["r1"], a), R("rb", ["r1"], b))
    v = wm.view(revs, {"r1", "ra", "rb"})
    assert not v.conflicts and "STOP." in v.text and "borg create" in v.text


def test_same_paragraph_changed_differently_is_a_named_conflict():
    a = BASE.replace("Step two: run borg.", "Step two: run borg create ::nightly.")
    b = BASE.replace("Step two: run borg.", "Step two: run restic backup.")
    revs = _dag(R("r1", [], BASE), R("ra", ["r1"], a, author="alice"), R("rb", ["r1"], b, author="bob"))
    v = wm.view(revs, {"r1", "ra", "rb"})
    assert v.state == "conflict" and len(v.conflicts) == 1
    c = v.conflicts[0]
    assert c.a == ["Step two: run borg create ::nightly."] and c.b == ["Step two: run restic backup."] and {c.a_author, c.b_author} == {"alice", "bob"}
    assert wm.CONFLICT_OPEN in v.text and "restic" in v.text and "borg create" in v.text  # nothing disappears
    fixed = BASE.replace("Step two: run borg.", "Step two: run borg create ::nightly (restic was tried and dropped).")
    revs["rm"] = R("rm", ["ra", "rb"], fixed)  # a revision with both heads as parents resolves it
    v = wm.view(revs, {"r1", "ra", "rb", "rm"})
    assert v.state == "current" and v.heads == ["rm"] and wm.CONFLICT_OPEN not in v.text


def test_same_change_on_both_sides_is_no_conflict():
    a = BASE.replace("borg", "borg 1.4")
    revs = _dag(R("r1", [], BASE), R("ra", ["r1"], a), R("rb", ["r1"], a + "\n\nExtra."))
    v = wm.view(revs, {"r1", "ra", "rb"})
    assert not v.conflicts and v.text.count("borg 1.4") == 1


def test_two_roots_merge_against_empty():
    revs = _dag(R("x1", [], "Created on server A."), R("y1", [], "Created on server B."))
    v = wm.view(revs, {"x1", "y1"})
    assert v.heads == ["x1", "y1"] and len(v.conflicts) == 1  # both inserted at the start: ambiguous order


def test_deletion_and_restore():
    revs = _dag(R("r1", [], BASE), R("rd", ["r1"], "", deleted=True))
    assert wm.view(revs, {"r1", "rd"}).state == "deleted"
    revs["rr"] = R("rr", ["rd"], BASE)
    assert wm.view(revs, {"r1", "rd", "rr"}).state == "current"
    revs2 = _dag(R("r1", [], BASE), R("rd", ["r1"], "", deleted=True), R("rc", ["r1"], BASE + "\n\nMore."))
    v = wm.view(revs2, {"r1", "rd", "rc"})
    assert not v.deleted and v.deleted_by == ["rd"] and "More." in v.text  # deleted by one head only: page stays, deletion named


def test_forgotten_revision_keeps_ancestry_but_is_no_head():
    revs = _dag(R("r1", [], BASE), R("r2", ["r1"], None), R("r3", ["r2"], BASE + "\n\nLater."))
    assert wm.view(revs, {"r1", "r2", "r3"}).heads == ["r3"]
    revs = _dag(R("r1", [], BASE), R("r2", ["r1"], None))
    assert wm.view(revs, {"r1", "r2"}).heads == ["r1"]


def test_every_arrival_order_gives_the_same_view():
    """The property that makes it multi-master: the same revisions, in any order, the same page."""
    rnd = random.Random(7)
    paras = [f"Paragraph {i} about the restore." for i in range(8)]
    revs = [R("r0", [], "\n\n".join(paras))]
    for i in range(1, 7):
        parent = rnd.choice(revs)
        p = wm.paragraphs(parent.text)
        p[rnd.randrange(len(p))] = f"Changed by {i}."
        revs.append(R(f"r{i}", [parent.rev], "\n\n".join(p), author=f"s{i}"))
    views = set()
    for perm in itertools.islice(itertools.permutations(revs), 0, 720, 37):
        d = {}
        for r in perm:
            d[r.rev] = r
        v = wm.view(d, set(d))
        views.add((v.text, tuple(v.heads), len(v.conflicts)))
    assert len(views) == 1


def test_long_history_has_no_recursion_limit():
    revs = {"r0": R("r0", [], "start")}
    for i in range(1, 3000):
        revs[f"r{i}"] = R(f"r{i}", [f"r{i - 1}"], f"version {i}")
    assert wm.depth(revs, "r2999") == 3000 and wm.view(revs, set(revs)).text == "version 2999"

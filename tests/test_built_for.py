"""0.70.3: the origin record built_for — what a knowledge object was built for, fixed at its first save (genius project, exaptation)."""
import json

from vi_mcp import memory as g


def _stored_data(oid):
    return json.loads(g.db().execute("SELECT data FROM object WHERE id = ?", (oid,)).fetchone()[0])


def test_first_save_records_the_context_tags(gd):
    o = g.new_object("insight", "Proxy variables are missing in the container build", ["tool:docker", "topic:proxy", "host:web1.example"],
                     {"source": "test"}, who="ki@a", instance="a")
    bf = _stored_data(o.id)["built_for"]
    assert bf["tags"] == ["host:web1.example", "tool:docker", "topic:proxy"]  # kind:/instance: are not context
    assert bf["instance"] == "a" and bf["ts"] == o.ts


def test_tags_added_later_do_not_change_the_origin(gd):
    o = g.new_object("insight", "Proxy variables are missing in the container build", ["tool:docker"], {"source": "test"},
                     who="ki@a", instance="a")
    o2 = g.load(o.id)
    o2.hashtags = sorted(set(o2.hashtags) | {"tool:pip", "topic:python"})
    o2.data["built_for"] = {"tags": ["tool:pip"]}  # a caller trying to rewrite the origin
    g.save(o2)
    assert _stored_data(o.id)["built_for"]["tags"] == ["tool:docker"]
    g.update_data(o.id, lambda d: d.update(built_for={"tags": ["x:y"]}, note="kept"))
    g.db().commit()  # update_data leaves the commit to its caller
    d = _stored_data(o.id)
    assert d["built_for"]["tags"] == ["tool:docker"] and d["note"] == "kept"


def test_an_object_stored_before_the_record_existed_gets_a_named_unknown_origin(gd):
    o = g.new_object("insight", "An old finding without an origin record", ["tool:ssh"], {"source": "test"}, who="ki@a", instance="a")
    d = _stored_data(o.id)
    d.pop("built_for")  # as written by 0.70.2
    g.db().execute("UPDATE object SET data = ? WHERE id = ?", (json.dumps(d), o.id))
    g.db().commit()
    o2 = g.load(o.id)
    o2.hashtags = sorted(set(o2.hashtags) | {"tool:bash"})
    g.save(o2)
    bf = _stored_data(o.id)["built_for"]
    assert "tags" not in bf and bf["unknown"].startswith("stored before")


def test_experiences_carry_no_origin_record(gd):
    o = g.new_object("experience", "Bash ok", ["tool:Bash", "ok:yes"], {"source": "test"}, who="ki@a", instance="a")
    assert "built_for" not in _stored_data(o.id)

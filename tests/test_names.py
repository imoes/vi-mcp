"""0.67.0: the stored names are English. A database of 0.66.1 (tests/fixtures, synthetic) is migrated in place when it is opened:
backup copy first, every table and column renamed, the counts recorded — and afterwards no German stored name is left."""
import hashlib
import os
import sqlite3
from pathlib import Path

from vi_mcp import db as dbmod
from vi_mcp import db_migrate
from vi_mcp import logbook as lb
from vi_mcp import memory as g
from vi_mcp import names

FIXTURES = Path(__file__).parent / "fixtures"
PG = os.environ.get("VI_MCP_TEST_PG")
GERMAN_TABLES = set(names.TABLES) | set(names.LOGBOOK_TABLES)
GERMAN_COLUMNS = {old for m in names.COLUMNS.values() for old in m}


def _load(sql_file: str, target: Path) -> dict[str, int]:
    """The fixture into a SQLite file (and, when the suite runs against PostgreSQL, into the schema the test hooks give that file).
    Returns the row count per table before the migration."""
    con = sqlite3.connect(target)
    con.executescript((FIXTURES / sql_file).read_text(encoding="utf-8"))
    counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
              for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'objekt_fts_%'")}
    con.close()
    if PG:
        prefix = "t_" if sql_file.startswith("memory") else "l_"
        db_migrate.copy(target, PG, prefix + hashlib.md5(str(target).encode()).hexdigest()[:20], say=lambda *_a: None)
    return counts


def _english(con) -> tuple[set[str], dict[str, set[str]]]:
    tables = names._tables(con)
    return tables, {t: names._columns(con, t) for t in tables if not t.startswith("object_fts_")}


def _assert_no_german(con, before: dict[str, int], mapping: dict[str, str]) -> None:
    tables, columns = _english(con)
    assert not tables & GERMAN_TABLES, tables & GERMAN_TABLES
    left = {f"{t}.{c}" for t, cols in columns.items() for c in cols & set(names.COLUMNS.get(t, {}))}
    assert not left, left
    for old, n in before.items():  # nothing lost: every row is still there under the English name
        new = mapping.get(old, old)
        assert con.execute(f"SELECT COUNT(*) FROM {new}").fetchone()[0] == n, (old, new)


def _assert_no_german_values(con) -> None:
    """Step 2: no stored enum value and no value of the hashtags art:/modus: is German any more (counted per column, named)."""
    left = {}
    for table, col, m in names.VALUE_COLUMNS:
        if table in names._tables(con):
            old = [k for k, v in m.items() if k != v]
            n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({','.join('?' * len(old))})", old).fetchone()[0]
            if n:
                left[f"{table}.{col}"] = n
    for k, m in names.TAG_VALUES.items():
        old = [f"{k}:{o}" for o, n in m.items() if o != n]
        n = con.execute(f"SELECT COUNT(*) FROM tag WHERE tag IN ({','.join('?' * len(old))})", old).fetchone()[0]
        if n:
            left[f"tag {k}:"] = n
    vals = names._german_value_tags()
    n = con.execute(f"SELECT COUNT(*) FROM tag WHERE tag IN ({','.join('?' * len(vals))})", vals).fetchone()[0]
    if n:
        left["tag values"] = n
    import json as _json
    for kinds, path, m in names.DATA_VALUES:
        for (raw,) in con.execute(f"SELECT data FROM object WHERE kind IN ({','.join('?' * len(kinds))})", kinds):
            v = _json.loads(raw)
            for key in path:
                v = v.get(key) if isinstance(v, dict) else None
            assert not (isinstance(v, str) and (v in m and m[v] != v or v.startswith("netz:"))), (path, "German value in data")
    kinds = names._german_tag_kinds()
    n = con.execute(f"SELECT COUNT(*) FROM tag WHERE substr(tag, 1, instr(tag, ':') - 1) IN ({','.join('?' * len(kinds))})", kinds).fetchone()[0]
    if n:
        left["tag kinds"] = n
    import json
    for oid, raw in con.execute("SELECT id, data FROM object WHERE data LIKE '%reize%' OR data LIKE '%filter%' OR data LIKE '%derived_triggers%'"):
        d = json.loads(raw)
        assert not names._tags_in_data(json.loads(raw)), (oid, "hashtags in data still German")
        assert d.get("fremd_hashtags") is None or isinstance(d["fremd_hashtags"], list)
    for (raw,) in con.execute("SELECT data FROM object WHERE kind = 'self'"):
        assert not set(json.loads(raw).get("soll") or {}) & {"werte", "ziele", "stil", "grenzen"}
    assert not left, left
    _assert_no_german_data_keys(con)


def _german_keys(d, found: set, depth: int = 0) -> set:
    """German keys of names.DATA_KEYS anywhere in a data value, opaque subtrees left out (as names.data_keys leaves them)."""
    if isinstance(d, dict):
        for k, v in d.items():
            if k in names.DATA_KEYS and names.DATA_KEYS[k] != k:
                found.add(k)
            if k not in names.OPAQUE_DATA:
                _german_keys(v, found, depth + 1)
    elif isinstance(d, list):
        for x in d:
            _german_keys(x, found, depth + 1)
    return found


def _assert_no_german_data_keys(con) -> None:
    """Step 4a: no German key in the data of a domain object, none in any change history; the reports of sleep and model objects
    keep theirs until 0.68 (names.REPORT_KINDS) — named, not silently skipped."""
    import json
    left: dict[str, set] = {}
    domain = 0
    for oid, kind, raw, hist in con.execute("SELECT id, kind, data, changes FROM object"):
        if kind in names.DOMAIN_KINDS:
            domain += 1
            found = _german_keys(json.loads(raw or "{}"), set())
            if found:
                left[oid] = found
        for e in json.loads(hist or "[]"):
            assert set(e) <= {"ts", "who", "what", "reason"}, (oid, sorted(e))
    assert domain and not left, left


def test_the_mapping_is_one_to_one():
    for m in [names.TABLES, names.LOGBOOK_TABLES, names.INDEXES, *names.COLUMNS.values()]:
        assert len(set(m.values())) == len(m), m  # reversible: no two German names become one English name
        assert not set(m) & set(m.values()) - {k for k, v in m.items() if k == v}
    assert not set(names.TABLES.values()) & set(names.LOGBOOK_TABLES.values())
    reserved = {"from", "on", "group", "join", "order", "values", "select", "where", "table", "index"}
    every = set(names.TABLES.values()) | set(names.LOGBOOK_TABLES.values()) | {c for m in names.COLUMNS.values() for c in m.values()}
    assert not every & reserved


def test_a_0_66_1_memory_is_migrated_in_place_with_a_backup(tmp_path):
    p = tmp_path / "vi.db"
    before = _load("memory_0_66_1.sql", p)
    assert "objekt" in before and before["objekt"] >= 20
    g.open_db(p)
    try:
        with g.lock:
            _assert_no_german(g.db(), before, names.TABLES)
            rep = {cls: n for _s, cls, n, _t, _b in names.report(g.db())}
            backup = names.report(g.db())[0][4]
        assert rep["tables"] == len(before) - sum(1 for t in before if t in ("tag", "vi_index", "net_peer_removed"))
        assert rep["columns"] > 100
        if not PG:
            copy = Path(backup)
            assert copy.exists() and oct(copy.stat().st_mode & 0o777) == "0o600"
            old = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)  # the backup is the untouched 0.66.1 state
            assert old.execute("SELECT COUNT(*) FROM objekt").fetchone()[0] == before["objekt"]
            old.close()
        else:
            assert backup.startswith("schema t_") and backup.endswith("_pre_0_67_0")
        assert g.load(g.recall("thema:backup", viewer=None)[0][1].id).text == "Backups on db01.example run at 02:00"
        with g.lock:
            _assert_no_german_values(g.db())
            assert rep["object.kind"] >= 20 and rep["object.visibility"] >= 20 and rep["tag values"] >= 20 and rep["self areas"] == 1
        assert "stored names: English — migrated" in db_migrate._names_lines(g.db(), "object")
    finally:
        g.close_db()
    g.open_db(p)  # idempotent: the second start finds nothing to do and writes no second report
    try:
        with g.lock:
            assert names.report(g.db())[0][4] == backup and not names._pending_schema(g.db(), names.TABLES)
    finally:
        g.close_db()


def test_data_keys_are_english_at_save_and_keep_the_callers_dict(gd):
    """Step 4a: whatever keys a caller writes, the stored data of a domain object has the English ones — renamed in place, so a caller
    that holds o.data (or a nested part of it) across save still writes into the object. Sleep and model reports are left as built."""
    o = g.new_object("insight", "keys at save", ["topic:keys"], {"quelle": "t", "nuetzlich": {"ja": 1, "nein": 0, "n": 1}}, reason="T")
    d, inner = o.data, o.data["useful"]
    assert set(d) >= {"source", "useful"} and "quelle" not in d and inner == {"yes": 1, "no": 0, "n": 1}
    d["vorher"] = {"gezeigt": ["x"], "args": {"quelle": "stays: a tool argument"}}
    g.save(o)
    assert o.data is d and o.data["before"] == {"shown": ["x"], "args": {"quelle": "stays: a tool argument"}}
    d["after_save"] = 1  # the same dict: still the object's
    g.save(o)
    stored = g.load(o.id)
    assert stored.data["after_save"] == 1 and stored.changes[0].keys() == {"ts", "who", "what", "reason"}
    s = g.new_object("sleep", "a sleep report", [], {"schritte": {"1": {"zustand": "fertig"}}}, reason="T")
    assert g.load(s.id).data == {"schritte": {"1": {"zustand": "fertig"}}}  # 0.68 (step 4b) renames the reports with their readers


def test_update_data_writes_english_keys_too(gd):
    o = g.new_object("insight", "counter", ["topic:keys"], {"source": "t"}, reason="T")
    with g.lock:
        g.update_data(o.id, lambda d: d.__setitem__("nuetzlich", {"ja": 2}))
        g.db().commit()
    assert g.load(o.id).data["useful"] == {"yes": 2}


def test_a_new_memory_needs_no_migration(gd):
    with g.lock:
        assert names.report(g.db()) == [] and not names._pending_schema(g.db(), names.TABLES)
        tables, columns = _english(g.db())
    assert not tables & GERMAN_TABLES
    assert "stored names: English (created by 0.67.0" in db_migrate._names_lines(g.db(), "object")


def test_a_0_66_1_logbook_is_migrated(tmp_path):
    p = tmp_path / "netz.db"
    before = _load("logbook_0_66_1.sql", p)
    seed = tmp_path / "seed"
    seed.write_bytes(b"\x01" * 32)
    log = lb.Logbook(p, seed, [])
    _assert_no_german(log.db, before, names.LOGBOOK_TABLES)
    assert log.db.execute("SELECT failures, last_error FROM peer").fetchone()[0] == 1
    assert log.db.execute("SELECT type FROM entry").fetchone()[0] == "objekt"  # the wire form of a signed entry stays as it was signed
    assert {cls for _s, cls, *_r in names.report(log.db)} == {"tables", "columns"}


def test_the_archive_is_migrated(tmp_path):
    from vi_mcp import archive
    p = tmp_path / "vi.db"
    g.open_db(p)
    g.close_db()
    if not PG:
        a = sqlite3.connect(tmp_path / "vi-lager.db")
        a.executescript("DROP TABLE IF EXISTS object; DROP TABLE IF EXISTS conversation_raw;"
                        "CREATE TABLE objekt (id TEXT PRIMARY KEY, art TEXT NOT NULL, instanz TEXT NOT NULL, sicht TEXT NOT NULL, eingelagert TEXT NOT NULL, "
                        "modus_vorher TEXT NOT NULL, grund TEXT NOT NULL, roh BLOB NOT NULL);"
                        "INSERT INTO objekt VALUES ('erkenntnis:a', 'erkenntnis', 'anna', 'geteilt', '2026-11-01', 'aktiv', 'old', X'00');"
                        "CREATE TABLE gespraech_roh (serial TEXT PRIMARY KEY, eingelagert TEXT NOT NULL, roh BLOB NOT NULL, laenge INTEGER NOT NULL);")
        a.close()
    g.open_db(p)
    try:
        con = archive.db()
        tables, columns = _english(con)
        assert {"object", "conversation_raw"} <= tables and not tables & GERMAN_TABLES
        assert columns["object"] == {"id", "kind", "instance", "visibility", "archived", "mode_before", "reason", "raw"}
        if not PG:
            assert con.execute("SELECT kind, mode_before FROM object").fetchone() == ("insight", "active")  # step 2: the values too
    finally:
        g.close_db()


def test_a_full_disk_refuses_before_changing_anything(tmp_path, monkeypatch):
    if PG:
        return
    p = tmp_path / "vi.db"
    _load("memory_0_66_1.sql", p)
    monkeypatch.setattr(names.shutil, "disk_usage", lambda _p: type("U", (), {"free": 10})())
    try:
        g.open_db(p)
        raise AssertionError("expected a refusal")
    except RuntimeError as e:
        assert "nothing was changed" in str(e)
    con = sqlite3.connect(p)
    assert con.execute("SELECT COUNT(*) FROM objekt").fetchone()[0] > 0  # still the German schema
    con.close()
    assert dbmod.is_url("x") is False


def test_the_network_still_sees_the_wire_form_of_0_66(gd):
    """Signed entries and content hashes are the German wire form of every server before 0.67.0: the export translates back, the
    import reads it, and the same meaning keeps the same hash on both sides."""
    from vi_mcp import net_score, p2p
    o = g.new_object("insight", "The backup of db01.example runs at 02:00", ["thema:backup"], {"quelle": "crontab -l"}, instance="anna")
    assert o.id.startswith("insight:")  # the user's decision: only new ids are English
    wire, why = p2p.internal_form(o, {"netz_id": "a" * 32, "loesch_hash": "b" * 64})
    assert why is None and wire["art"] == "erkenntnis"
    assert net_score.local_form(o)["art"] == "erkenntnis"
    old_peer = {"art": "erkenntnis", "text": o.text, "inhalt": None, "hashtags": ["thema:backup"]}
    assert net_score.content_hash(net_score.local_form(o)) == net_score.content_hash(old_peer)


def test_german_values_of_older_clients_are_read_as_english(gd):
    o = g.new_object("erkenntnis", "kind given the old way", ["modus:aktiv"], {}, mode="aktiv", visibility="geteilt", instance="anna")
    assert (o.kind, o.mode, o.visibility) == ("insight", "active", "shared") and "mode:active" in o.hashtags
    assert [h[1].id for h in g.recall("art:erkenntnis kind given", viewer=None)] == [o.id]
    assert g.recall("art:insight kind given", viewer=None)[0][1].id == o.id


def test_hashtags_travel_in_the_wire_form_and_reserved_ones_never_pass(gd):
    from vi_mcp import checks, p2p
    o = g.new_object("insight", "nginx on web1.example needs a reload after a certificate change", ["thema:tls", "fehler:handshake"],
                     {"quelle": "journalctl -u nginx"}, instance="anna")
    assert {"topic:tls", "error:handshake"} <= set(o.hashtags)  # German kinds of an older client are stored English
    wire, why = p2p.internal_form(o, {"netz_id": "a" * 32, "loesch_hash": "b" * 64})
    assert why is None and wire["hashtags"] == ["fehler:handshake", "thema:tls"]
    good = {"art": "erkenntnis", "text": "A fact from a peer of 0.67.0 that writes English kinds", "quelle": "measured on the peer", "netz_id": "c" * 32,
            "loesch_hash": "d" * 64, "hashtags": ["topic:a", "net:firma", "netz:firma", "mode:active", "instance:x"]}
    assert checks.check(good).mem_object["hashtags"] == ["topic:a"]  # reserved in both languages
    assert checks.check({**good, "hashtags": ["topic:a", "location:MUC-1"]}).verdict == "ablehnen"
    assert checks.check({**good, "art": "suche", "name": "s", "reize": ["tool:x"], "filter": "mode:archived"}).verdict == "ablehnen"


def test_old_and_new_ids_are_found_alike(gd):
    """The user, 15.11.2026: "only new ids English". An id of 0.66 keeps its German prefix; a new object gets the English one; every
    lookup by kind or key finds both."""
    from vi_mcp import bandit, session
    old = g.new_object("insight", "a fact learned under 0.66", ["topic:ids"], {"quelle": "x"}, instance="anna", oid="erkenntnis:0123456789abcdef")
    new = g.new_object("insight", "a fact learned under 0.67", ["topic:ids"], {"quelle": "x"}, instance="anna")
    assert new.id.startswith("insight:") and old.id.startswith("erkenntnis:")
    for f in ("kind:insight topic:ids", "art:erkenntnis topic:ids"):
        assert {h[1].id for h in g.recall(f, viewer=None)} == {old.id, new.id}, f
    assert {h[1].id for h in g.recall("topic:ids", kinds=("insight",), viewer=None)} == {old.id, new.id}
    assert names.id_has_kind(old.id, "insight") and names.id_has_kind(new.id, "erkenntnis")
    assert old.id.startswith(bandit.HINT_KINDS) and new.id.startswith(bandit.HINT_KINDS)
    # a conversation of 0.66 is found by its serial; a new one is conversation:<serial>
    g.new_object("conversation", "old conversation", ["serial:20261101001"], {"serial": "20261101001"}, oid="gespraech:20261101001")
    assert g.load_keyed("conversation", "20261101001").id == "gespraech:20261101001"
    assert g.keyed_id("conversation", "20261101001") == "gespraech:20261101001" and g.keyed_id("conversation", "x9") == "conversation:x9"
    s = session.begin("anna", "test")
    assert g.load_keyed("conversation", s.serial).id == f"conversation:{s.serial}"
    session.finish(s.id)


def test_a_migrated_memory_stays_english_after_new_writes(tmp_path):
    """24.11.2026, production 0.71.1: every start renamed German values again (22 object.mode + 22 visibility, index sources, a tag).
    A database migrated from 0.66 keeps its German column DEFAULTs (SQLite's RENAME COLUMN does not touch them), so an INSERT that
    leaves a column out writes German; and the main loop wrote collective:ja/nein. After writes on every such path, nothing is German."""
    from vi_mcp import intuition, main_loop, session
    p = tmp_path / "vi.db"
    _load("memory_0_66_1.sql", p)
    g.open_db(p)
    try:
        with g.lock:  # the defaults are still the old ones — the reason the writes below must name their values
            ddl = g.db().execute("SELECT sql FROM sqlite_master WHERE name = 'object'").fetchone()[0]
        assert "DEFAULT 'aktiv'" in ddl and "DEFAULT 'geteilt'" in ddl
        serial = session.new_serial()  # the stub a process leaves when it dies before begin() saves the conversation
        o = g.new_object("insight", "an object in an index nobody created yet", ["topic:x"], {}, instance="a")
        o.idx = "fresh-index"
        g.save(o)  # memory.save creates the vi_index row
        with g.lock:
            g.db().execute("UPDATE object SET idx = 'orphan-index' WHERE id = ?", (o.id,))  # an index row missing at the next start
            g.db().execute("DELETE FROM vi_index WHERE name = 'orphan-index'")
            g.db().commit()
        for inst in ("a", "a", "b"):  # the loop's repeated-error rule, collective
            v = intuition.before("graylog_search", {"q": inst}, inst)
            intuition.after("graylog_search", {"q": inst}, False, 1, "ConnectionError: refused 10.0.0.1", None, v["vorher_id"], inst)
        assert main_loop.step() >= 1  # creates the rule (new_object writes its hashtags English)
        v = intuition.before("graylog_search", {"q": "c"}, "c")  # one more failure: the rule's hits change ...
        intuition.after("graylog_search", {"q": "c"}, False, 1, "ConnectionError: refused 10.0.0.1", None, v["vorher_id"], "c")
        main_loop.step()  # ... so the loop updates it (o.hashtags set directly, then save — the path that wrote collective:ja)
        with g.lock:  # checked now, before the next start's migration would rename what was written German
            stub = g.db().execute("SELECT mode, visibility FROM object WHERE id = ?", (names.new_id("conversation", serial),)).fetchone()
            assert stub == ("active", "shared")
            assert g.db().execute("SELECT source FROM vi_index WHERE name = 'fresh-index'").fetchone() == ("automatic",)
            assert not names._tags_pending(g.db()) and not names._value_pending(g.db(), names.VALUE_COLUMNS)
            _assert_no_german_values(g.db())
    finally:
        g.close_db()
    g.open_db(p)  # the next start: _migrate adds the missing index row (after the names migration has run)
    try:
        with g.lock:
            assert g.db().execute("SELECT kind, source FROM vi_index WHERE name = 'orphan-index'").fetchone() == ("project", "automatic")
            _assert_no_german_values(g.db())
    finally:
        g.close_db()

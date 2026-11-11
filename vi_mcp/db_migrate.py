"""Move a SQLite database to PostgreSQL (0.50.0): `vi-mcp db migrate`, `vi-mcp db status`.

The copy reads a consistent snapshot of the SQLite file (backup API), creates every table and index in the target schema from the
file's own definitions (translated by vi_mcp/db.py), copies the rows in batches and compares the row count of every table. It only
writes into an empty target: a target that already holds objects is refused, so nothing is merged or overwritten by accident.

Memory: `vi-mcp db migrate --to URL` — the configured SQLite file into the URL's schema, its long-term archive (<file>-lager.db) into
<schema>_lager. A network logbook: `vi-mcp db migrate --from /var/lib/vi-p2p/NETZ/netz.db --to URL --schema netz_NETZ`.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import db as dbmod

#: FTS5 keeps its index in shadow tables; PostgreSQL builds its own (tsvector) from the copied rows
_SHADOW = re.compile(r"^objekt_fts_(data|idx|content|docsize|config)$|^sqlite_")
BATCH = 1000


def _snapshot(src: Path, tmp: Path) -> sqlite3.Connection:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    t = sqlite3.connect(str(tmp))
    s.backup(t)  # consistent even while the service writes; the switch afterwards still needs the service stopped
    s.close()
    return t


def _if_not_exists(sql: str) -> str:
    return re.sub(r"^\s*CREATE\s+(VIRTUAL\s+|UNIQUE\s+)?(TABLE|INDEX)\s+(?!IF\s)", lambda m: f"CREATE {m.group(1) or ''}{m.group(2)} IF NOT EXISTS ",
                  sql, count=1, flags=re.I)


def copy(src: Path, url: str, schema: str | None = None, say=print) -> dict[str, tuple[int, int]]:
    """Copy all tables of the SQLite file src into the PostgreSQL schema (None = the URL's). Returns {table: (rows source, rows target)}.
    Raises ValueError if the target already holds rows in a table to be copied."""
    src = Path(src)
    if not src.exists():
        raise ValueError(f"{src} does not exist")
    with tempfile.TemporaryDirectory(prefix="vi-mcp-migrate-") as tmpdir:
        s = _snapshot(src, Path(tmpdir) / "snapshot.db")
        d = dbmod.connect(url, schema=schema)
        try:
            tables = [(n, sql) for n, sql in s.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL ORDER BY name")
                      if not _SHADOW.match(n)]
            for name, sql in tables:
                d.execute(_if_not_exists(sql))
            for (sql,) in s.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"):
                d.execute(_if_not_exists(sql))
            d.commit()
            busy = [n for n, _sql in tables if d.execute(f"SELECT 1 FROM {n} LIMIT 1").fetchone()]
            if busy:
                raise ValueError(f"target schema {d.schema} already holds rows in {', '.join(busy)} — migrate into an empty schema")
            report = {}
            for name, _sql in tables:
                cols = [r[1] for r in s.execute(f'PRAGMA table_info("{name}")')]
                insert = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                cur = s.execute(f'SELECT {", ".join(cols)} FROM "{name}"')
                n = 0
                while True:
                    rows = cur.fetchmany(BATCH)
                    if not rows:
                        break
                    d.executemany(insert, rows)
                    d.commit()
                    n += len(rows)
                report[name] = (s.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0], d.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                say(f"  {name}: {report[name][0]} → {report[name][1]}")
            # identity columns (SQLite INTEGER PRIMARY KEY): continue after the highest copied value
            for table, col in d.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                                        "AND is_identity = 'YES'").fetchall():
                d.execute(f"SELECT setval(pg_get_serial_sequence('{d.schema}.{table}', '{col}'), COALESCE((SELECT MAX({col}) FROM {table}), 0) + 1, false)")
            d.commit()
            return report
        finally:
            d.close()
            s.close()


def migrate_memory(src: Path, url: str, say=print) -> dict[str, tuple[int, int]]:
    """The memory file into the URL's schema, its archive (if any) into <schema>_lager."""
    say(f"memory {src} → {dbmod.redact(url)}")
    report = copy(src, url, say=say)
    archive = Path(src).with_name(f"{Path(src).stem}-lager.db")
    if archive.exists():
        con = dbmod.connect(url)
        schema = f"{con.schema}_lager"
        con.close()
        say(f"archive {archive} → schema {schema}")
        report.update({f"lager.{k}": v for k, v in copy(archive, url, schema=schema, say=say).items()})
    return report


def status() -> str:
    from . import config
    k = config.load()
    if dbmod.is_url(k.db):
        con = dbmod.connect(k.db)
        try:
            n = con.execute("SELECT COUNT(*) FROM objekt").fetchone()[0] if con.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'objekt'").fetchone() else 0
            version = con.execute("SHOW server_version").fetchone()[0]
            return f"database: PostgreSQL {version} · {dbmod.redact(k.db)} · schema {con.schema} · {n} objects"
        finally:
            con.close()
    p = Path(k.db)
    if not p.exists():
        return f"database: SQLite {p} (not created yet)"
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM objekt").fetchone()[0]
    finally:
        con.close()
    return f"database: SQLite {p} · {p.stat().st_size // 1024} KiB · {n} objects"


USAGE = """usage: vi-mcp db status
       vi-mcp db migrate --to postgresql://USER@HOST/DB [--from FILE --schema NAME]
Without --from: the configured memory (and its archive). Stop the service first; then set the URL (vi-mcp configure --set db=URL)
and start it again. The password never goes into the URL: ~/.pgpass of the service user, PGPASSFILE or peer authentication."""


def main(argv: list[str]) -> int:
    if argv[:1] == ["status"]:
        print(status())
        return 0
    if argv[:1] != ["migrate"] or "--to" not in argv:
        print(USAGE, file=sys.stderr)
        return 2
    opts = dict(zip(argv[1::2], argv[2::2]))
    url = opts.get("--to", "")
    if not dbmod.is_url(url):
        print("--to needs a postgresql:// URL", file=sys.stderr)
        return 2
    if re.search(r"://[^/@:]+:[^@]*@", url):
        print("no password in the URL — use ~/.pgpass of the service user, PGPASSFILE or peer authentication", file=sys.stderr)
        return 2
    try:
        if "--from" in opts:
            report = copy(Path(opts["--from"]), url, schema=opts.get("--schema"))
        else:
            from . import config
            k = config.load()
            if dbmod.is_url(k.db):
                print(f"the memory already uses PostgreSQL ({dbmod.redact(k.db)})", file=sys.stderr)
                return 2
            report = migrate_memory(Path(k.db), url)
    except (ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1
    differ = {t: v for t, v in report.items() if v[0] != v[1]}
    if differ:
        print("row counts differ: " + ", ".join(f"{t} {a}≠{b}" for t, (a, b) in differ.items()), file=sys.stderr)
        return 1
    print(f"migrated: {len(report)} tables, {sum(a for a, _b in report.values())} rows, every count equal.")
    if "--from" not in opts:
        print(f"Next: sudo vi-mcp configure --set db={dbmod.redact(url)} (restarts the service). The SQLite file stays as it is.")
    return 0

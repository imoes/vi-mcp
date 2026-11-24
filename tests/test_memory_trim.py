"""0.71.3: the loop gives the memory glibc keeps back to the system every TRIM_S seconds (malloc_trim). Measured on a production copy:
Python's memory flat, RSS +0.23 GB/h without it; with it RSS stayed at 1.0–1.3 GB."""
import sys

import pytest

from vi_mcp import main_loop


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(main_loop, "_last_trim", [0.0])
    for k, v in (("trim_laeufe", 0), ("trim_mb", 0), ("trim_zuletzt_mb", None), ("trim_verfuegbar", None)):
        monkeypatch.setitem(main_loop.progress, k, v)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc")
def test_trim_runs_and_is_counted():
    freed = main_loop.trim_memory()
    assert isinstance(freed, int) and main_loop.progress["trim_laeufe"] == 1 and main_loop.progress["trim_verfuegbar"] is True
    assert main_loop.progress["trim_zuletzt_mb"] == freed


def test_trim_runs_only_every_trim_s(monkeypatch):
    calls = []
    monkeypatch.setattr(main_loop, "trim_memory", lambda: calls.append(1) or 0)
    t = main_loop.TRIM_S + 10.0
    assert main_loop.maybe_trim(t) == 0 and main_loop.maybe_trim(t + 30) is None  # once, then not before TRIM_S
    assert main_loop.maybe_trim(t + main_loop.TRIM_S) == 0 and len(calls) == 2


def test_without_glibc_it_says_so_and_does_nothing(monkeypatch):
    import ctypes

    def no_libc(name, *a, **k):
        raise OSError(f"{name}: cannot open shared object file")
    monkeypatch.setattr(ctypes, "CDLL", no_libc)
    assert main_loop.trim_memory() is None and main_loop.progress["trim_verfuegbar"] is False
    assert main_loop.trim_memory() is None and main_loop.progress["trim_laeufe"] == 0

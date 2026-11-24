"""0.71.2: the server limits BLAS to one thread per call — concurrent searches each started a multi-threaded matrix product, and the
idle OpenBLAS workers spun (24.11.2026: 32 threads 482 CPU seconds vs 1 thread 39 for the same 1,600 products)."""
import pytest

from vi_mcp import server


def test_the_server_limits_blas_to_one_thread():
    threadpoolctl = pytest.importorskip("threadpoolctl")
    msg = server.limit_blas()
    assert msg.startswith("BLAS threads limited to 1")
    blas = [i for i in threadpoolctl.threadpool_info() if i.get("user_api") == "blas"]
    assert all(i["num_threads"] == 1 for i in blas)


def test_without_threadpoolctl_it_says_so(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_tpc(name, *a, **k):
        if name == "threadpoolctl":
            raise ImportError(name="threadpoolctl")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_tpc)
    assert server.limit_blas() == "BLAS threads not limited: threadpoolctl missing"

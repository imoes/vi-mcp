"""0.28.0: own embedding service — download checks, archive safety, Vulkan→CPU fallback, switching embed.url (no network, no real binary)."""
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from vi_mcp import config
from vi_mcp import embed_service as es


def test_download_rejects_wrong_hash(tmp_path, monkeypatch):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(es.urllib.request, "urlopen", lambda req, timeout: R(b"not the model"))
    with pytest.raises(ValueError, match="SHA256"):
        es._download("https://example/model.gguf", tmp_path / "m.gguf", "0" * 64)
    assert not (tmp_path / "m.gguf").exists() and not (tmp_path / "m.gguf.part").exists()  # nothing half-written stays
    ok = hashlib.sha256(b"not the model").hexdigest()
    assert es._download("https://example/model.gguf", tmp_path / "m.gguf", ok).read_bytes() == b"not the model"


def test_archive_member_outside_target_is_refused(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(ValueError, match="leaves the target"):
        es._extract(bad, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_extract_finds_server(tmp_path):
    arc = tmp_path / "llama.tar.gz"
    with tarfile.open(arc, "w:gz") as t:
        data = b"#!/bin/sh\necho version\n"
        info = tarfile.TarInfo("build/bin/llama-server")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    exe = es._extract(arc, tmp_path / "out")
    assert exe.name == "llama-server" and exe.stat().st_mode & 0o111


def test_setup_falls_back_to_cpu_and_switches(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"port": 8765, "embed": {"url": "https://old/embed/v1/embeddings"}}))
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    monkeypatch.setattr(es, "home", lambda: tmp_path / "embed")
    monkeypatch.setattr(es, "system", lambda: "linux")
    monkeypatch.setattr(es, "_download", lambda url, target, sha: target)
    monkeypatch.setattr(es, "_extract", lambda archive, into: into / "llama-server")
    monkeypatch.setattr(es, "_starts", lambda exe: (exe.parent.name.endswith("-cpu"), "libvulkan.so.1: cannot open"))
    monkeypatch.setattr(es, "detect_gpus", lambda: ([{"vendor": "amd", "name": "Radeon", "memory_mib": None, "driver": None}], {}))
    monkeypatch.setattr(es, "_devices", lambda exe: [])
    services = []
    monkeypatch.setattr(es, "_service_linux", lambda exe, model, port, name=es.SERVICE, args=None: services.append((exe, port)))
    monkeypatch.setattr(es, "rerank_probe", lambda port, q, docs, timeout_s=120: [0.5] * len(docs))
    monkeypatch.setattr(es, "probe", lambda port, texts, timeout_s=120: [[0.0] * es.MODEL_DIM])
    monkeypatch.setattr(es.os, "geteuid", lambda: 1000)
    from vi_mcp import setup as _setup
    monkeypatch.setattr(_setup, "_restart", lambda: None)
    r = es.setup(port=8767, switch=False)
    assert r["backend"] == "cpu" and "libvulkan" in r["tried"]["vulkan"] and services[0][1] == 8767 and r["device"] == "CPU"
    assert config.load(cfg).embed == {"url": "https://old/embed/v1/embeddings"}  # --no-switch keeps the old service
    r = es.setup(port=8767)
    assert config.load(cfg).embed == {"url": "http://127.0.0.1:8767/v1/embeddings"} and r["previous_url"] == "https://old/embed/v1/embeddings"


def test_model_file_must_be_the_pinned_one(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "home", lambda: tmp_path / "embed")
    other = tmp_path / "other.gguf"
    other.write_bytes(b"another quantisation")
    with pytest.raises(ValueError, match="not the pinned"):
        es.setup(model_file=other, switch=False)


def test_server_parameters_match_the_vectors():
    """Pooling and context decide the vector: they must stay those of the service the stored vectors came from."""
    c = es.command(Path("/x/llama-server"), Path("/m/bge.gguf"), 8767)
    assert c[c.index("--pooling") + 1] == "mean" and c[c.index("--ctx-size") + 1] == "8192" and "--embedding" in c
    assert c[c.index("--host") + 1] == "127.0.0.1"


def test_compare_reports_same_and_different_vectors(gd, monkeypatch):
    import numpy as np
    from vi_mcp import memory as g
    from vi_mcp import vector
    o = g.new_object("erkenntnis", "nginx reload only after nginx -t", ["thema:nginx"], {"quelle": "x"})
    v = np.random.default_rng(1).normal(size=es.MODEL_DIM).astype(np.float32)
    vector._table()
    with g.lock:
        g.db().execute("INSERT INTO vektor (id, dim, modell, zeit, roh) VALUES (?,?,?,?,?)", (o.id, len(v), "bge-m3", g.now(), v.tobytes()))
        g.db().commit()
    monkeypatch.setattr(es.config, "load", lambda: type("K", (), {"db": g.fpath_active})())
    monkeypatch.setattr(es, "probe", lambda port, texts, timeout_s=120: [list(v * 2.0)])  # same direction
    assert es.compare(sample=5)["verdict"] == "same vectors"
    monkeypatch.setattr(es, "probe", lambda port, texts, timeout_s=120: [list(-v)])
    assert es.compare(sample=5)["verdict"] == "different — do not switch"


def test_download_retries_a_dropped_connection(tmp_path, monkeypatch):
    # 0.60.0: a proxied connection to github.com closed once without a response (Windows test VM); the next try went through
    import http.client
    calls = []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return R(b"payload")
    monkeypatch.setattr(es.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(es, "DOWNLOAD_PAUSE_S", 0)
    ok = hashlib.sha256(b"payload").hexdigest()
    assert es._download("https://example/a.zip", tmp_path / "a.zip", ok).read_bytes() == b"payload" and len(calls) == 2
    calls.clear()
    with pytest.raises(ValueError, match="SHA256"):  # a wrong hash is not retried
        es._download("https://example/b.zip", tmp_path / "b.zip", "0" * 64)
    assert len(calls) == 2  # first try dropped, second delivered the wrong bytes

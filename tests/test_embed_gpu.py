"""0.60.0: the embedding service fits the hardware — GPUs are detected, the backend is chosen (CUDA → Vulkan → CPU) and accepted only when
llama-server lists a device of its kind. The trigger: on a Windows PC with an NVIDIA card `vi-mcp embed setup` reported "vulkan" — and a
Vulkan build without any GPU starts too ("Available devices: (none)", measured 12.11.2026). No network, no real binary."""
import json

import pytest

from vi_mcp import embed_service as es

NV_NEW = {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4070", "memory_mib": 12282, "driver": "581.57", "source": "nvidia-smi"}
NV_OLD = {**NV_NEW, "driver": "551.61"}
NV_ANCIENT = {**NV_NEW, "driver": "470.256"}
AMD = {"vendor": "amd", "name": "AMD Radeon 8060S", "memory_mib": 98304, "driver": None, "source": "sysfs"}


def test_nvidia_smi_output_is_parsed():
    g = es.parse_nvidia_smi("NVIDIA GeForce RTX 3070, 8192, 580.95.05\nNVIDIA RTX A2000, 6138, 580.95.05\n")
    assert [x["name"] for x in g] == ["NVIDIA GeForce RTX 3070", "NVIDIA RTX A2000"] and g[0]["memory_mib"] == 8192
    assert g[0]["driver"] == "580.95.05" and es.parse_nvidia_smi("") == []


def test_sysfs_cards_and_not_their_connectors(tmp_path):
    for card, vendor, vram in (("card0", "0x1002", str(96 << 30)), ("card1", "0x1234", None)):
        dev = tmp_path / card / "device"
        dev.mkdir(parents=True)
        (dev / "vendor").write_text(vendor + "\n")
        (dev / "device").write_text("0x1586\n")
        if vram:
            (dev / "mem_info_vram_total").write_text(vram)
    (tmp_path / "card0-HDMI-A-1").mkdir()
    g = es.parse_sysfs(tmp_path)
    assert [x["vendor"] for x in g] == ["amd", "other"] and g[0]["memory_mib"] == 96 * 1024
    assert [x["vendor"] for x in g if es.is_gpu(x)] == ["amd"]  # the QEMU display (1234) is no GPU


def test_windows_video_controllers():
    text = json.dumps([{"Name": "NVIDIA GeForce RTX 4070", "PNPDeviceID": "PCI\\VEN_10DE&DEV_2786&SUBSYS", "DriverVersion": "32.0.15.8157"},
                       {"Name": "Microsoft Basic Display Adapter", "PNPDeviceID": "ROOT\\BasicDisplay", "DriverVersion": "10.0"}])
    g = es.parse_win_video(text)
    assert [x["vendor"] for x in g] == ["nvidia", "other"] and [x["name"] for x in g if es.is_gpu(x)] == ["NVIDIA GeForce RTX 4070"]
    assert es.parse_win_video(json.dumps({"Name": "AMD Radeon", "PNPDeviceID": "PCI\\VEN_1002&DEV_1"}))[0]["vendor"] == "amd"  # one object, no list
    assert es.parse_win_video("not json") == []


def test_backend_order_follows_the_driver():
    assert [v for v, _ in es.choose_backends([NV_NEW])] == ["cuda-13", "cuda-12", "vulkan", "cpu"]
    assert [v for v, _ in es.choose_backends([NV_OLD])] == ["cuda-12", "vulkan", "cpu"]
    old = es.choose_backends([NV_ANCIENT])
    assert [v for v, _ in old] == ["vulkan", "cpu"] and "470 < 525" in old[0][1]  # the reason names the driver
    assert [v for v, _ in es.choose_backends([{**NV_NEW, "driver": None}])] == ["vulkan", "cpu"]  # card without nvidia-smi
    mism = es.choose_backends([{**NV_NEW, "driver": None}], smi_error="Failed to initialize NVML: Driver/library version mismatch\nNVML 580.178")
    assert "Driver/library version mismatch" in mism[0][1] and "reboot" in mism[0][1]  # the reason says why, measured on a test host
    assert [v for v, _ in es.choose_backends([AMD])] == ["vulkan", "cpu"]
    assert es.choose_backends([]) == [("cpu", "no GPU found")]


def test_a_requested_backend_is_exactly_that():
    assert es.choose_backends([NV_NEW], "cpu") == [("cpu", "requested")]
    assert [v for v, _ in es.choose_backends([NV_OLD], "cuda")] == ["cuda-12"]
    with pytest.raises(ValueError, match="no NVIDIA card"):
        es.choose_backends([AMD], "cuda")
    with pytest.raises(ValueError, match="must be one of"):
        es.choose_backends([], "metal")


def test_every_variant_has_a_pinned_build_on_both_systems():
    for system in ("linux", "win32"):
        for variant in ("cuda-13", "cuda-12", "rocm", "vulkan", "cpu"):
            files = es.BUILDS[(system, variant)]
            assert files and all(len(sha) == 64 for _n, sha in files)
            assert len(files) == (2 if variant.startswith("cuda") else 1)  # CUDA comes with its runtime


def test_device_list_decides_whether_a_gpu_computes():
    none = es.parse_devices("Available devices:\n  (none)\n")  # measured: Vulkan and CPU build without a GPU, 12.11.2026
    assert none == [] and es.device_for("vulkan", none) is None and es.device_for("cpu", none)["id"] == "CPU"
    devs = es.parse_devices("Available devices:\n  CUDA0: NVIDIA GeForce RTX 3070 (7972 MiB, 7600 MiB free)\n")
    assert devs[0] == {"id": "CUDA0", "name": "NVIDIA GeForce RTX 3070", "memory_mib": 7972, "free_mib": 7600}
    assert es.device_for("cuda-13", devs)["name"] == "NVIDIA GeForce RTX 3070" and es.device_for("vulkan", devs) is None
    intel = es.parse_devices("Available devices:\n  Vulkan0: Intel(R) UHD Graphics 770 (ADL-S GT1) (23823 MiB, 17414 MiB free)\n")
    assert intel[0]["name"] == "Intel(R) UHD Graphics 770 (ADL-S GT1)" and intel[0]["free_mib"] == 17414  # measured on a test host, 12.11.2026
    soft = es.parse_devices("Available devices:\n  Vulkan0: llvmpipe (LLVM 19.1.7, 256 bits)\n")
    assert soft and es.device_for("vulkan", soft) is None  # a software renderer is no GPU


def test_setup_takes_the_first_backend_that_lists_its_device(tmp_path, monkeypatch):
    # an NVIDIA card with a new driver: the CUDA 13 build lists nothing (say, an unsupported card), the CUDA 12 build lists CUDA0
    monkeypatch.setattr(es, "home", lambda: tmp_path / "embed")
    monkeypatch.setattr(es, "system", lambda: "linux")
    monkeypatch.setattr(es.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(es, "detect_gpus", lambda: ([NV_NEW], {}))
    monkeypatch.setattr(es, "_download", lambda url, target, sha: target)
    monkeypatch.setattr(es, "_install", lambda d, variant: d / f"llama-{variant}" / "llama-server")
    monkeypatch.setattr(es, "_starts", lambda exe: (True, ""))
    lists = {"llama-cuda-13": "Available devices:\n  (none)\n",
             "llama-cuda-12": "Available devices:\n  CUDA0: NVIDIA GeForce RTX 4070 (12282 MiB, 11000 MiB free)\n"}
    monkeypatch.setattr(es, "_devices", lambda exe: es.parse_devices(lists.get(exe.parent.name, "")))
    started = []
    monkeypatch.setattr(es, "_start_service", lambda exe, model, port, name=es.SERVICE, args=None: started.append(exe.parent.name))
    monkeypatch.setattr(es, "setup_reranker", lambda d, exe, variant, mode, switch: {"state": "stub"})
    monkeypatch.setattr(es, "probe", lambda port, texts, timeout_s=120: [[0.0] * es.MODEL_DIM for _ in texts])
    r = es.setup(port=8767, switch=False)
    assert r["backend"] == "cuda-12" and r["device"] == "NVIDIA GeForce RTX 4070 (12282 MiB)" and started == ["llama-cuda-12"]
    assert "lists no device" in r["tried"]["cuda-13"] and r["tried"]["cuda-12"] == "ok" and "vulkan" not in r["tried"]
    assert r["gpus"] == ["NVIDIA GeForce RTX 4070, 12282 MiB, driver 581.57"] and isinstance(r["ms_per_text"], float)


def _rerank_env(tmp_path, monkeypatch, seconds):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"port": 8765, "rerank": {"url": "https://old/rerank/v1/rerank"}}))
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    monkeypatch.setattr(es, "_download", lambda url, target, sha: target)
    started = []
    monkeypatch.setattr(es, "_start_service", lambda exe, model, port, name=es.SERVICE, args=None: started.append((name, model.name, args)))
    clock = iter([0.0, seconds])
    monkeypatch.setattr(es.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(es, "rerank_probe", lambda port, q, docs, timeout_s=120: [0.1] * len(docs))
    return cfg, started


def test_a_fast_reranker_is_switched_on_with_the_measured_parameters(tmp_path, monkeypatch):
    from vi_mcp import config
    cfg, started = _rerank_env(tmp_path, monkeypatch, 1.2)
    r = es.setup_reranker(tmp_path, tmp_path / "llama-server", "cuda-13", "auto", True)
    assert r["state"] == "used (rerank.url)" and r["seconds_for_30_documents"] == 1.2 and r["previous_url"] == "https://old/rerank/v1/rerank"
    assert config.load(cfg).rerank == {"url": "http://127.0.0.1:8768/v1/rerank"}
    assert started == [(es.RERANK_SERVICE, es.RERANK_MODEL_FILE, es.RERANK_ARGS)] and "--pooling" in es.RERANK_ARGS


def test_a_slow_reranker_is_installed_but_not_used_and_says_why(tmp_path, monkeypatch):
    from vi_mcp import config
    cfg, _ = _rerank_env(tmp_path, monkeypatch, 11.2)
    r = es.setup_reranker(tmp_path, tmp_path / "llama-server", "cpu", "auto", True)
    assert r["state"].startswith("installed, not used: 30 documents took 11.2 s on cpu (limit 5 s")
    assert config.load(cfg).rerank == {"url": "https://old/rerank/v1/rerank"}  # untouched
    cfg, _ = _rerank_env(tmp_path, monkeypatch, 11.2)
    assert es.setup_reranker(tmp_path, tmp_path / "llama-server", "cpu", "force", True)["state"] == "used (rerank.url)"
    assert es.setup_reranker(tmp_path, tmp_path / "x", "cpu", "off", True) == {"state": "not installed (--rerank off)"}


def test_remove_clears_only_urls_of_the_own_services(tmp_path, monkeypatch):
    from vi_mcp import config
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"embed": {"url": "http://127.0.0.1:8767/v1/embeddings"}, "rerank": {"url": "https://central/rerank/v1/rerank"}}))
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    monkeypatch.setattr(es, "home", lambda: tmp_path / "embed")
    monkeypatch.setattr(es, "system", lambda: "linux")
    monkeypatch.setattr(es.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(es.Path, "unlink", lambda self, missing_ok=False: None)
    r = es.remove()
    assert r["embed.url"] == "cleared" and r["rerank.url"] == "https://central/rerank/v1/rerank"
    assert config.load(cfg).embed is None and config.load(cfg).rerank == {"url": "https://central/rerank/v1/rerank"}

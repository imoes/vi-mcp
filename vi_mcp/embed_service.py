"""Own embedding service (0.28.0) and reranker (0.60.0): `vi-mcp embed setup|auto|compare|status|remove` — vectors without a foreign stack.

Until 0.27.0 vectors came only from an external OpenAI-compatible service (config `embed.url`). This module installs one that belongs to
vi-mcp, on Linux and Windows, and can be added later:
- llama.cpp `llama-server` from a pinned GitHub release, SHA256 checked — since 0.60.0 the build fits the hardware: CUDA with an NVIDIA
  driver, Vulkan with another GPU, else CPU, each accepted only if it lists its device (`detect_gpus`, `choose_backends`);
- the model bge-m3 Q4_K_M from a pinned Hugging Face file, SHA256 checked — byte-identical with the file the existing vectors were made with
  (checked 10.11.2026), so stored vectors stay valid and nothing has to be embedded again;
- a service of its own (systemd unit `vi-embed` / scheduled task `vi-embed`) on 127.0.0.1:<port>, separate from the vi-mcp process so
  embedding never blocks answers;
- `embed.url` in the configuration points to it (unless --no-switch), then vi-mcp is restarted.
An external service stays possible: set `embed.url` by hand as before.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import config

LLAMA_TAG = "b11938"  # llama.cpp release of 27.10.2026
_GH = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/"
#: (system, variant) → [(file, SHA256 from the GitHub release)]; the first archive holds llama-server, further ones (the CUDA runtime) are
#: put next to it. SHA256 from the release's asset digests (gh api repos/ggml-org/llama.cpp/releases/tags/b11938, 12.11.2026).
BUILDS = {
    ("linux", "cuda-13"): [(f"llama-{LLAMA_TAG}-bin-ubuntu-cuda-13.4-x64.tar.gz", "c129309799928e7c5483ff7cc9195e1ca3bec807f41bef13b839598b43bddfc1"),
                           (f"cudart-llama-{LLAMA_TAG}-bin-ubuntu-cuda-13.4-x64.tar.gz", "844ff9a6f2b8378cff323ad1b64be4b68edcde21e05e23720e8cbd2e73a1ae2f")],
    ("linux", "cuda-12"): [(f"llama-{LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz", "9e3c3f657f4708bf4bdc038dc22183d54035bb6e9b5baa9e4897c88701eb4c56"),
                           (f"cudart-llama-{LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz", "739ef042b1b77bf8db0f65709840fbdc102951b04ae9806c7919e7c035134505")],
    ("linux", "rocm"): [(f"llama-{LLAMA_TAG}-bin-ubuntu-rocm-10.0-x64.tar.gz", "b5b1ccec697c41f7f3bbc64dc54b55c9cbc04df0b02f2b6deeec97ef19844105")],
    ("linux", "vulkan"): [(f"llama-{LLAMA_TAG}-bin-ubuntu-vulkan-x64.tar.gz", "9d78c8eae0be03d36665753d1a1a7f360fd18186265f1064e07d8f64eff71f3c")],
    ("linux", "cpu"): [(f"llama-{LLAMA_TAG}-bin-ubuntu-x64.tar.gz", "0206adf559a226dfcafadf8051a91f1f813cf53b2ad570b1262658f1fddaefa4")],
    ("win32", "cuda-13"): [(f"llama-{LLAMA_TAG}-bin-win-cuda-13.4-x64.zip", "1bae5e2f84b0b6f7cd95683f755bc4fc1ca2790d16c022cf8cb91ca83038ff56"),
                           ("cudart-llama-bin-win-cuda-13.4-x64.zip", "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668")],
    ("win32", "cuda-12"): [(f"llama-{LLAMA_TAG}-bin-win-cuda-12.4-x64.zip", "91e8c63d59c080ea1b4f042911489b27d3ee019f323bc0556111c83dcab410c8"),
                           ("cudart-llama-bin-win-cuda-12.4-x64.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6")],
    ("win32", "rocm"): [(f"llama-{LLAMA_TAG}-bin-win-rocm-10.0-x64.zip", "1ba99610e93f351db1dec73a7639b94a2edc8d82d2854ec2bea52bbbda180c56")],
    ("win32", "vulkan"): [(f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip", "9ecd072c6e785fa2b932229c86f845695198195c4f29b99b85ed42dccb022aa6")],
    ("win32", "cpu"): [(f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip", "9e2fc62604446d86809ca09094d3c7a7329b723bda636e4bbd23c3ce62cb77dc")],
}
#: 0.60.0: minimum NVIDIA driver (major) for CUDA minor version compatibility — "CUDA 13.x >= 580", "CUDA 12.x >= 525"
#: (https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html, Table 3, read 12.11.2026)
CUDA13_MIN_DRIVER = 580
CUDA12_MIN_DRIVER = 525
BACKENDS = ("auto", "cuda", "vulkan", "rocm", "cpu")
#: PCI vendor ids
VENDORS = {"10de": "nvidia", "1002": "amd", "8086": "intel"}
#: adapters that are no GPU to compute on: virtual displays and software renderers
NOT_A_GPU = ("microsoft basic", "basic render", "llvmpipe", "swiftshader", "qemu", "virtualbox", "vmware svga", "standard vga", "hyper-v")
MODEL_FILE = "bge-m3-Q4_K_M.gguf"
MODEL_URL = "https://huggingface.co/gpustack/bge-m3-GGUF/resolve/main/bge-m3-Q4_K_M.gguf"
MODEL_SHA256 = "6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06"
MODEL_DIM = 1024
DEFAULT_PORT = 8767
#: the same server parameters as the service the existing vectors came from (pooling and context decide the vector)
SERVER_ARGS = ["--embedding", "--pooling", "mean", "--ctx-size", "8192", "--batch-size", "2048", "--ubatch-size", "2048", "-ngl", "99"]
SERVICE = "vi-embed"
#: 0.60.0: the reranker (cross-encoder) — the very file and parameters of the service the search was measured with (MRR 0.754 → 0.817 on
#: a production copy, 0.57.0): bge-reranker-v2-m3 Q4_K_M, sha256 checked against the production copy and Hugging Face (12.11.2026)
RERANK_MODEL_FILE = "bge-reranker-v2-m3-Q4_K_M.gguf"
RERANK_MODEL_URL = "https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/bge-reranker-v2-m3-Q4_K_M.gguf"
RERANK_MODEL_SHA256 = "e186a244ed455b4ab66ec64339ce7427a6ae13f5c0b5e544de96e50f0f8b3673"
RERANK_PORT = 8768
RERANK_SERVICE = "vi-rerank"
RERANK_ARGS = ["--embedding", "--pooling", "rank", "-c", "4096", "--parallel", "4", "--batch-size", "2048", "--ubatch-size", "2048", "-ngl", "99"]
#: a search waits for the reranker (vector.RERANK_TIMEOUT_S); one that needs longer than this for RERANK_TOP documents is installed but
#: not switched on — measured at setup, named in the report
RERANK_MAX_S = 5.0
RERANK_MODES = ("auto", "force", "off")


def system() -> str:
    return "win32" if os.name == "nt" else "linux"


def home() -> Path:
    if system() == "win32":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "vi-mcp" / "embed"
    return Path("/var/lib/vi-mcp/embed") if os.geteuid() == 0 else Path("~/.local/share/vi-mcp/embed").expanduser()


def parse_nvidia_smi(text: str) -> list[dict]:
    """`nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits` → one dict per card."""
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0]:
            mem = int(float(parts[1])) if parts[1].replace(".", "", 1).isdigit() else None
            out.append({"vendor": "nvidia", "name": parts[0], "memory_mib": mem, "driver": parts[2], "source": "nvidia-smi"})
    return out


def parse_sysfs(root: Path = Path("/sys/class/drm")) -> list[dict]:
    """Linux: the PCI vendor of every DRM card (card0, card1 …; not the connectors card0-HDMI-A-1)."""
    out = []
    for card in sorted(root.glob("card*")):
        if not card.name[4:].isdigit():
            continue
        dev = card / "device"
        try:
            vendor = (dev / "vendor").read_text().strip().lower().removeprefix("0x")
        except OSError:
            continue
        mem = None
        try:
            mem = int((dev / "mem_info_vram_total").read_text().strip()) // (1 << 20)  # amdgpu only
        except (OSError, ValueError):
            pass
        name = VENDORS.get(vendor, "other")
        try:
            device = (dev / "device").read_text().strip()
        except OSError:
            device = "?"
        out.append({"vendor": name, "name": f"{name} {vendor}:{device.removeprefix('0x')} ({card.name})", "memory_mib": mem, "driver": None,
                    "source": "sysfs"})
    return out


def parse_win_video(text: str) -> list[dict]:
    """Windows: `Get-CimInstance Win32_VideoController | Select-Object Name, PNPDeviceID, DriverVersion | ConvertTo-Json`."""
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for c in (data if isinstance(data, list) else [data]):
        name, pnp = str(c.get("Name") or ""), str(c.get("PNPDeviceID") or "").upper()
        vendor = next((v for k, v in VENDORS.items() if f"VEN_{k.upper()}" in pnp), "other")
        out.append({"vendor": vendor, "name": name, "memory_mib": None, "driver": c.get("DriverVersion"), "source": "Win32_VideoController"})
    return out


def is_gpu(g: dict) -> bool:
    """A card to compute on — not a virtual display adapter or a software renderer."""
    name = (g.get("name") or "").lower()
    return g.get("vendor") in ("nvidia", "amd", "intel") and not any(x in name for x in NOT_A_GPU)


def _run_text(cmd: list[str], timeout: int = 20) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exit {r.returncode}: {(r.stderr or r.stdout).strip()[:160]}")
    return r.stdout


def detect_gpus() -> tuple[list[dict], dict]:
    """(GPUs to compute on, {source: error}) — every source on its own; one that fails is named, the others still count.
    nvidia-smi knows the driver version (which CUDA build runs); the other sources only say that a card of a vendor is there."""
    gpus, errors = [], {}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            gpus += parse_nvidia_smi(_run_text([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"]))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            errors["nvidia-smi"] = str(e)[:200]
    try:
        if system() == "linux":
            other = parse_sysfs()
        else:
            other = parse_win_video(_run_text(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                               "Get-CimInstance Win32_VideoController | Select-Object Name, PNPDeviceID, DriverVersion | ConvertTo-Json"]))
        if any(g["vendor"] == "nvidia" for g in gpus):  # nvidia-smi already named them, with the driver
            other = [g for g in other if g["vendor"] != "nvidia"]
        gpus += other
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        errors["sysfs" if system() == "linux" else "Win32_VideoController"] = str(e)[:200]
    return [g for g in gpus if is_gpu(g)], errors


def _driver_major(g: dict) -> int | None:
    try:
        return int(str(g.get("driver") or "").split(".")[0])
    except ValueError:
        return None


def choose_backends(gpus: list[dict], requested: str = "auto", smi_error: str | None = None) -> list[tuple[str, str]]:
    """[(variant, why)] in the order to try. `requested` other than auto means exactly that backend — no silent fallback.
    `smi_error`: why nvidia-smi gave no driver version — named in the reason (a host after a driver update without reboot:
    "Driver/library version mismatch", 12.11.2026)."""
    nvidia = [g for g in gpus if g["vendor"] == "nvidia"]
    drivers = [d for d in (_driver_major(g) for g in nvidia) if d is not None]
    driver = max(drivers) if drivers else None
    cuda: list[tuple[str, str]] = []
    if driver is not None and driver >= CUDA13_MIN_DRIVER:
        cuda = [("cuda-13", f"NVIDIA driver {driver} ≥ {CUDA13_MIN_DRIVER}: CUDA 13"), ("cuda-12", "CUDA 12 if the CUDA 13 build does not run")]
    elif driver is not None and driver >= CUDA12_MIN_DRIVER:
        cuda = [("cuda-12", f"NVIDIA driver {driver} ≥ {CUDA12_MIN_DRIVER} and < {CUDA13_MIN_DRIVER}: CUDA 12")]
    if requested == "cpu":
        return [("cpu", "requested")]
    if requested == "vulkan":
        return [("vulkan", "requested")]
    if requested == "rocm":
        return [("rocm", "requested (needs ROCm installed)")]
    if requested == "cuda":
        if cuda:
            return cuda
        raise ValueError("--backend cuda: no NVIDIA card with nvidia-smi and a driver ≥ "
                         f"{CUDA12_MIN_DRIVER} found" + (f" (driver {driver})" if driver is not None else ""))
    if requested != "auto":
        raise ValueError(f"--backend must be one of {', '.join(BACKENDS)}")
    if cuda:
        return cuda + [("vulkan", "Vulkan if no CUDA build runs"), ("cpu", "CPU if no GPU build runs")]
    if nvidia:
        why = "NVIDIA card, but no driver version from nvidia-smi (proprietary driver missing?) — Vulkan"
        if smi_error:
            why = f"NVIDIA card, but nvidia-smi failed ({smi_error.splitlines()[0][:120]}; a driver update needs a reboot?) — Vulkan"
        if driver is not None:
            why = f"NVIDIA driver {driver} < {CUDA12_MIN_DRIVER}: too old for CUDA 12 — Vulkan"
        return [("vulkan", why), ("cpu", "CPU if Vulkan does not run")]
    if gpus:
        kinds = ", ".join(sorted({g["vendor"] for g in gpus}))
        return [("vulkan", f"{kinds} card: Vulkan (ROCm only with --backend rocm)"), ("cpu", "CPU if Vulkan does not run")]
    return [("cpu", "no GPU found")]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _download(url: str, target: Path, sha256: str) -> Path:
    """Download (proxy from the environment), check SHA256; a file already there with the right hash is reused."""
    if target.exists() and _sha256(target) == sha256:
        return target
    tmp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "vi-mcp-embed-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    got = _sha256(tmp)
    if got != sha256:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"{url}: SHA256 {got} ≠ expected {sha256} — not used")
    os.replace(tmp, target)
    return target


def _extract(archive: Path, into: Path) -> Path:
    """Unpack the llama.cpp archive; returns the path of llama-server(.exe). Refuses members that leave the target directory."""
    shutil.rmtree(into, ignore_errors=True)
    into.mkdir(parents=True)
    root = into.resolve()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if not (root / n).resolve().is_relative_to(root):
                    raise ValueError(f"{archive.name}: member {n} leaves the target directory")
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data")
    name = "llama-server.exe" if system() == "win32" else "llama-server"
    found = [p for p in into.rglob(name) if p.is_file()]
    if not found:
        raise ValueError(f"{archive.name}: no {name} inside")
    exe = found[0]
    if system() != "win32":
        exe.chmod(0o755)
    return exe


def _add_libraries(archive: Path, exe: Path) -> int:
    """The CUDA runtime archive: its libraries (.dll / .so*) go next to llama-server, where the loader looks. Returns how many."""
    tmp = exe.parent.parent / f".{archive.name}.unpack"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        root = tmp.resolve()
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                for n in z.namelist():
                    if not (root / n).resolve().is_relative_to(root):
                        raise ValueError(f"{archive.name}: member {n} leaves the target directory")
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp, filter="data")
        n = 0
        for p in tmp.rglob("*"):
            if p.is_file() and (p.suffix.lower() == ".dll" or ".so" in p.name):
                shutil.copy2(p, exe.parent / p.name)
                n += 1
        return n
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


#: device prefix in `llama-server --list-devices` per variant (CUDA0, Vulkan0, ROCm0)
DEVICE_PREFIX = {"cuda-13": ("CUDA",), "cuda-12": ("CUDA",), "vulkan": ("Vulkan",), "rocm": ("ROCm", "HIP")}


def parse_devices(text: str) -> list[dict]:
    """`llama-server --list-devices`: "Available devices:" then one line per device, "  (none)" without any.
    Measured without a GPU (12.11.2026, b11938, Vulkan and CPU build): "Available devices:\\n  (none)". A device line is read as
    "  NAME: DESCRIPTION (TOTAL MiB, FREE MiB free)"; the memory part is optional."""
    import re
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s+([A-Za-z]+\d+):\s*(.*?)\s*(?:\((\d+) MiB,\s*(\d+) MiB free\))?\s*$", line)
        if m:
            out.append({"id": m.group(1), "name": m.group(2), "memory_mib": int(m.group(3)) if m.group(3) else None,
                        "free_mib": int(m.group(4)) if m.group(4) else None})
    return out


def _devices(exe: Path) -> list[dict]:
    env = {**os.environ, "LD_LIBRARY_PATH": str(exe.parent)} if system() == "linux" else None
    r = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True, timeout=60, env=env)
    return parse_devices((r.stdout or "") + "\n" + (r.stderr or ""))


def device_for(variant: str, devices: list[dict]) -> dict | None:
    """The device a GPU build will compute on — None if it lists none of its kind (it would run on the CPU) or only a software renderer."""
    if variant == "cpu":
        return {"id": "CPU", "name": "CPU", "memory_mib": None, "free_mib": None}
    want = DEVICE_PREFIX.get(variant, ())
    for d in devices:
        if d["id"].startswith(want) and not any(x in d["name"].lower() for x in NOT_A_GPU):
            return d
    return None


def _starts(exe: Path) -> tuple[bool, str]:
    """Does the binary start at all (missing libvulkan etc.)?"""
    env = {**os.environ, "LD_LIBRARY_PATH": str(exe.parent)} if system() == "linux" else None
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-300:]


def command(exe: Path, model: Path, port: int, args: list[str] | None = None) -> list[str]:
    return [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), *(SERVER_ARGS if args is None else args)]


def _service_linux(exe: Path, model: Path, port: int, name: str = SERVICE, args: list[str] | None = None) -> None:
    what = "reranker" if name == RERANK_SERVICE else "embedding service"
    unit = f"""[Unit]
Description={name} — {what} of vi-mcp (llama.cpp {LLAMA_TAG}, {model.name}) on 127.0.0.1:{port}
After=network.target

[Service]
User=vi-mcp
Group=vi-mcp
SupplementaryGroups=render video
Environment=LD_LIBRARY_PATH={exe.parent}
ExecStart={" ".join(command(exe, model, port, args))}
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths={exe.parent.parent} {model.parent}

[Install]
WantedBy=multi-user.target
"""
    Path(f"/etc/systemd/system/{name}.service").write_text(unit)
    for c in (["systemctl", "daemon-reload"], ["systemctl", "enable", name], ["systemctl", "restart", name]):
        subprocess.run(c, check=True, capture_output=True, timeout=60)


def _service_windows(exe: Path, model: Path, port: int, name: str = SERVICE, args: list[str] | None = None) -> None:
    SERVICE = name  # noqa: N806 — the task name below
    args = " ".join(f'"{a}"' if " " in a else a for a in command(exe, model, port, args)[1:])
    ps = (f"$a = New-ScheduledTaskAction -Execute '{exe}' -Argument '{args}' -WorkingDirectory '{exe.parent}';"
          "$t = New-ScheduledTaskTrigger -AtStartup;"
          "$p = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest;"
          "$s = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) "
          "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable;"
          f"if (Get-ScheduledTask -TaskName '{SERVICE}' -ErrorAction SilentlyContinue) {{ Stop-ScheduledTask -TaskName '{SERVICE}';"
          f" Unregister-ScheduledTask -TaskName '{SERVICE}' -Confirm:$false }};"
          f"Register-ScheduledTask -TaskName '{SERVICE}' -Action $a -Trigger $t -Principal $p -Settings $s | Out-Null;"
          f"Start-ScheduledTask -TaskName '{SERVICE}'")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True, capture_output=True, timeout=120)


def probe(port: int, texts: list[str], timeout_s: float = 120) -> list[list[float]]:
    """Wait for the service and embed `texts` (OpenAI-compatible); raises if it does not answer in time."""
    url = f"http://127.0.0.1:{port}/v1/embeddings"
    end = time.monotonic() + timeout_s
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last = ""
    while time.monotonic() < end:
        try:
            body = json.dumps({"input": texts}).encode()
            with op.open(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=60) as r:
                data = json.load(r)["data"]
            return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
        except Exception as e:  # noqa: BLE001 — still starting (model loading)
            last = str(e)
            time.sleep(2)
    raise RuntimeError(f"{url} did not answer within {timeout_s:.0f} s: {last}")


#: texts for the speed measurement after setup (the time per text goes into the report)
TIMING_TEXTS = [f"vi-mcp timing text {i}: the service restarts after the upgrade and the agent reconnects to port {8000 + i}" for i in range(32)]


def _install(d: Path, variant: str) -> Path:
    """Download (SHA256 checked) and unpack the build of `variant`; the CUDA runtime goes next to llama-server."""
    files = BUILDS[(system(), variant)]
    archives = [_download(_GH + name, d / name, sha) for name, sha in files]
    exe = _extract(archives[0], d / f"llama-{LLAMA_TAG}-{variant}")
    for extra in archives[1:]:
        if not _add_libraries(extra, exe):
            raise ValueError(f"{extra.name}: no libraries inside")
    return exe


def _start_service(exe: Path, model: Path, port: int, name: str = SERVICE, args: list[str] | None = None) -> None:
    if system() == "linux":
        _service_linux(exe, model, port, name, args)
    else:
        _service_windows(exe, model, port, name, args)


RERANK_QUERY = "why does the agent lose its connection after the upgrade"
#: RERANK_TOP documents of the length vi_recall sends (vector.RERANK_CHARS) — the measured case is the real one
RERANK_DOCS = [(f"Document {i}: after the upgrade of the service the agent reconnects to port {8000 + i}; the log shows a timeout, "
                "the configuration was kept and the restart order matters. ") * 12 for i in range(30)]


def rerank_probe(port: int, query: str, documents: list[str], timeout_s: float = 120) -> list[float]:
    """Wait for the reranker and score `documents` (llama.cpp /v1/rerank, Jina form — what vector.rerank_scores sends)."""
    url = f"http://127.0.0.1:{port}/v1/rerank"
    end = time.monotonic() + timeout_s
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last = ""
    while time.monotonic() < end:
        try:
            body = json.dumps({"query": query, "documents": documents, "top_n": len(documents)}).encode()
            with op.open(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=120) as r:
                res = json.load(r)["results"]
            scores = [0.0] * len(documents)
            for item in res:
                scores[int(item["index"])] = float(item["relevance_score"])
            return scores
        except Exception as e:  # noqa: BLE001 — still starting
            last = str(e)
            time.sleep(2)
    raise RuntimeError(f"{url} did not answer within {timeout_s:.0f} s: {last}")


def setup_reranker(d: Path, exe: Path, variant: str, mode: str, switch: bool, port: int = RERANK_PORT) -> dict:
    """The reranker on the build the embedding service runs on. Switched on (config rerank.url) only if RERANK_TOP documents take at most
    RERANK_MAX_S — or with mode force; otherwise installed, not used, and the report says why."""
    if mode == "off":
        return {"state": "not installed (--rerank off)"}
    model = d / RERANK_MODEL_FILE
    _download(RERANK_MODEL_URL, model, RERANK_MODEL_SHA256)
    _start_service(exe, model, port, RERANK_SERVICE, RERANK_ARGS)
    rerank_probe(port, RERANK_QUERY, RERANK_DOCS[:2])  # waits until the model is loaded
    t0 = time.monotonic()
    scores = rerank_probe(port, RERANK_QUERY, RERANK_DOCS)
    took = time.monotonic() - t0
    out = {"service": f"{RERANK_SERVICE} on 127.0.0.1:{port}", "model": f"{RERANK_MODEL_FILE} sha256 {RERANK_MODEL_SHA256[:12]}…",
           "seconds_for_30_documents": round(took, 2), "scored": len(scores)}
    url = f"http://127.0.0.1:{port}/v1/rerank"
    if took > RERANK_MAX_S and mode != "force":
        out["state"] = f"installed, not used: {len(RERANK_DOCS)} documents took {took:.1f} s on {variant} (limit {RERANK_MAX_S:.0f} s; --rerank force uses it anyway)"
    elif switch:
        out["previous_url"] = (config.load().rerank or {}).get("url")
        config.set_rerank({"url": url})
        out["state"] = "used (rerank.url)"
    else:
        out["state"] = "installed, rerank.url unchanged (--no-switch)"
    return out


def setup(port: int = DEFAULT_PORT, cpu: bool = False, model_file: Path | None = None, switch: bool = True, backend: str = "auto",
          rerank: str = "auto") -> dict:
    """0.60.0: the backend is chosen from the GPUs found (CUDA → Vulkan → CPU) and accepted only when llama-server lists a device of its
    kind, the service answers and the speed is measured — "it starts" alone said nothing (a Vulkan build without a GPU starts and lists
    "(none)", measured 12.11.2026). The report names cards, backend, device, the reason and every rejected try."""
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    report: dict = {"dir": str(d), "llama": LLAMA_TAG}
    gpus, errors = detect_gpus()
    report["gpus"] = [f"{g['name']}" + (f", {g['memory_mib']} MiB" if g.get("memory_mib") else "") + (f", driver {g['driver']}" if g.get("driver") else "")
                      for g in gpus] or "none found"
    if errors:
        report["detect_errors"] = errors
    candidates = choose_backends(gpus, "cpu" if cpu else backend, errors.get("nvidia-smi"))
    model = d / MODEL_FILE
    if model_file:  # an existing local copy (e.g. of the old service) — accepted only with the pinned hash
        if _sha256(model_file) != MODEL_SHA256:
            raise ValueError(f"{model_file}: not the pinned bge-m3 Q4_K_M (SHA256 differs)")
        if not (model.exists() and _sha256(model) == MODEL_SHA256):
            shutil.copyfile(model_file, model)
    else:
        _download(MODEL_URL, model, MODEL_SHA256)
    report["model"] = f"{MODEL_FILE} sha256 {MODEL_SHA256[:12]}…"
    if system() == "linux" and os.geteuid() == 0:
        shutil.chown(d, "vi-mcp", "vi-mcp")
    tried: dict[str, str] = {}
    chosen = None
    for variant, why in candidates:
        try:
            exe = _install(d, variant)
            ok, msg = _starts(exe)
            if not ok:
                tried[variant] = f"does not start: {msg}"
                continue
            dev = device_for(variant, _devices(exe))
            if dev is None:
                tried[variant] = "starts, but lists no device of its kind (it would compute on the CPU)"
                continue
            _start_service(exe, model, port)
            v = probe(port, ["vi-mcp embedding test"])[0]
            if len(v) != MODEL_DIM:
                tried[variant] = f"unexpected dimension {len(v)} (expected {MODEL_DIM})"
                continue
            t0 = time.monotonic()
            probe(port, TIMING_TEXTS)
            ms = (time.monotonic() - t0) * 1000 / len(TIMING_TEXTS)
            tried[variant] = "ok"
            chosen = (variant, why, dev, ms, exe)
            break
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            tried[variant] = f"{type(e).__name__}: {str(e)[:200]}"
    report["tried"] = tried
    if chosen is None:
        raise RuntimeError(f"no backend works: {report}")
    variant, why, dev, ms, exe = chosen
    report["backend"], report["why"] = variant, why
    report["device"] = dev["name"] + (f" ({dev['memory_mib']} MiB)" if dev.get("memory_mib") else "")
    report["ms_per_text"] = round(ms, 1)
    report["service"] = f"{SERVICE} on 127.0.0.1:{port}, dimension {MODEL_DIM}"
    try:
        report["reranker"] = setup_reranker(d, exe, variant, rerank, switch)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:  # the vectors work without it
        report["reranker"] = {"state": f"failed: {type(e).__name__}: {str(e)[:200]}"}
    if switch:
        report["previous_url"] = (config.load().embed or {}).get("url")
        config.set_embed({"url": f"http://127.0.0.1:{port}/v1/embeddings"})
        from . import setup as _setup
        report["restart"] = _setup._restart() or "ok"
    report["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:  # 0.60.0: status shows it; an update decides from it whether setup must run again
        (d / "setup.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    except OSError:
        pass
    return report


def compare(port: int = DEFAULT_PORT, sample: int = 30) -> dict:
    """Embed the texts of `sample` stored vectors again with the service on `port` and compare (cosine). Read-only on the database.
    Same model and parameters → cosine ≈ 1; anything clearly below means: the stored vectors would not fit, do not switch."""
    import sqlite3
    import numpy as np
    db = config.load().db
    from . import db as dbmod
    c = dbmod.connect_readonly(db)
    rows = c.execute("SELECT o.text, v.roh, v.dim FROM vektor v JOIN objekt o ON o.id = v.id WHERE length(o.text) > 0 "
                     "ORDER BY random() LIMIT ?", (sample,)).fetchall()
    c.close()
    if not rows:
        raise RuntimeError("no stored vectors to compare with")
    new = probe(port, [r[0] for r in rows])
    cos = []
    for (text, raw, dim), v in zip(rows, new):
        a = np.frombuffer(raw, dtype=np.float32, count=dim)
        b = np.asarray(v, dtype=np.float32)
        cos.append(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b))) if len(b) == dim else float("nan"))
    ok = [x for x in cos if x == x]
    return {"compared": len(cos), "dimension_mismatch": len(cos) - len(ok), "cosine_min": round(min(ok), 5) if ok else None,
            "cosine_median": round(sorted(ok)[len(ok) // 2], 5) if ok else None,
            "verdict": "same vectors" if ok and len(ok) == len(cos) and min(ok) >= 0.99 else "different — do not switch"}


def _service_state(name: str) -> str:
    if system() == "linux":
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
        return r.stdout.strip() or r.stderr.strip()
    r = subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True, text=True)
    return "registered" if r.returncode == 0 else "not registered"


def status() -> dict:
    k = config.load()
    out: dict = {"embed.url": (k.embed or {}).get("url") or "— (no vectors)", "rerank.url": (k.rerank or {}).get("url") or "— (no reranker)",
                 "dir": str(home())}
    out["service"] = _service_state(SERVICE)
    out["reranker_service"] = _service_state(RERANK_SERVICE)
    try:
        last = json.loads((home() / "setup.json").read_text())
        out["last_setup"] = {k2: last.get(k2) for k2 in ("backend", "device", "why", "ms_per_text", "time")}
    except (OSError, ValueError):
        out["last_setup"] = "— (no setup.json)"
    return out


def _local(url: str, suffix: str) -> bool:
    return url.startswith("http://127.0.0.1:") and url.endswith(suffix)


def remove() -> dict:
    """Stop and remove both services and their files; embed.url / rerank.url are cleared only if they pointed to these services."""
    for name in (SERVICE, RERANK_SERVICE):
        if system() == "linux":
            subprocess.run(["systemctl", "disable", "--now", name], capture_output=True, timeout=60)
            Path(f"/etc/systemd/system/{name}.service").unlink(missing_ok=True)
        else:
            subprocess.run(["schtasks", "/End", "/TN", name], capture_output=True)
            subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
    if system() == "linux":
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=60)
    shutil.rmtree(home(), ignore_errors=True)
    k = config.load()
    out: dict = {"removed": True}
    url = (k.embed or {}).get("url") or ""
    if _local(url, "/v1/embeddings"):
        config.set_embed(None)
        out["embed.url"] = "cleared"
    else:
        out["embed.url"] = url or "—"
    rurl = (k.rerank or {}).get("url") or ""
    if _local(rurl, "/v1/rerank"):
        config.set_rerank(None)
        out["rerank.url"] = "cleared"
    else:
        out["rerank.url"] = rurl or "—"
    return out


def plan_auto(k=None) -> tuple[bool, str, str]:
    """0.60.0, for the packages (`vi-mcp embed auto`, debconf/menu question local_models, MSI checkbox): (run setup?, why, rerank mode).
    Never touches an external service: an embed.url that does not point to this machine's own service is kept (production setups);
    an external rerank.url is kept too (the reranker is then not installed). Runs again when the pinned llama.cpp or a model changed."""
    k = k or config.load()
    url = (k.embed or {}).get("url") or ""
    rurl = (k.rerank or {}).get("url") or ""
    rerank = "off" if rurl and not _local(rurl, "/v1/rerank") else "auto"
    if url and not _local(url, "/v1/embeddings"):
        return False, "embed.url points to an external service — kept", rerank
    if not url:
        return True, "no embedding service configured yet", rerank
    try:
        last = json.loads((home() / "setup.json").read_text())
    except (OSError, ValueError):
        return True, "local service without setup.json (set up before 0.60.0: no GPU detection yet)", rerank
    if last.get("llama") != LLAMA_TAG:
        return True, f"llama.cpp {last.get('llama')} → {LLAMA_TAG}", rerank
    if not str(last.get("model") or "").startswith(f"{MODEL_FILE} sha256 {MODEL_SHA256[:12]}"):
        return True, "the embedding model changed", rerank
    if rerank == "auto" and not last.get("reranker"):
        return True, "the reranker is not set up yet", rerank
    return False, f"local service up to date ({last.get('backend')}, {last.get('device')})", rerank


def auto() -> dict:
    run, why, rerank = plan_auto()
    if not run:
        return {"skipped": why}
    r = setup(rerank=rerank)
    r["because"] = why
    return r


def main(argv: list[str]) -> int:
    import argparse
    a = argparse.ArgumentParser(prog="vi-mcp embed", description="own embedding service of vi-mcp (llama.cpp + bge-m3)")
    u = a.add_subparsers(dest="cmd", required=True)
    s = u.add_parser("setup", help="install or update the service and use it")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--backend", choices=BACKENDS, default="auto",
                   help="auto (default): CUDA with an NVIDIA driver, else Vulkan with a GPU, else CPU — each accepted only if it lists its device")
    s.add_argument("--cpu", action="store_true", help="same as --backend cpu")
    s.add_argument("--rerank", choices=RERANK_MODES, default="auto",
                   help=f"reranker (bge-reranker-v2-m3): auto = install, use it if {len(RERANK_DOCS)} documents take ≤ {RERANK_MAX_S:.0f} s; force; off")
    s.add_argument("--model-file", type=Path, help="use this local copy of bge-m3-Q4_K_M.gguf (checked by SHA256) instead of downloading")
    s.add_argument("--no-switch", action="store_true", help="install and start, but keep embed.url as it is (to compare first)")
    c = u.add_parser("compare", help="compare stored vectors with the service (read-only), before switching")
    c.add_argument("--port", type=int, default=DEFAULT_PORT)
    c.add_argument("--sample", type=int, default=30)
    au = u.add_parser("auto", help="what the packages run: set up only if no external service is configured and something is missing or outdated")
    au.add_argument("--dry-run", action="store_true", help="only say whether and why")
    u.add_parser("status")
    u.add_parser("remove")
    o = a.parse_args(argv)
    try:
        if o.cmd == "setup":
            if not 1024 <= o.port <= 65535:
                raise ValueError("port must be a number from 1024 to 65535")
            r = setup(o.port, o.cpu, o.model_file, not o.no_switch, o.backend, o.rerank)
        elif o.cmd == "auto":
            if o.dry_run:
                run, why, rerank = plan_auto()
                r = {"would_run": run, "why": why, "reranker": rerank}
            else:
                r = auto()
        elif o.cmd == "compare":
            r = compare(o.port, o.sample)
        elif o.cmd == "status":
            r = status()
        else:
            r = remove()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(f"vi-mcp embed {o.cmd}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0

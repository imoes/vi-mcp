"""Own embedding service (0.28.0): `vi-mcp embed setup|status|remove` — vectors without a foreign stack.

Until 0.27.0 vectors came only from an external OpenAI-compatible service (config `embed.url`). This module installs one that belongs to
vi-mcp, on Linux and Windows, and can be added later:
- llama.cpp `llama-server` from a pinned GitHub release (Vulkan build, the CPU build if Vulkan does not start), SHA256 checked;
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
#: (system, variant) → (file, SHA256 from the GitHub release)
BUILDS = {
    ("linux", "vulkan"): (f"llama-{LLAMA_TAG}-bin-ubuntu-vulkan-x64.tar.gz", "9d78c8eae0be03d36665753d1a1a7f360fd18186265f1064e07d8f64eff71f3c"),
    ("linux", "cpu"): (f"llama-{LLAMA_TAG}-bin-ubuntu-x64.tar.gz", "0206adf559a226dfcafadf8051a91f1f813cf53b2ad570b1262658f1fddaefa4"),
    ("win32", "vulkan"): (f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip", "9ecd072c6e785fa2b932229c86f845695198195c4f29b99b85ed42dccb022aa6"),
    ("win32", "cpu"): (f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip", "9e2fc62604446d86809ca09094d3c7a7329b723bda636e4bbd23c3ce62cb77dc"),
}
MODEL_FILE = "bge-m3-Q4_K_M.gguf"
MODEL_URL = "https://huggingface.co/gpustack/bge-m3-GGUF/resolve/main/bge-m3-Q4_K_M.gguf"
MODEL_SHA256 = "6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06"
MODEL_DIM = 1024
DEFAULT_PORT = 8767
#: the same server parameters as the service the existing vectors came from (pooling and context decide the vector)
SERVER_ARGS = ["--embedding", "--pooling", "mean", "--ctx-size", "8192", "--batch-size", "2048", "--ubatch-size", "2048", "-ngl", "99"]
SERVICE = "vi-embed"


def system() -> str:
    return "win32" if os.name == "nt" else "linux"


def home() -> Path:
    if system() == "win32":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "vi-mcp" / "embed"
    return Path("/var/lib/vi-mcp/embed") if os.geteuid() == 0 else Path("~/.local/share/vi-mcp/embed").expanduser()


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


def _starts(exe: Path) -> tuple[bool, str]:
    """Does the binary start at all (missing libvulkan etc.)?"""
    env = {**os.environ, "LD_LIBRARY_PATH": str(exe.parent)} if system() == "linux" else None
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-300:]


def command(exe: Path, model: Path, port: int) -> list[str]:
    return [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), *SERVER_ARGS]


def _service_linux(exe: Path, model: Path, port: int) -> None:
    unit = f"""[Unit]
Description=vi-embed — embedding service of vi-mcp (llama.cpp {LLAMA_TAG}, bge-m3 Q4_K_M) on 127.0.0.1:{port}
After=network.target

[Service]
User=vi-mcp
Group=vi-mcp
SupplementaryGroups=render video
Environment=LD_LIBRARY_PATH={exe.parent}
ExecStart={" ".join(command(exe, model, port))}
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths={exe.parent.parent} {model.parent}

[Install]
WantedBy=multi-user.target
"""
    Path(f"/etc/systemd/system/{SERVICE}.service").write_text(unit)
    for c in (["systemctl", "daemon-reload"], ["systemctl", "enable", SERVICE], ["systemctl", "restart", SERVICE]):
        subprocess.run(c, check=True, capture_output=True, timeout=60)


def _service_windows(exe: Path, model: Path, port: int) -> None:
    args = " ".join(f'"{a}"' if " " in a else a for a in command(exe, model, port)[1:])
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


def setup(port: int = DEFAULT_PORT, cpu: bool = False, model_file: Path | None = None, switch: bool = True) -> dict:
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    report: dict = {"dir": str(d), "llama": LLAMA_TAG}
    model = d / MODEL_FILE
    if model_file:  # an existing local copy (e.g. of the old service) — accepted only with the pinned hash
        if _sha256(model_file) != MODEL_SHA256:
            raise ValueError(f"{model_file}: not the pinned bge-m3 Q4_K_M (SHA256 differs)")
        if not (model.exists() and _sha256(model) == MODEL_SHA256):
            shutil.copyfile(model_file, model)
    else:
        _download(MODEL_URL, model, MODEL_SHA256)
    report["model"] = f"{MODEL_FILE} sha256 {MODEL_SHA256[:12]}…"
    exe = None
    for variant in (["cpu"] if cpu else ["vulkan", "cpu"]):
        name, sha = BUILDS[(system(), variant)]
        archive = _download(_GH + name, d / name, sha)
        candidate = _extract(archive, d / f"llama-{LLAMA_TAG}-{variant}")
        ok, msg = _starts(candidate)
        report[f"start_{variant}"] = "ok" if ok else msg
        if ok:
            exe, report["variant"] = candidate, variant
            break
    if exe is None:
        raise RuntimeError(f"llama-server does not start: {report}")
    if system() == "linux":
        if os.geteuid() == 0:
            shutil.chown(d, "vi-mcp", "vi-mcp")
        _service_linux(exe, model, port)
    else:
        _service_windows(exe, model, port)
    v = probe(port, ["vi-mcp embedding test"])[0]
    if len(v) != MODEL_DIM:
        raise RuntimeError(f"unexpected dimension {len(v)} (expected {MODEL_DIM})")
    report["service"] = f"{SERVICE} on 127.0.0.1:{port}, dimension {len(v)}"
    if switch:
        report["previous_url"] = (config.load().embed or {}).get("url")
        config.set_embed({"url": f"http://127.0.0.1:{port}/v1/embeddings"})
        from . import setup as _setup
        report["restart"] = _setup._restart() or "ok"
    return report


def compare(port: int = DEFAULT_PORT, sample: int = 30) -> dict:
    """Embed the texts of `sample` stored vectors again with the service on `port` and compare (cosine). Read-only on the database.
    Same model and parameters → cosine ≈ 1; anything clearly below means: the stored vectors would not fit, do not switch."""
    import sqlite3
    import numpy as np
    db = config.load().db
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
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


def status() -> dict:
    k = config.load()
    url = (k.embed or {}).get("url")
    out: dict = {"embed.url": url or "— (no vectors)", "dir": str(home())}
    if system() == "linux":
        r = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True, text=True)
        out["service"] = r.stdout.strip() or r.stderr.strip()
    else:
        r = subprocess.run(["schtasks", "/Query", "/TN", SERVICE], capture_output=True, text=True)
        out["service"] = "registered" if r.returncode == 0 else "not registered"
    return out


def remove() -> dict:
    """Stop and remove the service and its files; embed.url is cleared only if it pointed to this service."""
    if system() == "linux":
        subprocess.run(["systemctl", "disable", "--now", SERVICE], capture_output=True, timeout=60)
        Path(f"/etc/systemd/system/{SERVICE}.service").unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=60)
    else:
        subprocess.run(["schtasks", "/End", "/TN", SERVICE], capture_output=True)
        subprocess.run(["schtasks", "/Delete", "/TN", SERVICE, "/F"], capture_output=True)
    shutil.rmtree(home(), ignore_errors=True)
    url = (config.load().embed or {}).get("url") or ""
    if url.startswith("http://127.0.0.1:") and url.endswith("/v1/embeddings"):
        config.set_embed(None)
        return {"removed": True, "embed.url": "cleared"}
    return {"removed": True, "embed.url": url or "—"}


def main(argv: list[str]) -> int:
    import argparse
    a = argparse.ArgumentParser(prog="vi-mcp embed", description="own embedding service of vi-mcp (llama.cpp + bge-m3)")
    u = a.add_subparsers(dest="cmd", required=True)
    s = u.add_parser("setup", help="install or update the service and use it")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--cpu", action="store_true", help="CPU build only (default: Vulkan, CPU if Vulkan does not start)")
    s.add_argument("--model-file", type=Path, help="use this local copy of bge-m3-Q4_K_M.gguf (checked by SHA256) instead of downloading")
    s.add_argument("--no-switch", action="store_true", help="install and start, but keep embed.url as it is (to compare first)")
    c = u.add_parser("compare", help="compare stored vectors with the service (read-only), before switching")
    c.add_argument("--port", type=int, default=DEFAULT_PORT)
    c.add_argument("--sample", type=int, default=30)
    u.add_parser("status")
    u.add_parser("remove")
    o = a.parse_args(argv)
    try:
        if o.cmd == "setup":
            if not 1024 <= o.port <= 65535:
                raise ValueError("port must be a number from 1024 to 65535")
            r = setup(o.port, o.cpu, o.model_file, not o.no_switch)
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

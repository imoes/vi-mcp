"""Sandbox — reflex code runs in its own process, never in the server.

The first barrier remains the AST whitelist (reflexes.check). The sandbox is the second and assumes that the first
has failed. The child process (`python3 -I -S`, empty environment, cwd /) restricts itself before it compiles
foreign code — irreversibly:
  Resources   RLIMIT_CPU, RLIMIT_AS, RLIMIT_NOFILE, RLIMIT_FSIZE 0; wall clock and output limit are enforced by the server (kill)
  Files       Landlock: only /usr, /lib, /lib64, /bin may be read (standard library); nothing is writable,
              nothing truncatable — not even vi.db, although the process runs as the same user as the server
  Network     Landlock blocks TCP bind/connect; seccomp blocks socket() altogether (thus also UDP and Unix sockets)
  Processes   seccomp blocks execve, fork, clone, ptrace
If a building block is missing (kernel without Landlock ABI ≥ 4, architecture other than x86_64), the code does NOT run: result
`isolation: "keine"` with a reason. There is no silent fallback to less protection.

The mechanism needs no privileges and no user namespaces, so it also runs in the hardened systemd service
(RestrictNamespaces=yes, NoNewPrivileges=yes). bubblewrap failed there and on the development machine (AppArmor
forbids unprivileged namespaces, measured 08.11.2026) and was therefore removed again.
Stage 5 (P2P): code from the network runs exclusively here and is distributed only as source text.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time

CPU_S = 10
WALLCLOCK_S = 12
MEMORY_MB = 256
OUTPUT_MAX = 1024 * 1024

# The child process. Order: read input → set limits → only then compile foreign code.
RUNNER = r'''
import ctypes, json, os, platform, resource, struct, sys

CPU_S, SPEICHER_MB = %d, %d
LESBAR = ("/usr", "/lib", "/lib64", "/bin")
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
PR_SET_NO_NEW_PRIVS, PR_SET_SECCOMP, SECCOMP_MODE_FILTER = 38, 22, 2
LL_CREATE, LL_ADD, LL_RESTRICT = 444, 445, 446


def landlock():
    abi = libc.syscall(LL_CREATE, None, 0, 1)
    if abi < 4:
        raise RuntimeError(f"Landlock ABI {abi} (needed: at least 4 for the network block)")
    fs = (1 << 13) - 1 | 1 << 13 | 1 << 14 | (1 << 15 if abi >= 5 else 0)
    # handled_access_fs, handled_access_net, scoped (ABI ≥ 6: abstract Unix sockets and signals)
    attr = struct.pack("=QQ", fs, 3) + (struct.pack("=Q", 3) if abi >= 6 else b"")
    fd = libc.syscall(LL_CREATE, attr, len(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
    lesen = 1 | 1 << 2 | 1 << 3  # EXECUTE, READ_FILE, READ_DIR
    for pfad in LESBAR:
        if not os.path.exists(pfad):
            continue
        pf = os.open(pfad, os.O_PATH | os.O_CLOEXEC)
        regel = struct.pack("=Qi", lesen, pf)
        if libc.syscall(LL_ADD, fd, 1, regel, 0) != 0:
            raise OSError(ctypes.get_errno(), f"landlock_add_rule {pfad}")
        os.close(pf)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "no_new_privs")
    if libc.syscall(LL_RESTRICT, fd, 0) != 0:
        raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    os.close(fd)
    return abi


class Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class Programm(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(Filter))]


def seccomp():
    if platform.machine() != "x86_64":
        raise RuntimeError(f"seccomp filter built only for x86_64, here {platform.machine()}")
    # socket, socketpair, clone, fork, vfork, execve, ptrace, execveat, clone3
    verboten = (41, 53, 56, 57, 58, 59, 101, 322, 435)
    LD, JEQ, JGE, RET = 0x20, 0x15, 0x35, 0x06
    ERLAUBT, TOETEN, EPERM = 0x7fff0000, 0x80000000, 0x00050001
    n = len(verboten)
    prog = [(LD, 0, 0, 4), (JEQ, 1, 0, 0xc000003e), (RET, 0, 0, TOETEN), (LD, 0, 0, 0), (JGE, n + 1, 0, 0x40000000)]
    prog += [(JEQ, n - i, 0, nr) for i, nr in enumerate(verboten)]
    prog += [(RET, 0, 0, ERLAUBT), (RET, 0, 0, EPERM)]
    arr = (Filter * len(prog))(*[Filter(*p) for p in prog])
    p = Programm(len(prog), arr)
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(p), 0, 0) != 0:  # byref: full 64-bit pointer
        raise OSError(ctypes.get_errno(), "seccomp")


def melde(aus):
    os.write(1, json.dumps(aus, ensure_ascii=False, default=str).encode())
    os._exit(0)


roh = json.loads(sys.stdin.read())
try:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_S, CPU_S + 1))
    resource.setrlimit(resource.RLIMIT_AS, (SPEICHER_MB << 20, SPEICHER_MB << 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    abi = landlock()
    seccomp()
except BaseException as exc:
    melde({"fehler": f"sandbox could not be set up, code not executed: {type(exc).__name__}: {exc}"[:400], "isolation": "keine"})
stufe = f"landlock-abi{abi}+seccomp"
try:
    ns = {"__name__": "reflex"}
    kompiliert = compile(roh["code"], "<reflex>", "exec")
    if roh.get("nur_pruefen"):  # compile only, execute nothing
        melde({"ok": True, "isolation": stufe})
    exec(kompiliert, ns)
    if roh.get("nur_schema"):
        aus = {"schema": ns.get("TOOL")}
    else:
        aus = {"wert": ns["run"](*roh["args"])}
    json.dumps(aus)
except BaseException as exc:
    aus = {"fehler": f"{type(exc).__name__}: {exc}"[:500]}
melde({**aus, "isolation": stufe})
''' % (CPU_S, MEMORY_MB)


def run(code: str, args: list, schema_only: bool = False, wallclock_s: float = WALLCLOCK_S, check_only: bool = False) -> dict:
    """Run reflex code. Returns {"wert"|"schema"|"fehler", "isolation", "dauer_ms"}; `isolation: "keine"` means:
    the code did not run because the sandbox could not be set up."""
    t0 = time.monotonic()
    user_input = json.dumps({"code": code, "args": args, "nur_schema": schema_only, "nur_pruefen": check_only}, ensure_ascii=False, default=str).encode()
    # No preexec_fn: the server has threads, it would be unsafe there. The child restricts itself.
    p = subprocess.Popen([sys.executable, "-I", "-S", "-c", RUNNER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, cwd="/", env={"PATH": "/usr/bin:/bin"}, start_new_session=True)
    end = time.monotonic() + wallclock_s
    data, too_many, expired = bytearray(), False, False
    try:
        p.stdin.write(user_input)
        p.stdin.close()
        fd = p.stdout.fileno()
        while True:
            rest = end - time.monotonic()
            if rest <= 0:
                expired = True
                break
            readable, _, _ = select.select([fd], [], [], rest)
            if not readable:
                continue
            piece = os.read(fd, 65536)
            if not piece:
                break
            data += piece
            if len(data) > OUTPUT_MAX:
                too_many = True
                break
    except BrokenPipeError:
        pass
    finally:
        if expired or too_many:
            p.kill()
        p.stdout.close()
        rc = p.wait()
    duration = int((time.monotonic() - t0) * 1000)
    if expired:
        return {"fehler": f"time limit {wallclock_s:g} s — process killed", "isolation": "landlock+seccomp", "dauer_ms": duration}
    if too_many:
        return {"fehler": f"output over {OUTPUT_MAX} bytes — process killed", "isolation": "landlock+seccomp", "dauer_ms": duration}
    try:
        return {**json.loads(data or b"{}" if data else b'{"fehler": "no answer"}'), "dauer_ms": duration, **({"exit": rc} if rc else {})} \
            if rc == 0 else {"fehler": f"process ended with exit {rc}", "isolation": "landlock+seccomp", "dauer_ms": duration}
    except json.JSONDecodeError:
        return {"fehler": f"no JSON answer: {bytes(data[:200])!r}", "isolation": "landlock+seccomp", "dauer_ms": duration}


def description() -> str:
    return (f"own process (python3 -I -S), Landlock + seccomp, CPU {CPU_S} s, memory {MEMORY_MB} MB, wall clock {WALLCLOCK_S} s, "
            "no network, no files except read access to the standard library, no child processes; without Landlock nothing runs")

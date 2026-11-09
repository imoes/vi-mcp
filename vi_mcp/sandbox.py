"""Sandbox — Reflex-Code läuft in einem eigenen Prozess, nie im Server.

Erste Schranke bleibt die AST-Whitelist (reflexe.pruefe). Die Sandbox ist die zweite und setzt voraus, dass die erste
versagt hat. Der Kindprozess (`python3 -I -S`, leere Umgebung, cwd /) begrenzt sich selbst, bevor er fremden Code
übersetzt — unumkehrbar:
  Ressourcen  RLIMIT_CPU, RLIMIT_AS, RLIMIT_NOFILE, RLIMIT_FSIZE 0; Wanduhr und Ausgabelimit erzwingt der Server (Kill)
  Dateien     Landlock: gelesen werden darf nur /usr, /lib, /lib64, /bin (Standardbibliothek); nichts ist schreibbar,
              nichts kürzbar — auch nicht vi.db, obwohl der Prozess unter demselben Nutzer läuft wie der Server
  Netz        Landlock sperrt TCP bind/connect; seccomp sperrt socket() überhaupt (damit auch UDP und Unix-Sockets)
  Prozesse    seccomp sperrt execve, fork, clone, ptrace
Fehlt ein Baustein (Kernel ohne Landlock ABI ≥ 4, andere Architektur als x86_64), läuft der Code NICHT: Ergebnis
`isolation: "keine"` mit Grund. Es gibt keinen stillen Rückfall auf weniger Schutz.

Der Mechanismus braucht keine Rechte und keine User-Namespaces, läuft also auch im gehärteten systemd-Dienst
(RestrictNamespaces=yes, NoNewPrivileges=yes). bubblewrap scheiterte dort und auf dem Entwicklungsrechner (AppArmor
verbietet unprivilegierte Namespaces, gemessen 08.11.2026) und wurde deshalb wieder entfernt.
Stufe 5 (P2P): Code aus dem Netz läuft ausschließlich hier und wird nur als Quelltext verteilt.
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

# Der Kindprozess. Reihenfolge: Eingabe lesen → Grenzen setzen → erst dann fremden Code übersetzen.
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
        raise RuntimeError(f"Landlock ABI {abi} (gebraucht: mindestens 4 für die Netzsperre)")
    fs = (1 << 13) - 1 | 1 << 13 | 1 << 14 | (1 << 15 if abi >= 5 else 0)
    # handled_access_fs, handled_access_net, scoped (ABI ≥ 6: abstrakte Unix-Sockets und Signale)
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
        raise RuntimeError(f"seccomp-Filter nur für x86_64 gebaut, hier {platform.machine()}")
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
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(p), 0, 0) != 0:  # byref: voller 64-Bit-Zeiger
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
    melde({"fehler": f"Sandbox nicht herstellbar, Code nicht ausgeführt: {type(exc).__name__}: {exc}"[:400], "isolation": "keine"})
stufe = f"landlock-abi{abi}+seccomp"
try:
    ns = {"__name__": "reflex"}
    kompiliert = compile(roh["code"], "<reflex>", "exec")
    if roh.get("nur_pruefen"):  # nur übersetzen, nichts ausführen
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
    """Reflex-Code ausführen. Liefert {"wert"|"schema"|"fehler", "isolation", "dauer_ms"}; `isolation: "keine"` heißt:
    der Code lief nicht, weil die Sandbox nicht herstellbar war."""
    t0 = time.monotonic()
    user_input = json.dumps({"code": code, "args": args, "nur_schema": schema_only, "nur_pruefen": check_only}, ensure_ascii=False, default=str).encode()
    # Kein preexec_fn: der Server hat Threads, dort wäre das unsicher. Das Kind begrenzt sich selbst.
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
        return {"fehler": f"Zeitlimit {wallclock_s:g} s — Prozess beendet", "isolation": "landlock+seccomp", "dauer_ms": duration}
    if too_many:
        return {"fehler": f"Ausgabe über {OUTPUT_MAX} Bytes — Prozess beendet", "isolation": "landlock+seccomp", "dauer_ms": duration}
    try:
        return {**json.loads(data or b"{}" if data else b'{"fehler": "keine Antwort"}'), "dauer_ms": duration, **({"exit": rc} if rc else {})} \
            if rc == 0 else {"fehler": f"Prozess beendet mit Exit {rc}", "isolation": "landlock+seccomp", "dauer_ms": duration}
    except json.JSONDecodeError:
        return {"fehler": f"keine JSON-Antwort: {bytes(data[:200])!r}", "isolation": "landlock+seccomp", "dauer_ms": duration}


def description() -> str:
    return (f"eigener Prozess (python3 -I -S), Landlock + seccomp, CPU {CPU_S} s, Speicher {MEMORY_MB} MB, Wanduhr {WALLCLOCK_S} s, "
            "kein Netz, keine Dateien außer Lesezugriff auf die Standardbibliothek, keine Kindprozesse; ohne Landlock läuft nichts")

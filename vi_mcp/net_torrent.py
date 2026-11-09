"""Torrent als zweiter Weg für große Rückstände. Direkte Verbindung zu bekannten Peers, privat markiert: kein DHT, kein LSD, kein PEX, kein UPnP.

Ein Segment ist ein Abschnitt eines Logbuchs als JSON-Zeilen. Der Empfänger prüft es wie jeden anderen Eintrag: Prüfsumme hier, Signatur und Kette im Logbuch.
Wird ein Eintrag eines Segments vergessen, fällt das ganze Segment weg (Logbuch.segmente_verwerfen), der Rückstand läuft dann über HTTPS.
libtorrent ist optional: Fehlt es, bleibt es benannt bei HTTPS.
"""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import time
from pathlib import Path


def available() -> bool:
    try:
        import libtorrent  # noqa: F401
        return True
    except ImportError:
        return False


class Swarm:
    def __init__(self, directory: Path, port: int, bind: str):
        import libtorrent as lt
        self.lt = lt
        self.dir_path = Path(directory)
        self.dir_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.s = lt.session({"listen_interfaces": f"{bind}:{port}", "enable_dht": False, "enable_lsd": False, "enable_upnp": False, "enable_natpmp": False,
                             "allow_multiple_connections_per_ip": True, "alert_mask": 0, "user_agent": "vi-p2p"})
        self.handles: dict[str, object] = {}

    def port(self) -> int:
        return self.s.listen_port()

    def _info(self, raw: bytes):
        return self.lt.torrent_info(self.lt.bdecode(raw))

    def parts(self, torrent_b64: str, file: Path) -> None:
        if not file.exists():
            return
        info = self._info(base64.b64decode(torrent_b64))
        self.handles[str(info.info_hash())] = self.s.add_torrent({"ti": info, "save_path": str(file.parent)})

    def build(self, log, pub: str, from_: int, until: int) -> None:
        lines = log.read(pub, from_ - 1, until - from_ + 1)
        if len(lines) != until - from_ + 1:
            return
        data = "\n".join(json.dumps(z, ensure_ascii=False, sort_keys=True) for z in lines).encode()
        sha = hashlib.sha256(data).hexdigest()
        file = self.dir_path / f"{sha}.jsonl"
        file.write_bytes(data)
        fs = self.lt.file_storage()
        self.lt.add_files(fs, str(file))
        ct = self.lt.create_torrent(fs)
        ct.set_priv(True)
        self.lt.set_piece_hashes(ct, str(self.dir_path))
        raw = self.lt.bencode(ct.generate())
        log.remember_segment(sha, pub, from_, until, raw, self.port(), str(file))
        self.parts(base64.b64encode(raw).decode(), file)

    def fetch(self, s: dict, host: str, wait_s: float, log, pub: str) -> list[dict] | None:
        """Ein Segment laden, prüfen, zum Weiterverteilen behalten. None, wenn es nicht klappt: Der Aufrufer fällt auf HTTPS zurück."""
        try:
            raw = base64.b64decode(s["torrent"])
            info = self._info(raw)
            ip = socket.gethostbyname(host)
        except (ValueError, RuntimeError, OSError, KeyError):
            return None
        h = self.s.add_torrent({"ti": info, "save_path": str(self.dir_path)})
        h.connect_peer((ip, int(s["port"])))
        end = time.time() + wait_s
        while time.time() < end and not h.status().is_seeding:
            time.sleep(0.1)
        file = self.dir_path / info.files().file_name(0)
        if not h.status().is_seeding or not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != s["sha256"]:
            self.s.remove_torrent(h)
            return None
        self.handles[str(info.info_hash())] = h
        log.remember_segment(s["sha256"], pub, s["von"], s["bis"], raw, self.port(), str(file))
        return [json.loads(z) for z in file.read_text().splitlines()]

    def stop_service(self) -> None:
        for h in self.handles.values():
            self.s.remove_torrent(h)
        self.handles.clear()

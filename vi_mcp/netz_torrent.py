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


def verfuegbar() -> bool:
    try:
        import libtorrent  # noqa: F401
        return True
    except ImportError:
        return False


class Schwarm:
    def __init__(self, verzeichnis: Path, port: int, bind: str):
        import libtorrent as lt
        self.lt = lt
        self.verz = Path(verzeichnis)
        self.verz.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.s = lt.session({"listen_interfaces": f"{bind}:{port}", "enable_dht": False, "enable_lsd": False, "enable_upnp": False, "enable_natpmp": False,
                             "allow_multiple_connections_per_ip": True, "alert_mask": 0, "user_agent": "vi-p2p"})
        self.griffe: dict[str, object] = {}

    def port(self) -> int:
        return self.s.listen_port()

    def _info(self, roh: bytes):
        return self.lt.torrent_info(self.lt.bdecode(roh))

    def teile(self, torrent_b64: str, datei: Path) -> None:
        if not datei.exists():
            return
        info = self._info(base64.b64decode(torrent_b64))
        self.griffe[str(info.info_hash())] = self.s.add_torrent({"ti": info, "save_path": str(datei.parent)})

    def baue(self, log, pub: str, von: int, bis: int) -> None:
        zeilen = log.lies(pub, von - 1, bis - von + 1)
        if len(zeilen) != bis - von + 1:
            return
        daten = "\n".join(json.dumps(z, ensure_ascii=False, sort_keys=True) for z in zeilen).encode()
        sha = hashlib.sha256(daten).hexdigest()
        datei = self.verz / f"{sha}.jsonl"
        datei.write_bytes(daten)
        fs = self.lt.file_storage()
        self.lt.add_files(fs, str(datei))
        ct = self.lt.create_torrent(fs)
        ct.set_priv(True)
        self.lt.set_piece_hashes(ct, str(self.verz))
        roh = self.lt.bencode(ct.generate())
        log.segment_merken(sha, pub, von, bis, roh, self.port(), str(datei))
        self.teile(base64.b64encode(roh).decode(), datei)

    def hole(self, s: dict, host: str, warte_s: float, log, pub: str) -> list[dict] | None:
        """Ein Segment laden, prüfen, zum Weiterverteilen behalten. None, wenn es nicht klappt: Der Aufrufer fällt auf HTTPS zurück."""
        try:
            roh = base64.b64decode(s["torrent"])
            info = self._info(roh)
            ip = socket.gethostbyname(host)
        except (ValueError, RuntimeError, OSError, KeyError):
            return None
        h = self.s.add_torrent({"ti": info, "save_path": str(self.verz)})
        h.connect_peer((ip, int(s["port"])))
        ende = time.time() + warte_s
        while time.time() < ende and not h.status().is_seeding:
            time.sleep(0.1)
        datei = self.verz / info.files().file_name(0)
        if not h.status().is_seeding or not datei.exists() or hashlib.sha256(datei.read_bytes()).hexdigest() != s["sha256"]:
            self.s.remove_torrent(h)
            return None
        self.griffe[str(info.info_hash())] = h
        log.segment_merken(s["sha256"], pub, s["von"], s["bis"], roh, self.port(), str(datei))
        return [json.loads(z) for z in datei.read_text().splitlines()]

    def stoppe(self) -> None:
        for h in self.griffe.values():
            self.s.remove_torrent(h)
        self.griffe.clear()

"""0.35.0: images in memory — with description and regions in the output format of SAM 3; type from the bytes; never onto the network."""
import base64
import json
import struct
import threading
import zlib

import pytest

from vi_mcp import config, images, p2p, server, tools
from vi_mcp import memory as g

from test_http import request


def png(w=64, h=48, colour=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes([colour, 0, 0]) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def jpeg(w, h):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp_vp8x(w, h):
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def b64(raw):
    return base64.b64encode(raw).decode()


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("anna")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db"), "offen": True})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], tok
    s.shutdown()
    s.server_close()
    server.finish([s])


def _session(port, token=None):
    _, h, _ = request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "t"}}}, token)
    return h.get("Mcp-Session-Id")


def _call(port, sid, name, args, token=None):
    _, _, a = request(port, "POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}, token, sid)
    return a["result"]


REGIONS = [{"concept": "red plug", "box": [4, 6, 30, 40], "score": 0.93, "mask": {"size": [48, 64], "counts": "PQ5d0"}},
           {"concept": "red plug", "box": [34, 6, 60, 40], "score": 0.88},
           {"concept": "network cable", "box": [0, 0, 64, 10], "score": 0.71}]


def test_sniff_takes_type_and_size_from_the_bytes():
    assert images.sniff(png(64, 48)) == ("image/png", 64, 48)
    assert images.sniff(jpeg(640, 480)) == ("image/jpeg", 640, 480)
    assert images.sniff(b"GIF89a" + struct.pack("<HH", 12, 7) + b"\x00" * 8) == ("image/gif", 12, 7)
    assert images.sniff(webp_vp8x(1920, 1080)) == ("image/webp", 1920, 1080)
    with pytest.raises(ValueError, match="not a supported image"):
        images.sniff(b"%PDF-1.7 this claims to be a png")


def test_image_with_description_and_sam3_regions_round_trip(srv):
    port, tok = srv
    sid = _session(port, tok)
    raw = png()
    r = _call(port, sid, "vi_learn", {"text": "Patch panel B3: both uplinks are plugged into the red ports",
                                      "content": "Full description: rack B3, top patch panel, ports 1 and 2 red, uplink cable on top.",
                                      "hashtags": ["thema:patchpanel"], "source": "photo 10.11.2026, rack B3", "image": b64(raw), "regions": REGIONS}, tok)
    assert not r["isError"], r
    text = r["content"][0]["text"]
    oid = text.split()[1]
    assert "image png 64×48" in text and "3 regions (red plug ×2, network cable)" in text
    o = g.load(oid)
    assert {"medium:bild", "zeigt:red-plug", "zeigt:network-cable"} <= set(o.hashtags)
    assert o.data["bild"]["sha"] and o.data["regionen"][0] == {"begriff": "red plug", "box": [4.0, 6.0, 30.0, 40.0], "score": 0.93,
                                                               "maske": {"size": [48, 64], "counts": "PQ5d0"}}
    # found by concept hashtag and by full text of the concept; the hit line names the image
    hit = _call(port, sid, "vi_recall", {"filter": "zeigt:red-plug"}, tok)["content"][0]["text"]
    assert oid in hit and "vi_object shows it" in hit
    assert oid in _call(port, sid, "vi_recall", {"filter": "network cable"}, tok)["content"][0]["text"]
    # vi_object returns the image as MCP content, byte for byte, with its regions
    r = _call(port, sid, "vi_object", {"id": oid}, tok)
    assert [c["type"] for c in r["content"]] == ["text", "image"]
    assert r["content"][1]["mimeType"] == "image/png" and base64.b64decode(r["content"][1]["data"]) == raw
    assert "region 1: red plug · box [4.0, 6.0, 30.0, 40.0] (px, xyxy) · score 0.93 · mask (COCO RLE)" in r["content"][0]["text"]
    r = _call(port, sid, "vi_object", {"id": oid, "image": False}, tok)
    assert [c["type"] for c in r["content"]] == ["text"] and "image not attached" in r["content"][0]["text"]
    assert "Images: 1 image," in _call(port, sid, "vi_status", {}, tok)["content"][0]["text"]


@pytest.mark.parametrize("change,reason", [
    ({"regions": [{"concept": "plug", "box": [0, 0, 65, 10], "score": 0.5}]}, "outside the image 64×48"),
    ({"regions": [{"concept": "plug", "box": [10, 0, 5, 10], "score": 0.5}]}, "is empty"),
    ({"regions": [{"concept": "plug", "box": [0, 0, 5, 10], "score": 1.5}]}, "score must be a number 0–1"),
    ({"regions": [{"concept": "plug", "box": [0, 0, 5, 10], "score": 0.5, "mask": {"size": [64, 48], "counts": "x"}}]}, "size = \\[height, width\\]"),
    ({"regions": [{"concept": "", "box": [0, 0, 5, 10], "score": 0.5}]}, "concept"),
    ({"image": b64(b"just text, no image")}, "not a supported image"),
    ({"image": "%%% not base64"}, "not valid base64"),
    ({"key": "recurring-x"}, "image and key do not go together"),
])
def test_bad_image_input_is_refused_with_its_reason(srv, change, reason):
    port, tok = srv
    sid = _session(port, tok)
    args = {"text": "a photo of the rack in room B3", "hashtags": ["thema:rack"], "source": "photo 10.11.2026", "image": b64(png()), **change}
    r = _call(port, sid, "vi_learn", args, tok)
    assert r["isError"]
    import re
    assert re.search(reason, r["content"][0]["text"]), r["content"][0]["text"]
    assert images.stats() == (0, 0)  # a refused image leaves nothing behind


def test_regions_need_an_image(srv):
    port, tok = srv
    sid = _session(port, tok)
    r = _call(port, sid, "vi_learn", {"text": "regions without a picture", "hashtags": ["thema:x"], "source": "test 10.11.2026", "regions": REGIONS}, tok)
    assert r["isError"] and "give image as well" in r["content"][0]["text"]


def test_without_token_no_images(srv):
    port, _ = srv
    sid = _session(port)
    r = _call(port, sid, "vi_learn", {"text": "a photo proposed without a token", "hashtags": ["thema:x"], "source": "test 10.11.2026", "image": b64(png())})
    assert r["isError"] and "own instance with a token" in r["content"][0]["text"]
    assert images.stats() == (0, 0)


def test_same_image_stored_once_and_limits(gd, monkeypatch):
    a = images.store(png())
    b = images.store(png())
    assert a == b and images.stats() == (1, len(png()))
    monkeypatch.setattr(images, "IMAGE_MAX", 100)
    with pytest.raises(ValueError, match="at most 100"):
        images.store(png(colour=9))
    monkeypatch.setattr(images, "IMAGE_MAX", 5 * 1024 * 1024)
    monkeypatch.setattr(images, "TOTAL_MAX", len(png()) + 10)
    with pytest.raises(ValueError, match="image store full"):
        images.store(png(colour=7))
    assert images.stats()[0] == 1


def test_image_never_onto_the_network(gd):
    ref = images.store(png())
    o = g.new_object("erkenntnis", "Patch panel B3 photographed, red ports used", ["thema:patchpanel", "medium:bild"],
                     {"quelle": "photo 10.11.2026", "bild": ref}, instance="anna")
    assert p2p._export_form(o, "t" * 32, frozenset()) == (None, "has an image (images stay on this server)")


def test_internal_image_invisible_without_token(srv):
    port, tok = srv
    sid = _session(port, tok)
    r = _call(port, sid, "vi_learn", {"text": "internal wiring diagram of rack B3", "hashtags": ["thema:rack"], "source": "photo 10.11.2026",
                                      "image": b64(png()), "visibility": "internal"}, tok)
    oid = r["content"][0]["text"].split()[1]
    guest = _session(port)
    r = _call(port, guest, "vi_object", {"id": oid})
    assert r["isError"] and [c["type"] for c in r["content"]] == ["text"]


def test_command_line_puts_a_file_in_and_gets_it_back(srv, tmp_path, monkeypatch, capsys):
    from vi_mcp import image_cli
    port, tok = srv
    (tmp_path / "tok").write_text(tok)
    monkeypatch.setenv("VI_MCP_URL", f"http://127.0.0.1:{port}/mcp")
    monkeypatch.setenv("VI_MCP_TOKEN_FILE", str(tmp_path / "tok"))
    monkeypatch.setenv("no_proxy", "*")
    (tmp_path / "rack.png").write_bytes(png())
    (tmp_path / "regions.json").write_text(json.dumps(REGIONS))
    (tmp_path / "desc.md").write_text("Full description of rack B3.")
    assert image_cli.main([str(tmp_path / "rack.png"), "--text", "rack B3 front, two red plugs", "--hashtags", "thema:rack,host:b3",
                           "--source", "photo 10.11.2026", "--content-file", str(tmp_path / "desc.md"), "--regions", str(tmp_path / "regions.json")]) == 0
    oid = capsys.readouterr().out.split()[1]
    assert g.load(oid).data["inhalt"] == "Full description of rack B3."
    assert image_cli.main(["get", oid, str(tmp_path / "back.png")]) == 0
    assert (tmp_path / "back.png").read_bytes() == png()


def test_with_images_is_a_plain_string_for_text_callers():
    w = tools.WithImages("text", [("image/png", "AAAA")])
    assert w == "text" and isinstance(w, str) and w.images == [("image/png", "AAAA")]

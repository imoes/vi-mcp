"""Aufruf:
  python3 -m vi_mcp                       Server starten (Konfiguration: $VI_MCP_CONFIG oder ~/.config/vi-mcp/config.json)
  python3 -m vi_mcp instanz NAME [--reflexe]
                                          Instanz anlegen bzw. Token erneuern; gibt das Token EINMAL aus
"""
import sys

from . import konfig, server


def _cli(argv: list[str]) -> int:
    if not argv:
        server.main()
        return 0
    if argv[0] == "instanz" and len(argv) >= 2:
        token = konfig.instanz_anlegen(argv[1], reflexe="--reflexe" in argv[2:])
        print(f"Instanz {argv[1]} in {konfig.pfad()} angelegt (Reflex-Recht: {'ja' if '--reflexe' in argv[2:] else 'nein'}).")
        print(f"Token (wird nicht gespeichert, nur sein SHA-256):\n{token}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


sys.exit(_cli(sys.argv[1:]))

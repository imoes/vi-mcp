#!/bin/sh
# vi-mcp — Server starten oder Instanz anlegen (siehe: vi-mcp --hilfe). Konfiguration: /etc/vi-mcp/config.json
export VI_MCP_CONFIG="${VI_MCP_CONFIG:-/etc/vi-mcp/config.json}"
exec /usr/bin/python3 -I -m vi_mcp "$@"

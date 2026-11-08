#!/bin/sh
# vi-mcp — Server starten, Instanz anlegen, Programme einrichten. Konfiguration: /etc/vi-mcp/config.json
export VI_MCP_CONFIG="${VI_MCP_CONFIG:-/etc/vi-mcp/config.json}"
exec /usr/libexec/vi-mcp-start "$@"

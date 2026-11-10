#!/bin/sh
# vi-mcp — start the server or create an instance (see: vi-mcp --help). Configuration: /etc/vi-mcp/config.json
export VI_MCP_CONFIG="${VI_MCP_CONFIG:-/etc/vi-mcp/config.json}"
exec /usr/bin/python3 -I -m vi_mcp "$@"

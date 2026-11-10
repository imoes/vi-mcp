#!/bin/sh
# vi-mcp — start the server, create an instance, set up clients. Configuration: /etc/vi-mcp/config.json
export VI_MCP_CONFIG="${VI_MCP_CONFIG:-/etc/vi-mcp/config.json}"
exec /usr/libexec/vi-mcp-start "$@"

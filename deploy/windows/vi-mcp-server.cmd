@echo off
rem vi-mcp server, started by the scheduled task "vi-mcp" (SYSTEM). Output goes to %ProgramData%\vi-mcp\server.log.
set "VI_MCP_CONFIG=%ProgramData%\vi-mcp\config.json"
"%~dp0venv\Scripts\python.exe" -I -m vi_mcp >> "%ProgramData%\vi-mcp\server.log" 2>&1

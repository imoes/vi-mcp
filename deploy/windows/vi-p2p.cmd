@echo off
rem vi-mcp network service of one network (argument: its name; "standard" uses p2p\config.json), started by the scheduled task
rem vi-p2p-<name> (SYSTEM; `vi-mcp net wiki on` creates it). Output goes to %ProgramData%\vi-mcp\p2p-<name>.log.
set "VI_MCP_CONFIG=%ProgramData%\vi-mcp\config.json"
set "N=%~1"
if "%N%"=="" set "N=standard"
if /I "%N%"=="standard" (set "VI_P2P_CONFIG=%ProgramData%\vi-mcp\p2p\config.json") else (set "VI_P2P_CONFIG=%ProgramData%\vi-mcp\p2p\%N%.json")
"%~dp0venv\Scripts\python.exe" -I -X utf8 -m vi_mcp net run >> "%ProgramData%\vi-mcp\p2p-%N%.log" 2>&1

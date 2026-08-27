@echo off
REM Double-click me, or run .\quickstart.cmd from PowerShell.
REM -ExecutionPolicy Bypass applies to this one script only; nothing is changed
REM permanently on the machine.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0quickstart.ps1" %*

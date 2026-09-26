@echo off
rem Moose Life Resolution List Fix - double-click to patch your Steam install.
rem Runs the PowerShell patcher next to this file. Pass MooselifeGL.exe paths or -Check / -Restore / -Filter as arguments.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ML-ResolutionFix.ps1" %*
echo.
if errorlevel 1 (echo Something went wrong - see the messages above.) else (echo Done.)
pause

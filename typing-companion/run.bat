@echo off
rem Launches the Typing Companion with no console window.
rem Extra arguments are passed through, e.g.  run.bat --demo
setlocal
cd /d "%~dp0"

set "PYW="

rem 1) The Python launcher that python.org installs (picks the newest Python 3).
where pyw >nul 2>nul
if not errorlevel 1 set "PYW=pyw -3"
if defined PYW goto launch

rem 2) pythonw.exe on PATH.
where pythonw >nul 2>nul
if not errorlevel 1 set "PYW=pythonw"
if defined PYW goto launch

rem 3) A per-user python.org install that isn't on PATH.
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~D\pythonw.exe" if not defined PYW set PYW="%%~D\pythonw.exe"
if defined PYW goto launch

echo Could not find Python.
echo Install Python 3.8 or newer from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer) and run this file again.
pause
exit /b 1

:launch
start "" %PYW% "%~dp0companion.py" %*
exit /b 0

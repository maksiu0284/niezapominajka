@echo off
REM Niezapominajka - uruchomienie ze zrodel na Windows
cd /d "%~dp0"
if not exist .venv (
  echo Pierwsze uruchomienie: tworze srodowisko Python...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python run.py %*
pause

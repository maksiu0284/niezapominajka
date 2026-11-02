@echo off
REM Niezapominajka - budowa wersji Windows (instalator + wersja przenosna)
REM Wymaga: Python 3.12 (python.org) oraz Inno Setup 6 (https://jrsoftware.org/isinfo.php)
cd /d "%~dp0\..\.."
py -3.12 -m venv build\venv-win || python -m venv build\venv-win
build\venv-win\Scripts\python -m pip install --upgrade pip
build\venv-win\Scripts\python -m pip install pyinstaller -r requirements-desktop.txt || exit /b 1
build\venv-win\Scripts\pyinstaller --noconfirm --clean --workpath build\win --distpath dist-win packaging\windows\niezapominajka.spec || exit /b 1
set NZ_ONEFILE=1
build\venv-win\Scripts\pyinstaller --noconfirm --workpath build\win1 --distpath dist-win packaging\windows\niezapominajka.spec || exit /b 1
set NZ_ONEFILE=
move /Y dist-win\Niezapominajka-przenosna.exe dist-win\Niezapominajka-1.0.1-przenosna.exe
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
%ISCC% packaging\windows\installer.iss || exit /b 1
echo Gotowe: folder dist-win

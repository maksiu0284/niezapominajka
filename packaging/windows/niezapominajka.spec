# -*- mode: python ; coding: utf-8 -*-
# PyInstaller – Niezapominajka dla Windows.
# Wersja do instalatora (folder):   pyinstaller packaging\windows\niezapominajka.spec
# Wersja przenośna (jeden plik):    set NZ_ONEFILE=1 && pyinstaller packaging\windows\niezapominajka.spec
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ONEFILE = os.environ.get("NZ_ONEFILE") == "1"
ICON = os.path.join(SPECPATH, "niezapominajka.ico")

hidden = (collect_submodules("uvicorn") + collect_submodules("app")
          + ["pystray._win32", "PIL.Image", "multipart", "python_multipart", "segno", "openpyxl"])

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "app", "templates"), os.path.join("app", "templates")),
        (os.path.join(ROOT, "app", "static"), os.path.join("app", "static")),
        (os.path.join(ROOT, "LICENSE"), "."),
    ],
    hiddenimports=hidden,
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="Niezapominajka-przenosna", icon=ICON, console=False,
              upx=False, runtime_tmpdir=None, version=os.path.join(SPECPATH, "version.txt"))
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="Niezapominajka", icon=ICON, console=False, upx=False,
              version=os.path.join(SPECPATH, "version.txt"))
    coll = COLLECT(exe, a.binaries, a.datas, name="Niezapominajka", upx=False)

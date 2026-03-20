# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('bhaptics_python')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


def _collect_conda_runtime_dlls():
    runtime_dlls = []
    env_root = Path(sys.executable).resolve().parent
    lib_bin = env_root / "Library" / "bin"
    for dll_name in (
        "sqlite3.dll",
        "libexpat.dll",
        "libcrypto-3-x64.dll",
        "libssl-3-x64.dll",
        "liblzma.dll",
        "libbz2.dll",
    ):
        dll_path = lib_bin / dll_name
        if dll_path.is_file():
            runtime_dlls.append((str(dll_path), "."))
    return runtime_dlls


def _collect_tkinter_runtime():
    tk_datas = []
    tk_binaries = []
    tk_hiddenimports = []
    env_root = Path(sys.executable).resolve().parent
    lib_bin = env_root / "Library" / "bin"
    dlls_dir = env_root / "DLLs"
    lib_root = env_root / "Library" / "lib"
    py_lib = env_root / "Lib"

    for name in ("_tkinter.pyd",):
        path = dlls_dir / name
        if path.is_file():
            tk_binaries.append((str(path), "."))

    for name in ("tcl86t.dll", "tk86t.dll"):
        path = lib_bin / name
        if path.is_file():
            tk_binaries.append((str(path), "."))

    for dirname in ("tcl8", "tcl8.6", "tk8.6"):
        path = lib_root / dirname
        if path.is_dir():
            tk_datas.append((str(path), dirname))

    tkinter_pkg = py_lib / "tkinter"
    if tkinter_pkg.is_dir():
        tk_datas.append((str(tkinter_pkg), "tkinter"))

    return tk_datas, tk_binaries, tk_hiddenimports


_tk_datas, _tk_binaries, _tk_hiddenimports = _collect_tkinter_runtime()

binaries += _collect_conda_runtime_dlls()
datas += _tk_datas
binaries += _tk_binaries
hiddenimports += _tk_hiddenimports


a = Analysis(
    ['src\\subscribe.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['src\\rthook_tk.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='subscribe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

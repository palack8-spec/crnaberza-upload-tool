# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['crnaberza_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['clr', 'pythonnet', 'webview', 'bottle', 'proxy_tools', 'PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    name='CrnaBerzaUploadTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',
    version='version_info.txt',
)

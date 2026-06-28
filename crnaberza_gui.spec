# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Bundle pip into the EXE so the app can install python-based tools (ffsubsync / autosubsync)
# into TOOLS_DIR/py/<name> at runtime.
_pip_datas, _pip_binaries, _pip_hidden = collect_all('pip')
_st_datas, _st_binaries, _st_hidden = collect_all('setuptools')
_pr_datas, _pr_binaries, _pr_hidden = collect_all('pkg_resources')
try:
    _wh_datas, _wh_binaries, _wh_hidden = collect_all('wheel')
except Exception:
    _wh_datas, _wh_binaries, _wh_hidden = [], [], []

# Bundle SSH/SFTP stack so paramiko works fully (no external scp prompt)
_para_datas, _para_binaries, _para_hidden = [], [], []
for _pkg in ('paramiko', 'cryptography', 'cffi', 'bcrypt', 'nacl'):
    try:
        _d, _b, _h = collect_all(_pkg)
        _para_datas += _d; _para_binaries += _b; _para_hidden += _h
    except Exception:
        pass

a = Analysis(
    ['crnaberza_gui.py'],
    pathex=[],
    binaries=_pip_binaries + _st_binaries + _pr_binaries + _wh_binaries + _para_binaries,
    datas=_pip_datas + _st_datas + _pr_datas + _wh_datas + _para_datas + [
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'clr', 'pythonnet', 'webview', 'bottle', 'proxy_tools',
        'crnaberza_core', 'crnaberza_core.config', 'crnaberza_core.constants',
        'crnaberza_core.text', 'crnaberza_core.media', 'crnaberza_core.torrent',
        'crnaberza_core.tmdb', 'crnaberza_core.network',
        'PIL._tkinter_finder',
        'paramiko', 'paramiko.transport', 'paramiko.client', 'paramiko.sftp_client',
        'cryptography', 'cryptography.hazmat.backends.openssl', 'cryptography.hazmat.bindings._rust',
        'cffi', 'bcrypt', 'nacl', 'nacl.bindings',
        'pkg_resources', 'pkg_resources.extern',
    ] + _pip_hidden + _st_hidden + _pr_hidden + _wh_hidden + _para_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['ffsubsync', 'autosubsync', 'webrtcvad', 'audalign'],
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

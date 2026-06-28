#!/usr/bin/env python3
"""Crna Berza Tools v2.0 by Vucko — pywebview + Bootstrap 5 GUI"""

import os, sys, re, json, base64, shutil, subprocess, threading, time, zipfile, tempfile, ctypes
import urllib.parse, urllib.request
from pathlib import Path
from io import BytesIO
from datetime import datetime

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import webview

from crnaberza_core import (
    APP_VERSION,
    CATEGORIES,
    DEFAULT_CONFIG,
    GITHUB_REPO,
    VIDEO_EXTENSIONS,
    clean_folder_name,
    cyr_to_lat,
    detect_subtitles_from_mediainfo,
    download_with_progress,
    file_to_base64,
    find_video_file,
    format_duration,
    google_translate,
    normalize_torrent,
    scan_srt_subtitles,
    validate_torrent_file,
)
from crnaberza_core.config import CONFIG_FILE, DATA_DIR, HISTORY_FILE, TOOLS_DIR, load_config, save_config
from crnaberza_core.tmdb import tmdb_get_local as _tmdb_get_local, tmdb_request as _tmdb_request

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
NO_WINDOW = subprocess.CREATE_NO_WINDOW

TOOL_INFO = {
    "ffmpeg": {"version": "7.1", "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"},
    "mediainfo": {"version": "24.12", "url": "https://mediaarea.net/download/binary/mediainfo/24.12/MediaInfo_CLI_24.12_Windows_x64.zip"},
    "torrenttools": {"version": "0.6.2", "url": "https://github.com/fbdtemme/torrenttools/releases/download/v0.6.2/torrenttools-0.6.2-windows-x86_64.msi"},
}
TOOLS_VERSION_FILE = os.path.join(TOOLS_DIR, "versions.json")

CONFIG = load_config()


def tmdb_request(endpoint):
    return _tmdb_request(endpoint, CONFIG["tmdb_api_key"])


def tmdb_get_local(search_type, tmdb_id, en_overview=""):
    return _tmdb_get_local(search_type, tmdb_id, CONFIG["tmdb_api_key"], en_overview)


def _assets_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _ui_bundle_dir():
    """Writable UI folder where index.html and vendor/ live (WebView2 needs real file URLs)."""
    src = _assets_dir()
    if not getattr(sys, "frozen", False):
        return src
    bundle = os.path.join(DATA_DIR, "ui_bundle", APP_VERSION)
    marker = os.path.join(bundle, ".bundle_ok")
    vendor_dest = os.path.join(bundle, "vendor")
    src_vendor = os.path.join(src, "vendor")
    if not os.path.isfile(marker) and os.path.isdir(src_vendor):
        if os.path.isdir(bundle):
            shutil.rmtree(bundle, ignore_errors=True)
        os.makedirs(bundle, exist_ok=True)
        shutil.copytree(src_vendor, vendor_dest)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(APP_VERSION)
    return bundle


def load_tool_versions():
    if os.path.exists(TOOLS_VERSION_FILE):
        try:
            with open(TOOLS_VERSION_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_tool_version(name, version):
    versions = load_tool_versions()
    versions[name] = version
    os.makedirs(TOOLS_DIR, exist_ok=True)
    with open(TOOLS_VERSION_FILE, "w") as f:
        json.dump(versions, f)


def save_all_tool_versions(versions):
    os.makedirs(TOOLS_DIR, exist_ok=True)
    with open(TOOLS_VERSION_FILE, "w") as f:
        json.dump(versions, f)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


def find_exe_in_dir(base_dir, exe_name):
    if not os.path.isdir(base_dir):
        return None
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower() == exe_name.lower():
                return os.path.join(root, f)
    return None


def get_ffmpeg_path():
    return find_exe_in_dir(os.path.join(TOOLS_DIR, "ffmpeg"), "ffmpeg.exe") or shutil.which("ffmpeg")

def get_ffprobe_path():
    return find_exe_in_dir(os.path.join(TOOLS_DIR, "ffmpeg"), "ffprobe.exe") or shutil.which("ffprobe")

def get_mediainfo_path():
    return find_exe_in_dir(os.path.join(TOOLS_DIR, "mediainfo"), "MediaInfo.exe") or shutil.which("MediaInfo")

def get_torrenttools_path():
    return find_exe_in_dir(os.path.join(TOOLS_DIR, "torrenttools"), "torrenttools.exe") or shutil.which("torrenttools")

def get_mkvmerge_path():
    return find_exe_in_dir(os.path.join(TOOLS_DIR, "mkvtoolnix"), "mkvmerge.exe") or shutil.which("mkvmerge")

def get_mkvextract_path():
    return find_exe_in_dir(os.path.join(TOOLS_DIR, "mkvtoolnix"), "mkvextract.exe") or shutil.which("mkvextract")

def get_alass_path():
    """Look for alass binary in TOOLS_DIR/alass/ (recursive) or on PATH."""
    d = os.path.join(TOOLS_DIR, "alass")
    if os.path.isdir(d):
        for name in ("alass-cli.exe", "alass.exe"):
            for p in Path(d).rglob(name):
                return str(p)
    return shutil.which("alass-cli") or shutil.which("alass")

IS_FROZEN = getattr(sys, "frozen", False)

# Root dir where python-based tools (ffsubsync, autosubsync) get installed via pip --target.
PY_TOOLS_DIR = os.path.join(TOOLS_DIR, "py")

def get_py_tool_dir(name):
    return os.path.join(PY_TOOLS_DIR, name)

def _ensure_py_tool_on_path(name):
    """Prepend TOOLS_DIR/py/<name> to sys.path (and its .libs for C exts) if it exists."""
    d = get_py_tool_dir(name)
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)
    # Some wheels put DLLs in <pkg>.libs subdir (numpy etc.)
    if os.path.isdir(d):
        for entry in os.listdir(d):
            if entry.endswith(".libs"):
                libs = os.path.join(d, entry)
                if os.path.isdir(libs):
                    os.add_dll_directory(libs) if hasattr(os, "add_dll_directory") else None

def _ensure_all_py_tools_on_path():
    for n in ("ffsubsync", "autosubsync"):
        _ensure_py_tool_on_path(n)

def check_py_tool_available(name, import_name=None):
    """Check whether a python tool is importable (from tools dir or env)."""
    _ensure_py_tool_on_path(name)
    try:
        __import__(import_name or name)
        return True
    except Exception:
        return False

def check_ffsubsync_available():
    return check_py_tool_available("ffsubsync")

def check_autosubsync_available():
    return check_py_tool_available("autosubsync")

def _pip_install_to_tools(pkg, target_dir, log_cb=None):
    """pip install <pkg> --target=<target_dir> using bundled or system python.
    Works both frozen (uses bundled pip) and in dev (uses sys.executable).
    pkg can be a string or a list of package names."""
    pkgs = pkg if isinstance(pkg, list) else [pkg]
    # If target exists with potentially locked .pyd files, rename it first
    if os.path.isdir(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception:
            bak = target_dir + f".old.{int(time.time())}"
            try:
                os.rename(target_dir, bak)
                if log_cb: log_cb(f"  Stari folder preimenovan ({os.path.basename(bak)})")
            except Exception as e:
                if log_cb: log_cb(f"  [WARN] Nije moguce ocistiti stari folder: {e}")
    os.makedirs(target_dir, exist_ok=True)
    if log_cb: log_cb(f"Instalacija {' '.join(pkgs)} u {target_dir}...")

    args = ["install", "--no-warn-script-location", "--disable-pip-version-check",
            "--upgrade", "--prefer-binary", "--target", target_dir] + pkgs

    # Prefer a real python interpreter if available on PATH (subprocess can build sdists).
    system_py = None if not IS_FROZEN else (shutil.which("python") or shutil.which("py"))

    if IS_FROZEN and system_py:
        if log_cb: log_cb(f"  (using system python: {system_py})")
        try:
            proc = subprocess.Popen(
                [system_py, "-m", "pip"] + args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            for line in proc.stdout:
                if log_cb and line.strip():
                    log_cb("  " + line.rstrip())
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            if log_cb: log_cb(f"[ERR] pip: {e}")
            # fall back to in-process
    if IS_FROZEN:
        # Run pip in-process (pip is bundled in the exe). Works for pure-wheel packages.
        try:
            from pip._internal.cli.main import main as pip_main
        except ImportError as e:
            if log_cb: log_cb(f"[ERR] pip nije dostupan u EXE-u: {e}")
            return False
        import io, contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = pip_main(args)
        except SystemExit as e:
            rc = int(e.code) if isinstance(e.code, int) else 1
        except Exception as e:
            if log_cb: log_cb(f"[ERR] pip: {e}")
            return False
        out = buf.getvalue()
        if log_cb:
            for line in out.splitlines():
                if line.strip():
                    log_cb("  " + line)
        return rc == 0
    else:
        # Dev mode: subprocess via python -m pip
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip"] + args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            for line in proc.stdout:
                if log_cb and line.strip():
                    log_cb("  " + line.rstrip())
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            if log_cb: log_cb(f"[ERR] pip: {e}")
            return False

def install_py_tool(name, log_cb=None):
    """Install ffsubsync / autosubsync into TOOLS_DIR/py/<name>."""
    tgt = get_py_tool_dir(name)
    pkg = name
    if name == "autosubsync":
        pkg = ["autosubsync", "setuptools"]
    ok = _pip_install_to_tools(pkg, tgt, log_cb=log_cb)
    if ok:
        _ensure_py_tool_on_path(name)
    return ok

def remove_tool(name, log_cb=None):
    """Delete a tool's TOOLS_DIR folder (binary tools) or py/<name> (python tools)."""
    # Try python-tools dir first, then regular tools dir
    targets = [get_py_tool_dir(name), os.path.join(TOOLS_DIR, name)]
    removed_any = False
    for d in targets:
        if os.path.isdir(d):
            try:
                shutil.rmtree(d, ignore_errors=False)
                if log_cb: log_cb(f"[DEL] {d}")
                removed_any = True
            except Exception:
                # .pyd / .dll files may be locked; rename folder instead
                try:
                    bak = d + f".old.{int(time.time())}"
                    os.rename(d, bak)
                    if log_cb: log_cb(f"[DEL] {d} (preimenovano u {os.path.basename(bak)})")
                    removed_any = True
                except Exception as e2:
                    if log_cb: log_cb(f"[ERR] Brisanje {d}: {e2}")
    # Clear recorded version so auto-update will re-download
    try:
        versions = load_tool_versions()
        if name in versions:
            del versions[name]
            save_all_tool_versions(versions)
    except Exception:
        pass
    # Also try to purge in-memory import cache so next check reflects removal
    for mod in list(sys.modules):
        if mod == name or mod.startswith(name + "."):
            try:
                del sys.modules[mod]
            except Exception:
                pass
    return removed_any

# Backwards-compat wrapper used in earlier code paths
def pip_install_ffsubsync(log_cb=None):
    return install_py_tool("ffsubsync", log_cb=log_cb)

def check_all_tools():
    return {"ffmpeg": get_ffmpeg_path(), "ffprobe": get_ffprobe_path(),
            "mediainfo": get_mediainfo_path(), "torrenttools": get_torrenttools_path()}

def find_main_video_in_folder(folder):
    """Return path of the largest video file in folder (recursive), or None."""
    if not folder or not os.path.isdir(folder):
        return None
    best = None
    best_size = 0
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(VIDEO_EXTENSIONS):
                p = os.path.join(root, f)
                try:
                    s = os.path.getsize(p)
                    if s > best_size:
                        best_size = s
                        best = p
                except OSError:
                    pass
    return best

def find_srt_files_in_folder(folder):
    """Return list of .srt files in folder (recursive)."""
    if not folder or not os.path.isdir(folder):
        return []
    return [str(p) for p in Path(folder).rglob("*.srt")]

def _prepend_ffmpeg_to_path():
    """Ensure bundled/downloaded ffmpeg is on PATH for ffsubsync."""
    ffmpeg = get_ffmpeg_path()
    if ffmpeg:
        d = os.path.dirname(ffmpeg)
        if d and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

def _sync_ffsubsync_in_process(video, sub, output, log_cb=None):
    """Run ffsubsync in-process. Used when frozen (EXE)."""
    _prepend_ffmpeg_to_path()
    _ensure_py_tool_on_path("ffsubsync")
    try:
        from ffsubsync.ffsubsync import run, make_parser
    except ImportError as e:
        return False, f"ffsubsync nije instaliran ({e}) - Alati -> Preuzmi ffsubsync"
    # Capture ffsubsync logging output to log_cb
    import logging, io
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    prev_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        args = make_parser().parse_args([video, "-i", sub, "-o", output])
        ret = run(args)
        rc = ret.get("retval", 0) if isinstance(ret, dict) else (ret or 0)
    except SystemExit as e:
        rc = int(e.code) if isinstance(e.code, int) else 1
    except Exception as e:
        root.removeHandler(handler)
        root.setLevel(prev_level)
        return False, str(e)
    finally:
        # flush logs captured during run
        out_text = log_stream.getvalue()
        root.removeHandler(handler)
        root.setLevel(prev_level)
        if log_cb and out_text:
            for line in out_text.splitlines():
                if line.strip():
                    log_cb(f"  {line}")
    if rc == 0 and os.path.isfile(output):
        return True, output
    return False, f"ffsubsync rc={rc}"

def sync_subtitle_ffsubsync(video, sub, output, log_cb=None):
    """Sync subtitle using ffsubsync (always in-process; loaded from TOOLS_DIR/py/ffsubsync
    or from system site-packages). Returns (ok: bool, message_or_path: str).
    """
    if log_cb: log_cb(f"[ffsubsync] {os.path.basename(sub)} -> {os.path.basename(output)}")
    return _sync_ffsubsync_in_process(video, sub, output, log_cb)

def _ensure_utf8_srt(srt_path, log_cb=None):
    """If srt_path is not UTF-8, convert it to a temp UTF-8 copy and return (tmp_path, True).
    If already UTF-8, return (srt_path, False)."""
    try:
        with open(srt_path, "rb") as f:
            raw = f.read()
        if raw[:3] == b'\xef\xbb\xbf':
            return srt_path, False
        try:
            raw.decode("utf-8")
            return srt_path, False
        except UnicodeDecodeError:
            pass
        decoded = None
        det_enc = None
        for enc in ("cp1250", "cp1251", "iso-8859-2", "iso-8859-16", "latin-1"):
            try:
                decoded = raw.decode(enc)
                if any(c in decoded for c in "ćčžšđĆČŽŠĐ"):
                    det_enc = enc
                    break
                decoded = None
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        if not decoded:
            decoded = raw.decode("cp1250", errors="replace")
            det_enc = "cp1250 (fallback)"
        tmp = srt_path + ".utf8.srt"
        with open(tmp, "wb") as f:
            f.write(decoded.encode("utf-8"))
        if log_cb:
            log_cb(f"  encoding: {det_enc} -> konvertovano u UTF-8")
        return tmp, True
    except Exception as e:
        if log_cb:
            log_cb(f"  [ERR] encoding detekcija: {e}")
        return srt_path, False

def _find_bundled_ffmpeg_near_alass():
    """alass-windows64.zip ships ffmpeg/ffprobe under a nested folder.
    Return (ffmpeg_path, ffprobe_path) or (None, None)."""
    alass_dir = os.path.join(TOOLS_DIR, "alass")
    if not os.path.isdir(alass_dir):
        return None, None
    ffm, ffp = None, None
    for p in Path(alass_dir).rglob("ffmpeg.exe"):
        ffm = str(p); break
    for p in Path(alass_dir).rglob("ffprobe.exe"):
        ffp = str(p); break
    return ffm, ffp

def sync_subtitle_alass(video, sub, output, log_cb=None):
    """Sync using alass binary. Returns (ok, message)."""
    alass = get_alass_path()
    if not alass:
        return False, "alass nije pronadjen (Alati -> Preuzmi alass)"
    if log_cb: log_cb(f"[alass] {os.path.basename(sub)} -> {os.path.basename(output)}")

    # alass needs ffmpeg/ffprobe; prefer bundled ones inside alass zip, fall back to TOOLS_DIR ffmpeg
    env = os.environ.copy()
    ffm, ffp = _find_bundled_ffmpeg_near_alass()
    if not ffm:
        ffm = get_ffmpeg_path()
    if not ffp:
        ffp = get_ffprobe_path()
    if ffm:
        env["ALASS_FFMPEG_PATH"] = ffm
        env["PATH"] = os.path.dirname(ffm) + os.pathsep + env.get("PATH", "")
    if ffp:
        env["ALASS_FFPROBE_PATH"] = ffp
    if log_cb:
        log_cb(f"  ALASS_FFMPEG_PATH={ffm or '(none)'}")
        log_cb(f"  ALASS_FFPROBE_PATH={ffp or '(none)'}")
    if not ffm or not ffp:
        return False, "ffmpeg/ffprobe nedostaje - preuzmi FFmpeg na tabu Alati"

    # alass expects UTF-8 subtitles
    actual_sub, was_converted = _ensure_utf8_srt(sub, log_cb)
    cmd = [alass, video, actual_sub, output]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                env=env, creationflags=NO_WINDOW)
        for line in proc.stdout:
            line = line.rstrip()
            if line and log_cb:
                log_cb(f"  {line}")
        proc.wait()
        if proc.returncode == 0 and os.path.isfile(output):
            return True, output
        return False, f"alass exit code {proc.returncode}"
    except Exception as e:
        return False, str(e)
    finally:
        if was_converted:
            try: os.remove(actual_sub)
            except: pass

def sync_subtitle_autosubsync(video, sub, output, log_cb=None):
    """Sync using autosubsync python package (oseiskar/autosubsync). Returns (ok, message)."""
    if log_cb: log_cb(f"[autosubsync] {os.path.basename(sub)} -> {os.path.basename(output)}")
    _prepend_ffmpeg_to_path()
    _ensure_py_tool_on_path("autosubsync")
    # autosubsync uses pkg_resources.resource_filename to find trained-model.bin
    # Provide a shim if pkg_resources is not available (common in frozen EXE)
    try:
        import pkg_resources
    except ImportError:
        import types
        _pr = types.ModuleType("pkg_resources")
        _autosubsync_dir = os.path.join(get_py_tool_dir("autosubsync"), "autosubsync")
        def _resource_filename(pkg, path):
            return os.path.join(_autosubsync_dir, path)
        _pr.resource_filename = _resource_filename
        sys.modules["pkg_resources"] = _pr
    try:
        from autosubsync import synchronize
        from autosubsync import preprocessing as _ass_prep
    except ImportError as e:
        return False, f"autosubsync nije instaliran ({e}) - Alati -> Preuzmi autosubsync"
    # Monkey-patch extract_sound: use full ffmpeg path + CREATE_NO_WINDOW
    _ffmpeg_bin = get_ffmpeg_path() or "ffmpeg"
    def _patched_extract_sound(input_video_file, output_sound_file):
        cmd = [_ffmpeg_bin, '-y', '-loglevel', 'error',
               '-i', input_video_file, '-vn', '-sn', '-ac', '1',
               output_sound_file]
        if log_cb:
            log_cb(f"  ffmpeg: extracting audio...")
        subprocess.call(cmd, creationflags=NO_WINDOW)
    _ass_prep.extract_sound = _patched_extract_sound
    # autosubsync may fail on non-UTF-8 subtitles
    actual_sub, was_converted = _ensure_utf8_srt(sub, log_cb)
    # Disable multiprocessing to prevent frozen EXE from spawning duplicate GUI windows
    import multiprocessing, multiprocessing.pool
    _orig_pool = multiprocessing.Pool
    _orig_pool2 = multiprocessing.pool.Pool
    class _SeqPool:
        def __init__(self, *a, **kw): pass
        def map(self, fn, it): return list(map(fn, it))
        def starmap(self, fn, it): return [fn(*args) for args in it]
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def close(self): pass
        def join(self): pass
        def terminate(self): pass
    multiprocessing.Pool = _SeqPool
    multiprocessing.pool.Pool = _SeqPool
    try:
        synchronize(video, actual_sub, output)
        if os.path.isfile(output):
            return True, output
        return False, "autosubsync nije generisao izlaz"
    except Exception as e:
        return False, str(e)
    finally:
        multiprocessing.Pool = _orig_pool
        multiprocessing.pool.Pool = _orig_pool2
        if was_converted:
            try: os.remove(actual_sub)
            except: pass

def sync_subtitle(video, sub, output, method="ffsubsync", log_cb=None):
    """Dispatch subtitle sync to the chosen backend. Returns (ok, message)."""
    if method == "alass":
        return sync_subtitle_alass(video, sub, output, log_cb)
    if method == "autosubsync":
        return sync_subtitle_autosubsync(video, sub, output, log_cb)
    return sync_subtitle_ffsubsync(video, sub, output, log_cb)

# ═══════════════════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="sr" data-bs-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crna Berza Tools v2.0 by Vucko</title>
<link href="__BOOTSTRAP_CSS__" rel="stylesheet">
<link href="__BOOTSTRAP_ICONS_CSS__" rel="stylesheet">
<style>
/* Ako Bootstrap ne ucita, ne prikazuj skrivene panele/modale */
.modal:not(.show){display:none!important}
.tab-pane:not(.active){display:none!important}
.collapse:not(.show){display:none!important}
.dropdown-menu:not(.show){display:none!important}
:root{
  --bg:#1a1a1c;--bg2:#232326;--bg3:#2b2b2f;--bg-sidebar:#161618;
  --accent:#2ecc71;--accent-dim:#27ae60;--accent-soft:rgba(46,204,113,.14);
  --border:#38383c;--border-light:#45454a;
  --text:#e4e4e7;--text-dim:#a1a1aa;--muted:#71717a;
  --info:#60a5fa;--purple:#a78bfa;--warn:#fbbf24;--danger:#f87171;
  --radius:6px;--radius-sm:4px;
  --font:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;
  --font-mono:'Cascadia Mono','Cascadia Code','Consolas',monospace;
  --sidebar-w:196px;--status-h:26px;--ease:cubic-bezier(.2,0,.2,1);
  --shadow-inset:inset 0 1px 0 rgba(255,255,255,.04);
  --panel-shadow:0 1px 0 rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.03);
}
*{scrollbar-width:thin;scrollbar-color:#45454a transparent;box-sizing:border-box}
*::-webkit-scrollbar{width:7px;height:7px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:#45454a;border-radius:3px}
*::-webkit-scrollbar-thumb:hover{background:#5a5a60}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;overflow:hidden;height:100vh;margin:0;-webkit-font-smoothing:antialiased;position:relative}
/* ─── Sidebar (VS Code / native nav) ─── */
.sidebar{width:var(--sidebar-w);position:fixed;left:0;top:0;bottom:0;background:var(--bg-sidebar);border-right:1px solid var(--border);z-index:100;display:flex;flex-direction:column;transition:width .18s var(--ease)}
.sidebar .logo{padding:0 10px;height:44px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:6px;flex-shrink:0}
.sidebar .logo h5{margin:0;font-weight:600;letter-spacing:.2px;font-size:14px;color:var(--text);white-space:nowrap;overflow:hidden;display:flex;align-items:center;gap:8px;min-width:0;flex:1}
.sidebar .logo h5 i{color:var(--accent);font-size:15px;flex-shrink:0}
.sidebar-collapse-btn{width:28px;height:28px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text-dim);display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;padding:0;transition:background .12s,border-color .12s,color .12s}
.sidebar-collapse-btn:hover{background:var(--bg);border-color:var(--border-light);color:var(--text)}
.sidebar-collapse-btn i{font-size:14px;line-height:1}
.sidebar .nav{flex:1;padding:6px 8px;overflow-y:auto;overflow-x:hidden}
.nav-group-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);padding:10px 10px 4px;white-space:nowrap}
.sidebar .nav-link{color:var(--text-dim);padding:7px 10px;font-size:12.5px;font-weight:400;transition:background .12s var(--ease),color .12s;border-radius:var(--radius-sm);display:flex;align-items:center;gap:9px;margin:1px 0;position:relative;white-space:nowrap;border:1px solid transparent}
.sidebar .nav-link:hover{color:var(--text);background:rgba(255,255,255,.04)}
.sidebar .nav-link.active{color:var(--text);background:var(--bg3);border-color:var(--border-light);box-shadow:var(--shadow-inset)}
.sidebar .nav-link.active::before{content:'';position:absolute;left:-8px;top:6px;bottom:6px;width:2px;background:var(--accent);border-radius:0 2px 2px 0}
.sidebar .nav-link i{font-size:14px;width:18px;text-align:center;opacity:.85;flex-shrink:0}
.sidebar .nav-link.active i{color:var(--accent);opacity:1}
.sidebar-toggle{display:none}
.sidebar-footer{height:var(--status-h);min-height:var(--status-h);padding:0 10px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:auto;font-size:11px;line-height:1;color:var(--muted);letter-spacing:.02em;box-sizing:border-box}
body.sidebar-collapsed .sidebar{width:52px}
body.sidebar-collapsed .sidebar .logo{justify-content:center;padding:0;height:40px;border-bottom:1px solid var(--border)}
body.sidebar-collapsed .sidebar .logo h5{display:none!important}
body.sidebar-collapsed .sidebar-collapse-btn{width:32px;height:32px;border:none;background:transparent;color:var(--accent)}
body.sidebar-collapsed .sidebar-collapse-btn:hover{background:var(--bg3);border:1px solid var(--border)}
body.sidebar-collapsed .sidebar .nav-link span,body.sidebar-collapsed .nav-group-label{display:none}
body.sidebar-collapsed .sidebar .nav-link{justify-content:center;padding:9px 0}
body.sidebar-collapsed .sidebar-footer{display:none}
body.sidebar-collapsed .main-content,body.sidebar-collapsed .status-bar{margin-left:52px}
body.sidebar-collapsed .status-bar{left:52px}
/* ─── Main workspace ─── */
.main-content{margin-left:var(--sidebar-w);padding:0;height:calc(100vh - var(--status-h));overflow:hidden;transition:margin-left .18s var(--ease);display:flex;flex-direction:column}
.page{display:none;flex:1;flex-direction:column;min-height:0;opacity:0;transform:translateX(6px);pointer-events:none;transition:opacity .16s var(--ease),transform .16s var(--ease)}
.page.active{display:flex;opacity:1;transform:none;pointer-events:auto}
.page-scroll{flex:1;overflow-y:auto;padding:12px 14px;min-height:0}
.page-title{font-size:15px;font-weight:600;margin:0 0 10px;padding:12px 14px 0;display:flex;align-items:center;gap:8px;color:var(--text);letter-spacing:0}
.page-title i{color:var(--accent);font-size:16px}
/* ─── App toolbar (replaces web hero) ─── */
.app-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 14px;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;min-height:40px}
.app-toolbar-title{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:var(--text)}
.app-toolbar-title i{color:var(--accent);font-size:14px}
.app-toolbar-sub{font-size:11px;color:var(--muted);font-weight:400;margin-left:4px}
.app-toolbar-actions{display:flex;align-items:center;gap:4px}
.tb-btn{width:30px;height:28px;border-radius:var(--radius-sm);background:transparent;border:1px solid transparent;color:var(--muted);display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer;transition:background .12s,border-color .12s,color .12s}
.tb-btn:hover{background:var(--bg3);border-color:var(--border);color:var(--text)}
/* ─── Panels (not web cards) ─── */
.card,.panel{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--panel-shadow);transition:border-color .12s}
.card:hover{transform:none;box-shadow:var(--panel-shadow)}
.card-header{background:var(--bg3);border-bottom:1px solid var(--border);font-size:12px;font-weight:600;color:var(--text-dim);padding:6px 12px;border-radius:var(--radius) var(--radius) 0 0}
.btn{border-radius:var(--radius-sm);font-weight:500;font-size:12.5px;transition:background .12s,border-color .12s,box-shadow .12s;box-shadow:none!important}
.btn-accent{background:var(--accent-dim);color:#fff;border:1px solid #229954}
.btn-accent:hover,.btn-accent:focus{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn-accent:active{background:#1e8449;transform:none}
.btn-outline-accent{background:var(--bg3);color:var(--accent);border:1px solid var(--border-light)}
.btn-outline-accent:hover{background:var(--accent-soft);color:var(--accent);border-color:rgba(46,204,113,.35);transform:none}
.form-control,.form-select{background:var(--bg);border:1px solid var(--border);color:var(--text);font-size:12.5px;border-radius:var(--radius-sm);transition:border-color .12s,box-shadow .12s;height:32px}
.form-control:focus,.form-select:focus{background:var(--bg);border-color:var(--accent-dim);color:var(--text);box-shadow:0 0 0 1px var(--accent-dim)}
.form-control::placeholder{color:var(--muted)}
.input-group .btn{border-radius:var(--radius-sm)}
.log-box{background:#141416;color:#b4b4bc;font-family:var(--font-mono);font-size:11.5px;line-height:1.55;border-radius:0;padding:4px 2px;overflow-y:auto;word-wrap:break-word;border:none;flex:1;min-height:0}
.log-box .log-line{display:flex;align-items:flex-start;gap:8px;padding:2px 10px;border-radius:2px;transition:background .08s}
.log-box .log-line:hover{background:rgba(255,255,255,.03)}
.log-box .log-time{flex-shrink:0;color:#52525b;font-size:10px;line-height:1.7;min-width:52px;user-select:none;font-variant-numeric:tabular-nums}
.log-box .log-ico{flex-shrink:0;font-size:12px;line-height:1.5;margin-top:1px}
.log-box .log-msg{flex:1;white-space:pre-wrap;word-break:break-word}
.log-box .log-copy{flex-shrink:0;opacity:0;background:transparent;border:none;color:var(--muted);cursor:pointer;font-size:11px;padding:0 4px}
.log-box .log-line:hover .log-copy{opacity:1}
.log-box .log-copy:hover{color:var(--accent)}
.log-box .log-ico.log-err{color:var(--danger)}
.log-box .log-ico.log-ok{color:var(--accent)}
.log-box .log-ico.log-warn{color:var(--warn)}
.log-box .log-ico.log-info{color:var(--info)}
.log-box .log-ico.log-load{color:var(--warn)}
.log-box .log-ico.log-update{color:var(--purple)}
.log-box .log-ico.log-plain{color:#52525b}
.log-box .log-line.log-err .log-msg{color:#fca5a5}
.log-box .log-line.log-ok .log-msg{color:#86efac}
.log-box .log-line.log-warn .log-msg{color:#fde68a}
.log-box .log-sep{margin:6px 4px 2px;padding:3px 10px;color:var(--accent-dim);font-weight:600;text-transform:uppercase;letter-spacing:.06em;font-size:10px;display:flex;align-items:center;gap:6px;border-top:1px solid var(--border)}
.tools-table td{vertical-align:middle}
.tools-table .path-cell{position:relative;max-width:0}
.tools-table .path-cell .path-text{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px;color:var(--muted);word-break:break-all}
.tools-table .path-cell:hover .path-text{visibility:hidden}
.tools-table .path-cell:hover::after{content:attr(data-path);position:absolute;left:8px;top:50%;transform:translateY(-50%);background:var(--bg3);border:1px solid var(--border-light);color:var(--text);padding:5px 8px;border-radius:var(--radius-sm);font-size:11px;z-index:20;white-space:normal;word-break:break-all;max-width:600px;box-shadow:0 4px 16px rgba(0,0,0,.4);pointer-events:none}
.tools-table .actions-cell{white-space:nowrap;text-align:right;padding-right:12px}
.tools-table .actions-cell .btn{padding:3px 8px;font-size:11px}
.tools-table .actions-cell .btn+.btn{margin-left:3px}
.tools-table .badge{font-size:10px}
.progress{height:3px;background:var(--border);border-radius:2px;overflow:hidden;margin:0}
.progress-bar{background:var(--accent);transition:width .25s var(--ease)}
.status-bar{position:fixed;bottom:0;left:var(--sidebar-w);right:0;background:var(--bg-sidebar);border-top:1px solid var(--border);padding:0 12px;font-size:11px;line-height:1;color:var(--muted);z-index:100;height:var(--status-h);min-height:var(--status-h);display:flex;align-items:center;justify-content:space-between;transition:left .18s var(--ease);font-variant-numeric:tabular-nums;box-sizing:border-box}
.status-bar #statusText{color:var(--text-dim);display:flex;align-items:center;gap:6px}
.status-dot{font-size:7px;color:var(--accent);animation:statusBlink 2.4s ease-in-out infinite}
@keyframes statusBlink{0%,100%{opacity:1}50%{opacity:.35}}
#statusRight{font-size:10px;color:var(--muted)}
.imdb-card{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);transition:border-color .12s,background .12s;cursor:default}
.imdb-card:hover{border-color:var(--border-light);background:var(--bg2);transform:none;box-shadow:none}
.poster-img{width:80px;min-height:120px;border-radius:var(--radius-sm);object-fit:cover;background:var(--bg)}
.poster-ph{width:80px;min-height:120px;border-radius:var(--radius-sm);background:var(--bg);display:flex;align-items:center;justify-content:center}
.upload-section{background:var(--bg3);border-radius:var(--radius-sm);padding:12px;margin-bottom:10px;border:1px solid var(--border)}
.upload-section .lbl{color:var(--accent);font-weight:600;font-size:11px;min-width:100px}
.table-dark{--bs-table-bg:transparent}
.table-dark td,.table-dark th{border-color:var(--border)}
.modal-content{background:var(--bg2);border:1px solid var(--border-light);border-radius:var(--radius);box-shadow:0 16px 48px rgba(0,0,0,.55)}
.modal-header,.modal-footer{border-color:var(--border);padding:10px 14px}
.modal.show .modal-dialog{animation:modalIn .18s var(--ease)}
@keyframes modalIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.ss-thumb{width:160px;height:100px;object-fit:cover;border-radius:var(--radius-sm);border:1px solid var(--border)}
.form-text{color:var(--muted)!important;font-size:11px}
.badge{font-weight:500}
.btn-outline-light{border-color:var(--border);color:var(--text-dim);background:var(--bg3)}
.btn-outline-light:hover{background:var(--bg);border-color:var(--border-light);color:var(--text)}
.btn-outline-light:focus,.btn-outline-light:focus-visible,.btn-outline-light:active{box-shadow:none!important;border-color:var(--border-light);background:var(--bg);color:var(--text)}
.btn-check:focus+.btn,.btn-check:focus-visible+.btn{box-shadow:none!important;outline:none!important}
.preview-section{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;margin-bottom:10px}
.preview-header{padding:8px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px;font-size:10px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.preview-header i{color:var(--accent);font-size:12px}
.preview-body{padding:12px}
.info-tbl{width:100%;font-size:12.5px;border-collapse:separate;border-spacing:0}
.info-tbl td{padding:7px 12px;border-bottom:1px solid var(--border)}
.info-tbl .il{color:var(--muted);width:130px;white-space:nowrap}
.info-tbl .iv{color:var(--text)}
.genre-badge{display:inline-block;padding:2px 8px;border-radius:var(--radius-sm);font-size:10px;font-weight:600;margin-right:3px;margin-bottom:2px;background:var(--accent-soft);color:var(--accent)}
.sub-flag{display:inline-block;padding:2px 0;margin-right:6px}
.mi-grid{display:grid;grid-template-columns:1fr 1fr 1fr}
.mi-grid>div{padding:12px}
.mi-grid>div:not(:last-child){border-right:1px solid var(--border)}
.mi-title{font-size:10px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.mi-tbl{width:100%;font-size:11px}
.mi-tbl td{padding:2px 0}
.mi-tbl .mk{color:var(--muted);padding-right:8px;white-space:nowrap}
.mi-tbl .mv{color:var(--text)}
.ss-row{display:flex;gap:8px;overflow-x:auto;padding:2px}
.ss-row img{width:180px;height:110px;object-fit:cover;border-radius:var(--radius-sm);border:1px solid var(--border);flex-shrink:0}
.cat-badge{display:inline-block;padding:2px 7px;border-radius:var(--radius-sm);font-size:10px;font-weight:500;background:var(--accent-soft);border:1px solid rgba(46,204,113,.25);color:var(--accent)}
.imdb-link{color:#facc15;text-decoration:none;font-size:12px}
.imdb-link:hover{color:#fde68a}
.sub-tag{display:inline-flex;align-items:center;font-size:10px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px 7px;color:var(--text-dim)}
/* ─── Pipeline stepper (desktop installer style) ─── */
.pipeline{display:flex;align-items:flex-start;user-select:none;gap:0;padding-bottom:2px}
.pipe-step{display:flex;flex-direction:column;align-items:center;cursor:pointer;position:relative;z-index:1;flex:0 0 auto;min-width:76px}
.pipe-circle{width:26px;height:26px;border-radius:50%;background:var(--bg);border:1px solid var(--border-light);display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--muted);transition:background .15s,border-color .15s,color .15s,box-shadow .15s;flex-shrink:0}
.pipe-step:hover:not(.locked) .pipe-circle{border-color:var(--accent-dim);color:var(--accent)}
.pipe-step.locked{cursor:not-allowed;opacity:.35}
.pipe-step.done .pipe-circle{background:var(--accent-dim);border-color:var(--accent-dim);color:#fff}
.pipe-step.active .pipe-circle{background:var(--accent);border-color:var(--accent);color:#fff;box-shadow:0 0 0 3px var(--accent-soft);animation:stepPulse 1.6s ease-in-out infinite}
.pipe-undo{margin-top:5px;font-size:10px;color:var(--text-dim);cursor:pointer;opacity:0;visibility:hidden;transition:opacity .12s,background .12s,border-color .12s,color .12s;display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:var(--radius-sm);border:1px solid transparent;background:transparent;line-height:1.2;white-space:nowrap}
.pipe-step.done .pipe-undo{opacity:1;visibility:visible}
.pipe-undo:hover{color:var(--danger);border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.08)}
.pipe-undo i{font-size:10px}
@keyframes stepPulse{0%,100%{box-shadow:0 0 0 3px var(--accent-soft)}50%{box-shadow:0 0 0 5px rgba(46,204,113,.08)}}
.pipe-label{font-size:9px;margin-top:6px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em;text-align:center}
.pipe-step.done .pipe-label,.pipe-step.active .pipe-label{color:var(--accent)}
.pipe-line{flex:1;height:2px;background:var(--border);margin:0 4px;position:relative;overflow:hidden;border-radius:1px;align-self:flex-start;margin-top:13px}
.pipe-line::after{content:'';position:absolute;inset:0;background:var(--accent);transform:scaleX(0);transform-origin:left;transition:transform .35s var(--ease)}
.pipe-line.filled::after{transform:scaleX(1)}
.toast-wrap{position:fixed;bottom:calc(var(--status-h) + 10px);right:12px;z-index:10000;display:flex;flex-direction:column;gap:6px}
.app-toast{background:var(--bg2);border:1px solid var(--border-light);border-radius:var(--radius-sm);padding:10px 14px;display:flex;align-items:center;gap:9px;font-size:12px;color:var(--text);box-shadow:0 8px 24px rgba(0,0,0,.45);animation:toastIn .2s var(--ease);min-width:240px}
.app-toast.out{animation:toastOut .15s ease forwards}
.app-toast.success{border-left:2px solid var(--accent)}
.app-toast.error{border-left:2px solid var(--danger)}
.app-toast.info{border-left:2px solid var(--info)}
.app-toast i{font-size:15px;flex-shrink:0}
.app-toast.success i{color:var(--accent)}
.app-toast.error i{color:var(--danger)}
.app-toast.info i{color:var(--info)}
@keyframes toastIn{from{transform:translateY(8px);opacity:0}to{transform:none;opacity:1}}
@keyframes toastOut{to{transform:translateY(4px);opacity:0}}
.skeleton{position:relative;overflow:hidden;background:var(--bg3);border-radius:var(--radius-sm)}
.skeleton::after{content:'';position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(90deg,transparent,rgba(255,255,255,.04),transparent);animation:shimmer 1.2s infinite}
@keyframes shimmer{100%{transform:translateX(100%)}}
.skeleton-line{height:11px;margin:6px 0;border-radius:3px}
.skeleton-row{height:36px;margin:4px 0;border-radius:var(--radius-sm)}

/* ─── Light Theme ─── */
body.light{--bg:#f0f0f2;--bg2:#ffffff;--bg3:#f4f4f5;--bg-sidebar:#e8e8eb;--accent:#16a34a;--accent-dim:#15803d;--accent-soft:rgba(22,163,74,.1);--border:#d4d4d8;--border-light:#e4e4e7;--text:#18181b;--text-dim:#3f3f46;--muted:#71717a}
body.light{color-scheme:light}
body.light .sidebar{background:var(--bg-sidebar);border-right-color:var(--border)}
body.light .sidebar .logo{border-bottom-color:var(--border)}
body.light .sidebar .nav-link{color:var(--text-dim)}
body.light .sidebar .nav-link:hover{color:var(--text);background:rgba(0,0,0,.04)}
body.light .sidebar .nav-link.active{background:#fff;border-color:var(--border)}
body.light .card,.body.light .panel{background:#fff;border-color:var(--border)}
body.light .card-header{background:var(--bg3);border-bottom-color:var(--border);color:var(--text-dim)}
body.light .form-control,body.light .form-select{background:#fff;border-color:var(--border);color:var(--text)}
body.light .form-control:focus,body.light .form-select:focus{border-color:var(--accent-dim);box-shadow:0 0 0 1px var(--accent-dim)}
body.light .log-box{background:#fafafa;color:#3f3f46;border-color:var(--border)}
body.light .modal-content{background:#fff;border-color:var(--border)}
body.light .modal-header,.body.light .modal-footer{border-color:var(--border)}
body.light .table-dark{--bs-table-bg:#fff;--bs-table-color:var(--text);--bs-table-border-color:var(--border)}
body.light .status-bar{background:var(--bg-sidebar);border-top-color:var(--border)}
body.light .app-toolbar{background:#fff;border-bottom-color:var(--border)}
body.light .btn-outline-light{background:#fff;border-color:var(--border);color:var(--text-dim)}
body.light .btn-outline-light:hover{background:var(--bg3);border-color:var(--border-light);color:var(--text)}
body.light .pipe-circle{background:#fff;border-color:var(--border)}
body.light .pipe-line{background:var(--border)}
body.light .stat-card{background:#fff;border-color:var(--border)}
body.light .app-toast{background:#fff;border-color:var(--border);color:var(--text)}
body.light .imdb-card{background:var(--bg3)}
body.light .preview-section{background:var(--bg3);border-color:var(--border)}
body.light .upload-section{background:var(--bg3);border-color:var(--border)}
body.light .log-filters .btn.active-filter{background:var(--accent-dim);border-color:var(--accent-dim)}
body.light .desc-preview{background:#fff;border-color:var(--border);color:var(--text-dim)}
body.light .sub-chip{background:#fff}
body.light .help-block{background:var(--bg3)}
body.light .code-lines{background:#1e1e1e}
body.light .tb-btn:hover{background:var(--bg3)}

/* Section labels */
.section-cap{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 6px 2px;display:flex;align-items:center;gap:5px}
.section-cap i{color:var(--accent);font-size:11px}

/* Main workspace layout */
.workspace-main{flex:1;display:flex;flex-direction:column;gap:8px;padding:10px 14px;min-height:0}
.panel-input{padding:10px 12px}
.panel-steps .card-body{padding-bottom:12px}
.panel-steps .progress{margin-top:10px}
.panel-console{flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.panel-console .card-body{flex:1;display:flex;flex-direction:column;min-height:0;padding:0!important}
.panel-console .log-box{border-radius:0 0 var(--radius) var(--radius)}

/* Stats */
#statsRow{display:flex;gap:8px}
#statsRow>.col{flex:1 1 0;min-width:0;max-width:none}
.stat-card{text-align:left;padding:12px;border-radius:var(--radius);background:var(--bg2);border:1px solid var(--border);height:100%;box-shadow:var(--panel-shadow)}
.stat-card .stat-ico{float:right;font-size:15px;color:var(--accent);opacity:.5}
.stat-val{font-size:20px;font-weight:600;color:var(--text);line-height:1.2;font-variant-numeric:tabular-nums}
.stat-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:3px}

/* Log Filters */
.log-filters{display:flex;gap:2px;align-items:center;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px}
.log-filters .btn{font-size:10px;padding:2px 8px;border-radius:3px;border:none;background:transparent;color:var(--muted)}
.log-filters .btn:hover{color:var(--text);background:var(--bg3)}
.log-filters .btn.active-filter{background:var(--bg3);color:var(--text);border:1px solid var(--border-light)}

/* Queue Badge */
.queue-badge{position:absolute;top:-4px;right:-4px;background:#ef4444;color:#fff;font-size:9px;width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700}

/* Desc Preview */
.desc-preview{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;color:var(--text);overflow-y:auto;max-height:350px;line-height:1.6}
.desc-preview .bb-center{text-align:center}
.desc-preview .bb-bold{font-weight:700}
.desc-preview .bb-size24{font-size:20px}
.desc-preview .bb-url{color:var(--accent);text-decoration:underline}

/* ─── Toggle radio btn-group (Source mode + Request status) ─── */
.btn-check+.btn{background:var(--bg3);border:1px solid var(--border);color:var(--muted);transition:background .12s,border-color .12s,color .12s;font-size:11px;padding:3px 10px}
.btn-check+.btn:hover{background:var(--bg);color:var(--text);border-color:var(--border-light)}
.btn-check:checked+.btn,.btn-check:active+.btn{background:var(--accent-dim)!important;color:#fff!important;border-color:var(--accent-dim)!important;box-shadow:none!important}
body.light .btn-check+.btn{border-color:#CBD5E1;color:#64748B}
body.light .btn-check:checked+.btn,body.light .btn-check:active+.btn{background:linear-gradient(135deg,#16A34A,#22C55E)!important;color:#fff!important;border-color:#22C55E!important}

/* ─── Alerts (info/warning/danger) — themed dark/light ─── */
.alert{border-radius:8px;border:1px solid;font-size:12px;padding:10px 14px;margin-bottom:0}
.alert-info{background:rgba(59,130,246,.10);border-color:rgba(59,130,246,.35);color:#93C5FD}
.alert-info code,.alert-warning code,.alert-success code{background:rgba(255,255,255,.08);color:inherit;border:1px solid rgba(255,255,255,.12);padding:1px 5px;border-radius:4px;font-size:11px}
.alert-warning{background:rgba(245,158,11,.10);border-color:rgba(245,158,11,.35);color:#FCD34D}
.alert-success{background:rgba(34,197,94,.10);border-color:rgba(34,197,94,.35);color:#86EFAC}
.alert-danger{background:rgba(239,68,68,.10);border-color:rgba(239,68,68,.35);color:#FCA5A5}
body.light .alert-info{background:rgba(59,130,246,.08);border-color:rgba(59,130,246,.30);color:#1D4ED8}
body.light .alert-warning{background:rgba(245,158,11,.08);border-color:rgba(245,158,11,.30);color:#92400E}
body.light .alert-success{background:rgba(34,197,94,.08);border-color:rgba(34,197,94,.30);color:#15803D}
body.light .alert-danger{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.30);color:#991B1B}
body.light .alert-info code,body.light .alert-warning code,body.light .alert-success code{background:rgba(0,0,0,.06);border-color:rgba(0,0,0,.10)}

/* ─── Tab content (IMDB modal, etc.) ─── */
.nav-tabs{border-bottom-color:var(--border)!important}
.nav-tabs .nav-link{color:var(--muted);background:transparent;border:1px solid transparent;border-bottom:none;font-size:13px;padding:8px 14px;border-radius:8px 8px 0 0;transition:all .15s}
.nav-tabs .nav-link:hover{color:var(--text);border-color:var(--border) var(--border) transparent var(--border);background:rgba(34,197,94,.04)}
.nav-tabs .nav-link.active{color:var(--accent)!important;background:var(--bg2)!important;border-color:var(--border) var(--border) var(--bg2) var(--border)!important;font-weight:600}
body.light .nav-tabs .nav-link.active{background:#FFFFFF!important;border-color:#E2E8F0 #E2E8F0 #FFFFFF #E2E8F0!important;color:#16A34A!important}

/* ─── Form labels & checkboxes consistent ─── */
.form-label{color:var(--text);margin-bottom:4px}
.form-label.small,label.small{color:var(--muted)}
.form-check-input{background-color:var(--bg3);border-color:var(--border)}
.form-check-input:checked{background-color:var(--accent);border-color:var(--accent)}
.form-check-input:focus{border-color:var(--accent);box-shadow:0 0 0 .2rem var(--accent-soft)}

/* ─── Tables ─── */
.table>thead{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted)}
.table>thead th{padding:10px 8px;font-weight:600}
.table tbody td{padding:10px 8px;vertical-align:middle}
.table tbody tr{border-bottom:1px solid var(--border)}
.table tbody tr:last-child{border-bottom:none}
.table tbody tr:hover{background:rgba(34,197,94,.04)}
body.light .table tbody tr:hover{background:rgba(22,163,74,.04)}

/* ─── Software/programs page form ─── */
#page-software .form-control,#page-software .form-select{font-size:13px}
#page-software .form-label{font-weight:500}
.sw-action-row{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}

/* ─── Remote browser modal ─── */
#remoteBrowserModal .modal-body{padding:16px}
#rbList{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:6px 0}
#rbList>div:hover{background:rgba(34,197,94,.06)}
body.light #rbList{background:#F8FAFC}
body.light #rbList>div:hover{background:rgba(22,163,74,.05)}

/* ─── Action button row on main page ─── */
.action-buttons{display:flex;gap:8px;flex-wrap:wrap}
.action-buttons .btn{display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:8px 14px;border-radius:8px;font-weight:600;white-space:nowrap}
.action-buttons .btn-quick{background:var(--accent-dim);color:#fff;border:1px solid #229954}
.action-buttons .btn-quick:hover{background:var(--accent);color:#fff;transform:none;box-shadow:none}
.action-buttons .btn-queue{background:rgba(59,130,246,.10);color:#60A5FA;border:1px solid rgba(59,130,246,.35)}
.action-buttons .btn-queue:hover{background:rgba(59,130,246,.18);color:#93C5FD;border-color:rgba(59,130,246,.55)}
.action-buttons .btn-batch{background:rgba(168,85,247,.10);color:#C084FC;border:1px solid rgba(168,85,247,.35)}
.action-buttons .btn-batch:hover{background:rgba(168,85,247,.18);color:#D8B4FE;border-color:rgba(168,85,247,.55)}
body.light .action-buttons .btn-queue{background:rgba(37,99,235,.08);color:#1D4ED8;border-color:rgba(37,99,235,.30)}
body.light .action-buttons .btn-queue:hover{background:rgba(37,99,235,.14);color:#1E40AF}
body.light .action-buttons .btn-batch{background:rgba(147,51,234,.08);color:#7C3AED;border-color:rgba(147,51,234,.30)}
body.light .action-buttons .btn-batch:hover{background:rgba(147,51,234,.14);color:#6D28D9}

/* ─── Subtitles picker chips (upload modal) ─── */
.sub-chip{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:14px;font-size:11px;font-weight:600;letter-spacing:.3px;background:var(--bg3);border:1px solid var(--border);color:var(--muted);cursor:pointer;transition:all .15s;text-transform:uppercase;user-select:none}
.sub-chip:hover{border-color:var(--accent);color:var(--text)}
.sub-chip.active{background:rgba(34,197,94,.15);border-color:var(--accent);color:var(--accent);box-shadow:0 0 0 1px rgba(34,197,94,.20)}
.sub-chip.active i{color:var(--accent)}
.sub-chip img{width:16px;height:12px;object-fit:cover;border-radius:2px;flex-shrink:0}
body.light .sub-chip{background:#F8FAFC}
body.light .sub-chip.active{background:rgba(22,163,74,.10);color:#15803D}

/* ─── Category picker modal ─── */
#catPickerModal .modal-body{padding:0}
#catPickerList .cat-item{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .12s;font-size:13px}
#catPickerList .cat-item:last-child{border-bottom:none}
#catPickerList .cat-item:hover{background:rgba(34,197,94,.08)}
#catPickerList .cat-item .cat-id{display:inline-flex;min-width:42px;height:24px;align-items:center;justify-content:center;background:var(--bg3);border:1px solid var(--border);border-radius:6px;font-family:'Consolas',monospace;font-size:11px;font-weight:700;color:var(--accent);flex-shrink:0}
#catPickerList .cat-item .cat-name{color:var(--text);flex:1}
body.light #catPickerList .cat-item:hover{background:rgba(22,163,74,.06)}
body.light #catPickerList .cat-item .cat-id{background:#F1F5F9}
#catPickerSearch{margin:14px 14px 8px 14px;width:calc(100% - 28px)}
.help-block{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.help-block h6{color:var(--accent);font-size:13px;font-weight:700;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.help-block pre{background:var(--bg);color:#86EFAC;padding:10px 12px;border-radius:6px;font-size:11px;border:1px solid var(--border);overflow-x:auto;margin:0;white-space:pre-wrap;word-break:break-all}
body.light .help-block{background:#F8FAFC}
body.light .help-block pre{background:#0F172A;color:#86EFAC}
.help-block .step-num{display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;font-weight:700;align-items:center;justify-content:center;margin-right:8px;flex-shrink:0}
.help-block ul{margin:0;padding-left:18px;font-size:12px;color:var(--muted)}
.help-block ul li{margin-bottom:3px}
.code-block{position:relative;margin:6px 0;display:flex;flex-direction:column}
.code-block .copy-btn{align-self:flex-end;margin-bottom:6px;background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.45);color:#86EFAC;padding:4px 11px;font-size:10px;border-radius:6px;cursor:pointer;font-weight:600;letter-spacing:.3px;transition:all .15s;display:inline-flex;align-items:center;gap:5px;text-transform:uppercase}
.code-block .copy-btn:hover{background:rgba(34,197,94,.30);color:#fff;border-color:#22C55E}
.code-block .copy-btn.copied{background:#22C55E;color:#fff;border-color:#22C55E}
body.light .code-block .copy-btn{background:rgba(22,163,74,.15);border-color:rgba(22,163,74,.40);color:#15803D}
body.light .code-block .copy-btn:hover{background:rgba(22,163,74,.28);color:#fff;border-color:#16A34A}
.code-lines{background:var(--bg);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.code-line{display:flex;align-items:center;gap:8px;padding:6px 10px;font-family:'JetBrains Mono','Consolas',monospace;font-size:11.5px;border-bottom:1px solid rgba(255,255,255,.04);transition:background .12s}
.code-line:last-child{border-bottom:none}
.code-line:hover{background:rgba(34,197,94,.07)}
.code-line code{flex:1;color:#86EFAC;white-space:pre-wrap;word-break:break-all;background:transparent;padding:0}
.code-line-copy{flex-shrink:0;opacity:0;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.3);color:#86EFAC;border-radius:5px;width:26px;height:24px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:11px;transition:all .15s}
.code-line:hover .code-line-copy{opacity:1}
.code-line-copy:hover{background:rgba(34,197,94,.28);color:#fff}
.code-line-copy.copied{background:var(--accent);color:#fff;border-color:var(--accent);opacity:1}
body.light .code-lines{background:#0F172A;border-color:#1E293B}
body.light .code-line{border-bottom-color:rgba(255,255,255,.05)}

/* ─── Source mode header ─── */
.src-mode-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:10px;flex-wrap:wrap}
.src-mode-bar .btn-group .btn{padding:4px 10px!important;font-size:11px!important}

/* ─── Software page polish ─── */
#page-software .software-form{padding:12px}
#page-software .software-form .mt-2{margin-top:.4rem!important}
#page-software .software-form .mt-3{margin-top:.55rem!important}
#page-software label.form-label{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);font-weight:600;margin-bottom:4px;display:block}
#page-software .sw-source-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding-bottom:10px;margin-bottom:10px;border-bottom:1px solid var(--border)}
#page-software .sw-source-label{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);font-weight:600}
#page-software .software-page{flex:1;display:flex;flex-direction:column;min-height:0;padding:12px 14px;overflow:hidden}
#page-software .software-form{flex-shrink:0}
#page-software .software-console{flex:1;display:flex;flex-direction:column;min-height:0;margin-bottom:0!important}
#page-software .software-console .card-body{flex:1;display:flex;flex-direction:column;min-height:0;padding:0!important}
#page-software .software-console .log-box{flex:1;height:auto!important;min-height:72px}
#page-software #swDesc{min-height:112px;height:112px;resize:vertical;max-height:200px;line-height:1.45}
#page-software .sw-fields-row{align-items:flex-start}
#page-software .sw-fields-row .sw-field-col{display:flex;flex-direction:column}
#page-software .sw-fields-row .sw-field-hint{font-size:11px;min-height:16px;margin-top:2px}
#page-software .sw-fields-row .form-select-sm,#page-software .sw-fields-row .input-group-sm .form-control{height:32px}
#swImagesPreview .badge{background:rgba(34,197,94,.10)!important;color:var(--accent);border:1px solid rgba(34,197,94,.30);padding:5px 9px;font-weight:500}
body.light #swImagesPreview .badge{background:rgba(22,163,74,.08)!important;color:#15803D;border-color:rgba(22,163,74,.25)}

/* ─── Requests table ─── */
#page-requests .table tbody td{font-size:12px}
.req-status-pill{display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.3px}
.req-status-pending{background:rgba(245,158,11,.12);color:#FCD34D;border:1px solid rgba(245,158,11,.30)}
.req-status-processing{background:rgba(59,130,246,.12);color:#93C5FD;border:1px solid rgba(59,130,246,.30)}
.req-status-done{background:rgba(34,197,94,.12);color:#86EFAC;border:1px solid rgba(34,197,94,.30)}
.req-status-error{background:rgba(239,68,68,.12);color:#FCA5A5;border:1px solid rgba(239,68,68,.30)}
body.light .req-status-pending{background:rgba(245,158,11,.10);color:#92400E}
body.light .req-status-processing{background:rgba(59,130,246,.10);color:#1D4ED8}
body.light .req-status-done{background:rgba(34,197,94,.10);color:#15803D}
body.light .req-status-error{background:rgba(239,68,68,.10);color:#991B1B}
.req-action-btn{padding:4px 9px!important;font-size:11px!important;margin-left:3px;border-radius:6px!important}
.req-url-link{color:var(--accent)!important;text-decoration:none;font-family:'Consolas',monospace;font-size:11px}
.req-url-link:hover{text-decoration:underline}

/* ─── Queue list polish ─── */
#queueList>.card{padding:8px 12px}
.q-status-pill{display:inline-block;padding:2px 9px;border-radius:10px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.3px;min-width:80px;text-align:center}
.q-status-waiting{background:rgba(148,163,184,.15);color:var(--muted);border:1px solid var(--border)}
.q-status-running{background:rgba(245,158,11,.12);color:#FCD34D;border:1px solid rgba(245,158,11,.30)}
.q-status-done{background:rgba(34,197,94,.12);color:#86EFAC;border:1px solid rgba(34,197,94,.30)}
.q-status-error{background:rgba(239,68,68,.12);color:#FCA5A5;border:1px solid rgba(239,68,68,.30)}
body.light .q-status-running{color:#92400E}
body.light .q-status-done{color:#15803D}
body.light .q-status-error{color:#991B1B}
</style>
</head>
<body>

<div class="toast-wrap" id="toastWrap"></div>

<!-- Sidebar -->
<div class="sidebar">
    <div class="logo">
        <h5><i class="bi bi-film"></i> <span>Crna Berza</span></h5>
        <button type="button" class="sidebar-collapse-btn" onclick="toggleSidebar()" title="Skupi meni" id="sidebarCollapseBtn"><i class="bi bi-layout-sidebar-inset" id="sidebarChevron"></i></button>
    </div>
    <nav class="nav flex-column">
        <div class="nav-group-label">Upload</div>
        <a class="nav-link active" href="#" data-page="main"><i class="bi bi-house-fill"></i><span>Glavni</span></a>
        <a class="nav-link" href="#" data-page="software"><i class="bi bi-controller"></i><span>Programi / Igrice</span></a>

        <a class="nav-link" href="#" data-page="requests" style="position:relative;display:none"><i class="bi bi-inbox"></i><span>Zahtevi sajta</span><span class="queue-badge" id="requestsBadge" style="display:none">0</span></a>
        <div class="nav-group-label">Alatke</div>
        <a class="nav-link" href="#" data-page="history"><i class="bi bi-clock-history"></i><span>Istorija</span></a>
        <a class="nav-link" href="#" data-page="tools"><i class="bi bi-wrench-adjustable"></i><span>Alati</span></a>
        <div class="nav-group-label">Sistem</div>
        <a class="nav-link" href="#" data-page="settings"><i class="bi bi-gear-fill"></i><span>Podesavanja</span></a>
    </nav>
    <div class="sidebar-footer">v2.0 by Vucko</div>
</div>

<!-- Main Content -->
<div class="main-content">

<!-- PAGE: Main -->
<div id="page-main" class="page active">
    <div class="app-toolbar">
        <div class="app-toolbar-title">
            <i class="bi bi-house-fill"></i> Glavni
            <span class="app-toolbar-sub">IMDB · Screenshots · Torrent · Upload</span>
        </div>
        <div class="app-toolbar-actions">
            <button class="tb-btn" onclick="setTheme(document.body.classList.contains('light')?'dark':'light')" title="Promeni temu"><i class="bi bi-circle-half"></i></button>
        </div>
    </div>

    <div class="workspace-main">
    <div class="card panel-input mb-0" id="dropZone">
        <div class="src-mode-bar">
            <label class="form-label fw-semibold mb-0" style="font-size:12px">Putanja do foldera / video fajla</label>
            <div class="btn-group btn-group-sm" role="group" aria-label="Source mode">
                <input type="radio" class="btn-check" name="srcMode" id="srcLocal" value="local" checked autocomplete="off">
                <label class="btn btn-outline-light btn-sm" for="srcLocal"><i class="bi bi-hdd me-1"></i>Lokalno</label>
                <input type="radio" class="btn-check" name="srcMode" id="srcRemote" value="remote" autocomplete="off">
                <label class="btn btn-outline-light btn-sm" for="srcRemote"><i class="bi bi-cloud me-1"></i>Remote (SFTP)</label>
                <button type="button" class="btn btn-outline-light btn-sm" onclick="showRemoteHelp()" title="Uputstvo za podesavanje servera"><i class="bi bi-info-circle"></i></button>
            </div>
        </div>
        <div id="dropHint" style="display:none;text-align:center;padding:24px;border:1px dashed var(--accent-dim);border-radius:var(--radius-sm);color:var(--accent);font-size:13px;margin-bottom:8px"><i class="bi bi-folder-plus" style="font-size:20px"></i><br>Prevucite folder ovde</div>
        <div class="d-flex gap-2 flex-wrap align-items-stretch">
            <div class="input-group flex-grow-1" style="min-width:280px">
                <input type="text" class="form-control" id="pathInput" placeholder="C:\\Movies\\...">
                <button class="btn btn-outline-light" onclick="browsePathSmart()" style="white-space:nowrap" title="Izaberi folder"><i class="bi bi-folder2-open me-1"></i>Folder</button>
                <button class="btn btn-outline-light" onclick="browseFileSmart()" style="white-space:nowrap" title="Izaberi video fajl"><i class="bi bi-file-earmark-play me-1"></i>Fajl</button>
                <button class="btn btn-accent m-0" onclick="quickUpload()" id="btnQuick" style="border-top-left-radius:0;border-bottom-left-radius:0;padding-left:12px;padding-right:12px;z-index:2" title="Pokreni sve korake odjednom"><i class="bi bi-play-fill me-1"></i>Pokreni</button>
            </div>
        </div>
        <div id="srcRemoteHint" class="alert alert-info mt-2" style="display:none">
            <i class="bi bi-info-circle me-1"></i>Remote rezim: alat ce se ulogovati na SFTP iz Podesavanja, pretraziti fajl i pripremiti torrent na serveru. Server mora imati instalirano <code>ffmpeg</code>, <code>mediainfo</code> i jedan od: <code>mktorrent</code> / <code>transmission-create</code> / <code>torrenttools</code>. <a href="#" onclick="showRemoteHelp();return false" style="color:inherit;text-decoration:underline">Uputstvo za instalaciju &raquo;</a>
        </div>
    </div>

    <div class="card panel-steps mb-0">
        <div class="card-header py-1 px-3" style="font-size:11px"><i class="bi bi-diagram-3 me-1"></i>Tok obrade</div>
        <div class="card-body py-2 px-3">
        <div class="pipeline" id="pipeline">
            <div class="pipe-step" id="pipeImdb" onclick="pipeClick(0)">
                <div class="pipe-circle"><i class="bi bi-film"></i></div>
                <div class="pipe-label">IMDB</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(0)"><i class="bi bi-arrow-counterclockwise"></i>Poništi</div>
            </div>
            <div class="pipe-line" id="pipeLine1"></div>
            <div class="pipe-step locked" id="pipeSs" onclick="pipeClick(1)">
                <div class="pipe-circle"><i class="bi bi-camera"></i></div>
                <div class="pipe-label">Screenshots</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(1)"><i class="bi bi-arrow-counterclockwise"></i>Poništi</div>
            </div>
            <div class="pipe-line" id="pipeLine2"></div>
            <div class="pipe-step locked" id="pipeTorrent" onclick="pipeClick(2)">
                <div class="pipe-circle"><i class="bi bi-magnet-fill"></i></div>
                <div class="pipe-label">Torrent</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(2)"><i class="bi bi-arrow-counterclockwise"></i>Poništi</div>
            </div>
            <div class="pipe-line" id="pipeLine3"></div>
            <div class="pipe-step locked" id="pipeUpload" onclick="pipeClick(3)">
                <div class="pipe-circle"><i class="bi bi-cloud-upload"></i></div>
                <div class="pipe-label">Upload</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(3)"><i class="bi bi-arrow-counterclockwise"></i>Poništi</div>
            </div>
        </div>
        <div class="progress mt-2"><div class="progress-bar" id="progressBar" style="width:0%"></div></div>
        </div>
    </div>

    <div class="card panel-console mb-0 flex-fill">
        <div class="card-header d-flex justify-content-between align-items-center px-3 py-1">
            <span style="font-size:11px"><i class="bi bi-terminal me-1"></i>Konzola</span>
            <div class="d-flex gap-1 align-items-center">
                <div class="log-filters">
                    <button class="btn btn-outline-light btn-sm active-filter" onclick="filterLog('all')" data-filter="all">Sve</button>
                    <button class="btn btn-outline-light btn-sm" onclick="filterLog('info')" data-filter="info">Info</button>
                    <button class="btn btn-outline-light btn-sm" onclick="filterLog('err')" data-filter="err">Greske</button>
                </div>
                <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:10px" onclick="copyLog('logOutput')"><i class="bi bi-clipboard me-1"></i>Kopiraj</button>
                <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:10px" onclick="clearLog()">Obrisi</button>
            </div>
        </div>
        <div class="card-body p-0 d-flex flex-column" style="min-height:0">
            <div class="log-box" id="logOutput"></div>
        </div>
    </div>
    </div>
</div>

<!-- PAGE: Tools -->
<div id="page-tools" class="page">
<div class="page-scroll">
    <div class="page-title"><i class="bi bi-wrench-adjustable-circle"></i> Alati</div>
    <p class="text-muted small mb-3">Program koristi spoljne alate. Klikni 'Preuzmi' za automatsku instalaciju.</p>

    <div class="card mb-3">
        <div class="card-body p-0">
            <table class="tools-table table table-dark table-borderless mb-0 align-middle" style="font-size:13px;table-layout:fixed;width:100%">
                <colgroup>
                    <col style="width:22%">
                    <col style="width:12%">
                    <col>
                    <col style="width:130px">
                </colgroup>
                <thead><tr class="text-muted small"><th class="ps-3">Alat</th><th>Status</th><th>Putanja</th><th class="text-end pe-3">Akcije</th></tr></thead>
                <tbody id="toolsBody"></tbody>
            </table>
        </div>
    </div>

    <div class="d-flex gap-2 mb-3">
        <button class="btn btn-accent btn-sm" onclick="downloadAllTools()"><i class="bi bi-download me-1"></i>Preuzmi SVE</button>
        <button class="btn btn-outline-light btn-sm" onclick="refreshTools()"><i class="bi bi-arrow-clockwise me-1"></i>Osvezi</button>
        <button class="btn btn-outline-light btn-sm" onclick="openToolsDir()"><i class="bi bi-folder me-1"></i>Otvori folder</button>
    </div>

    <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center px-3 py-2">
            <span><i class="bi bi-terminal me-1"></i>Log preuzimanja</span>
            <div class="d-flex gap-1">
                <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:11px" onclick="copyLog('toolsLog')"><i class="bi bi-clipboard me-1"></i>Kopiraj</button>
                <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:11px" onclick="document.getElementById('toolsLog').innerHTML=''">Obrisi</button>
            </div>
        </div>
        <div class="card-body p-0">
            <div class="log-box" id="toolsLog" style="height:180px;border:none;border-radius:0 0 10px 10px"></div>
        </div>
    </div>
</div>
</div>

<!-- PAGE: History -->
<div id="page-history" class="page">
<div class="page-scroll">
    <div class="page-title"><i class="bi bi-clock-history"></i> Istorija uploada</div>

    <!-- Stats -->
    <div class="row g-2 mb-3" id="statsRow">
        <div class="col"><div class="stat-card"><i class="bi bi-cloud-arrow-up-fill stat-ico"></i><div class="stat-val" id="statTotal">0</div><div class="stat-lbl">Ukupno uploada</div></div></div>
        <div class="col"><div class="stat-card"><i class="bi bi-hdd-stack-fill stat-ico"></i><div class="stat-val" id="statSize">0 GB</div><div class="stat-lbl">Ukupna velicina</div></div></div>
        <div class="col"><div class="stat-card"><i class="bi bi-calendar-check-fill stat-ico"></i><div class="stat-val" id="statLast" style="font-size:16px">-</div><div class="stat-lbl">Poslednji upload</div></div></div>

    </div>

    <div class="card mb-3">
        <div class="card-header d-flex justify-content-between align-items-center px-3 py-2">
            <span><i class="bi bi-table me-1"></i>Pregled uploada</span>
            <div class="d-flex gap-1">
                <button class="btn btn-outline-light btn-sm py-0 px-2" style="font-size:11px" onclick="loadHistory()"><i class="bi bi-arrow-clockwise me-1"></i>Osvezi</button>
                <button class="btn btn-outline-light btn-sm py-0 px-2" style="font-size:11px" onclick="exportHistory('json')"><i class="bi bi-filetype-json me-1"></i>JSON</button>
                <button class="btn btn-outline-light btn-sm py-0 px-2" style="font-size:11px" onclick="exportHistory('csv')"><i class="bi bi-filetype-csv me-1"></i>CSV</button>
            </div>
        </div>
        <div class="card-body p-0">
            <table class="table table-dark table-borderless mb-0 align-middle" style="font-size:12px">
                <thead><tr class="text-muted small"><th class="ps-3">#</th><th>Naziv</th><th>Kategorija</th><th>Velicina</th><th>Datum</th><th>Link</th><th>Opis</th><th></th></tr></thead>
                <tbody id="historyBody"><tr><td colspan="8" class="text-center text-muted py-4"><i class="bi bi-inbox" style="font-size:28px;opacity:.4;display:block;margin-bottom:6px"></i>Nema uploada</td></tr></tbody>
            </table>
        </div>
    </div>
</div>
</div>



<!-- PAGE: Software / Programi / Igrice -->
<div id="page-software" class="page">
    <div class="software-page">
    <div class="page-title" style="padding:0 0 6px;margin:0"><i class="bi bi-controller"></i> Programi / Igrice / Muzika</div>
    <p class="text-muted small mb-2" style="font-size:11px">Upload sadrzaja koji nije film ili serija.</p>

    <div class="card mb-2 software-form">
        <div class="sw-source-bar">
            <span class="sw-source-label">Izvor fajlova</span>
            <div class="btn-group btn-group-sm" role="group">
                <input type="radio" class="btn-check" name="swSrcMode" id="swSrcLocal" value="local" checked autocomplete="off">
                <label class="btn btn-outline-light btn-sm" for="swSrcLocal"><i class="bi bi-hdd me-1"></i>Lokalno</label>
                <input type="radio" class="btn-check" name="swSrcMode" id="swSrcRemote" value="remote" autocomplete="off">
                <label class="btn btn-outline-light btn-sm" for="swSrcRemote"><i class="bi bi-cloud me-1"></i>Remote (SFTP)</label>
                <button type="button" class="btn btn-outline-light btn-sm" onclick="showRemoteHelp()"><i class="bi bi-info-circle"></i></button>
            </div>
        </div>
        <div class="row g-2 sw-fields-row">
            <div class="col-md-3 sw-field-col">
                <label class="form-label">ID kategorije <span class="text-danger">*</span></label>
                <div class="input-group input-group-sm">
                    <input type="text" class="form-control" id="swCatId" placeholder="ID" oninput="swUpdateCatLabel()">
                    <button class="btn btn-outline-light" onclick="fetchCatsSw()" title="Lista kategorija sa sajta"><i class="bi bi-list-ul"></i></button>
                </div>
                <div id="swCatLabel" class="form-text text-muted sw-field-hint"></div>
            </div>
            <div class="col-md-9 sw-field-col">
                <label class="form-label">Putanja do foldera / fajla <span class="text-danger">*</span></label>
                <div class="input-group input-group-sm">
                    <input type="text" class="form-control" id="swPath" placeholder="C:\\Games\\Cyberpunk 2077">
                    <button class="btn btn-outline-light" onclick="swBrowseFolderSmart()" title="Folder"><i class="bi bi-folder2-open"></i></button>
                    <button class="btn btn-outline-light" onclick="swBrowseFileSmart()" title="Pojedinacan fajl"><i class="bi bi-file-earmark"></i></button>
                </div>
                <div class="sw-field-hint" aria-hidden="true"></div>
            </div>
        </div>
        <div class="row g-2 mt-2">
            <div class="col-md-9">
                <label class="form-label">Naziv torrenta <span class="text-danger">*</span></label>
                <input type="text" class="form-control form-control-sm" id="swName" placeholder="Cyberpunk.2077.v2.21.PC">
            </div>
            <div class="col-md-3">
                <label class="form-label">Godina</label>
                <input type="text" class="form-control form-control-sm" id="swYear" placeholder="2024">
            </div>
        </div>
        <div class="mt-2">
            <label class="form-label">Opis (BBCode podrzan)</label>
            <textarea class="form-control form-control-sm" id="swDesc" rows="5" placeholder="[b]Cyberpunk 2077[/b]&#10;Verzija: 2.21&#10;Velicina instalacije: 80 GB&#10;..."></textarea>
        </div>
        <div class="row g-2 mt-2">
            <div class="col-md-6">
                <label class="form-label">Slike (opciono, max 10, max 5MB)</label>
                <div class="input-group input-group-sm">
                    <input type="text" class="form-control" id="swImages" readonly placeholder="Nije izabrano nista">
                    <button class="btn btn-outline-light" onclick="swBrowseImages()"><i class="bi bi-images me-1"></i>Izaberi</button>
                    <button class="btn btn-outline-light" onclick="swClearImages()" title="Obrisi izbor"><i class="bi bi-x"></i></button>
                </div>
                <div id="swImagesPreview" class="d-flex flex-wrap gap-1 mt-2"></div>
            </div>
            <div class="col-md-3">
                <label class="form-label">NFO fajl (opciono)</label>
                <div class="input-group input-group-sm">
                    <input type="text" class="form-control" id="swNfo" readonly placeholder="-">
                    <button class="btn btn-outline-light" onclick="swBrowseNfo()"><i class="bi bi-file-earmark-text"></i></button>
                </div>
            </div>
            <div class="col-md-3">
                <label class="form-label">URL (opciono)</label>
                <input type="text" class="form-control form-control-sm" id="swUrl" placeholder="https://...">
            </div>
        </div>
        <div class="row g-2 mt-3 align-items-end">
            <div class="col-md-6">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="swAnon">
                    <label class="form-check-label small" for="swAnon">Anonimni upload</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="swComments" checked>
                    <label class="form-check-label small" for="swComments">Dozvoli komentare</label>
                </div>
            </div>
            <div class="col-md-6 text-end">
                <button class="btn btn-outline-light btn-sm" onclick="swMakeTorrent()" id="swMakeBtn"><i class="bi bi-magnet me-1"></i>1. Kreiraj torrent</button>
                <button class="btn btn-accent btn-sm ms-1" onclick="swDoUpload()" id="swUploadBtn"><i class="bi bi-cloud-upload me-1"></i>2. Upload</button>
            </div>
        </div>
    </div>

    <div class="card mb-0 software-console">
        <div class="card-header d-flex justify-content-between align-items-center px-3 py-1">
            <span style="font-size:11px"><i class="bi bi-terminal me-1"></i>Konzola</span>
            <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:10px" onclick="document.getElementById('swLog').innerHTML=''">Obrisi</button>
        </div>
        <div class="card-body p-0">
            <div class="log-box" id="swLog"></div>
        </div>
    </div>
    </div>
</div>

<!-- PAGE: Requests (queue API from site) -->
<div id="page-requests" class="page">
<div class="page-scroll">
    <div class="page-title"><i class="bi bi-inbox"></i> Zahtevi sajta (red iz API-ja)</div>
    <p class="text-muted small mb-3">Lista zahteva korisnika sajta za skidanje sa servisa (HBO Max, SkyShowtime, EON, Voyo, RTS Planeta, Move).</p>
    <div class="d-flex gap-2 mb-3 flex-wrap align-items-center">
        <div class="btn-group btn-group-sm" role="group">
            <input type="radio" class="btn-check" name="reqStatus" id="reqStPending" value="pending" checked autocomplete="off">
            <label class="btn btn-outline-light btn-sm" for="reqStPending">Na cekanju</label>
            <input type="radio" class="btn-check" name="reqStatus" id="reqStProcessing" value="processing" autocomplete="off">
            <label class="btn btn-outline-light btn-sm" for="reqStProcessing">U toku</label>
            <input type="radio" class="btn-check" name="reqStatus" id="reqStDone" value="done" autocomplete="off">
            <label class="btn btn-outline-light btn-sm" for="reqStDone">Zavrseno</label>
            <input type="radio" class="btn-check" name="reqStatus" id="reqStError" value="error" autocomplete="off">
            <label class="btn btn-outline-light btn-sm" for="reqStError">Greska</label>
            <input type="radio" class="btn-check" name="reqStatus" id="reqStAll" value="all" autocomplete="off">
            <label class="btn btn-outline-light btn-sm" for="reqStAll">Sve</label>
        </div>
        <button class="btn btn-outline-light btn-sm" onclick="loadRequests()"><i class="bi bi-arrow-clockwise me-1"></i>Osvezi</button>
    </div>
    <div class="card">
        <div class="card-body p-0">
            <table class="table table-dark table-borderless mb-0 align-middle" style="font-size:12px">
                <thead><tr class="text-muted small"><th class="ps-3">#</th><th>Tip</th><th>Servis</th><th>URL</th><th>Detalji</th><th>Notes</th><th>Status</th><th>Datum</th><th class="text-end pe-3">Akcije</th></tr></thead>
                <tbody id="requestsBody"><tr><td colspan="9" class="text-center text-muted py-3">Pritisnite "Osvezi"</td></tr></tbody>
            </table>
        </div>
    </div>
</div>
</div>

<!-- PAGE: Settings -->
<div id="page-settings" class="page">
<div class="page-scroll">
    <div class="page-title"><i class="bi bi-gear-fill"></i> Podesavanja</div>

    <div class="card p-4 mb-3">
        <div class="row g-3">
            <div class="col-12">
                <label class="form-label fw-semibold" style="font-size:13px">TMDB API kljuc</label>
                <input type="text" class="form-control" id="cfgTmdb">
                <div class="form-text">themoviedb.org &rarr; Profil &rarr; API &rarr; kopiraj kljuc</div>
            </div>
            <div class="col-12">
                <label class="form-label fw-semibold" style="font-size:13px">Crna Berza API kljuc</label>
                <input type="password" class="form-control" id="cfgCb">
                <div class="form-text">Nalog &rarr; API &rarr; Generisi novi kljuc</div>
            </div>


            <div class="col-12">
                <label class="form-label fw-semibold" style="font-size:13px">Output folder</label>
                <div class="input-group">
                    <input type="text" class="form-control" id="cfgOutput">
                    <button class="btn btn-outline-light" onclick="browseDir('cfgOutput')">...</button>
                </div>
            </div>
            <div class="col-12">
                <label class="form-label fw-semibold" style="font-size:13px">Watch folder (torrent klijent)</label>
                <div class="input-group">
                    <input type="text" class="form-control" id="cfgDownload">
                    <button class="btn btn-outline-light" onclick="browseDir('cfgDownload')">...</button>
                </div>
            </div>
            <div class="col-12">
                <label class="form-label fw-semibold" style="font-size:13px">Announce URL</label>
                <input type="text" class="form-control" id="cfgAnnounce">
            </div>
            <div class="col-md-4">
                <label class="form-label fw-semibold" style="font-size:13px">Broj screenshot-ova</label>
                <input type="number" class="form-control" id="cfgSsCount" min="1" max="20">
            </div>
            <div class="col-12 mt-2">
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="cfgAutoTrailer" checked>
                    <label class="form-check-label" for="cfgAutoTrailer" style="font-size:13px">
                        <i class="bi bi-youtube me-1" style="color:#ff0000"></i>Automatski dodaj YouTube trailer u opis (TMDB upload)
                    </label>
                </div>
                <div class="form-text" style="font-size:11px">Kad je ukljuceno, program trazi official trailer na YouTube-u i ubacuje ga u BBCode opis.</div>
            </div>
            <div class="col-12 mt-3">
                <label class="form-label fw-semibold" style="font-size:13px">Ciscenje fajlova nakon uploada</label>
                <div class="form-check form-switch mb-2">
                    <input class="form-check-input" type="checkbox" id="cfgCleanup">
                    <label class="form-check-label" for="cfgCleanup" style="font-size:13px">Automatski pitaj za brisanje nakon uploada</label>
                </div>
                <div class="ms-3" style="font-size:12px">
                    <div class="form-check"><input class="form-check-input" type="checkbox" id="cfgDelSs" checked><label class="form-check-label" for="cfgDelSs">Brisi screenshots</label></div>
                    <div class="form-check"><input class="form-check-input" type="checkbox" id="cfgDelMi" checked><label class="form-check-label" for="cfgDelMi">Brisi mediainfo.txt</label></div>
                    <div class="form-check"><input class="form-check-input" type="checkbox" id="cfgDelTorrent"><label class="form-check-label" for="cfgDelTorrent">Brisi .torrent fajl</label></div>
                    <div class="form-check"><input class="form-check-input" type="checkbox" id="cfgDelNfo" checked><label class="form-check-label" for="cfgDelNfo">Brisi info.nfo</label></div>
                    <div class="form-check"><input class="form-check-input" type="checkbox" id="cfgDelImdb" checked><label class="form-check-label" for="cfgDelImdb">Brisi imdb.txt</label></div>
                </div>
            </div>
            <div class="col-12 mt-3">
                <label class="form-label fw-semibold" style="font-size:13px"><i class="bi bi-hdd-network me-1"></i>FTP/SFTP - Upload .torrent na server</label>
                <div class="form-check form-switch mb-2">
                    <input class="form-check-input" type="checkbox" id="cfgFtpEnabled">
                    <label class="form-check-label" for="cfgFtpEnabled" style="font-size:13px">Omoguci FTP/SFTP upload .torrent fajla</label>
                </div>
                <div id="ftpSettings" style="display:none">
                    <div class="row g-2 mb-2">
                        <div class="col-md-3">
                            <label class="form-label" style="font-size:12px">Protokol</label>
                            <select class="form-select form-select-sm" id="cfgFtpProto">
                                <option value="sftp">SFTP</option>
                                <option value="ftp">FTP</option>
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label" style="font-size:12px">Host</label>
                            <input type="text" class="form-control form-control-sm" id="cfgFtpHost" placeholder="server.com">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label" style="font-size:12px">Port</label>
                            <input type="number" class="form-control form-control-sm" id="cfgFtpPort" value="22">
                        </div>
                    </div>
                    <div class="row g-2 mb-2">
                        <div class="col-md-6">
                            <label class="form-label" style="font-size:12px">Korisnik</label>
                            <input type="text" class="form-control form-control-sm" id="cfgFtpUser">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label" style="font-size:12px">Lozinka</label>
                            <input type="password" class="form-control form-control-sm" id="cfgFtpPass">
                        </div>
                    </div>
                    <div class="row g-2">
                        <div class="col-12">
                            <label class="form-label" style="font-size:12px">Remote direktorijum (za torrente)</label>
                            <input type="text" class="form-control form-control-sm" id="cfgFtpDir" placeholder="/watch">
                        </div>
                    </div>
                    <div class="row g-2 mt-1">
                        <div class="col-12">
                            <label class="form-label" style="font-size:12px">Remote direktorijum fajlova (za SFTP browser)</label>
                            <input type="text" class="form-control form-control-sm" id="cfgFtpSourceDir" placeholder="/home/user/downloads">
                        </div>
                    </div>
                </div>
            </div>

            <div class="col-12 mt-3">
                <label class="form-label fw-semibold" style="font-size:13px">Tema</label>
                <div class="d-flex gap-2">
                    <button class="btn btn-sm" id="btnThemeDark" onclick="setTheme('dark')"><i class="bi bi-moon-fill me-1"></i>Tamna</button>
                    <button class="btn btn-sm" id="btnThemeLight" onclick="setTheme('light')"><i class="bi bi-sun-fill me-1"></i>Svetla</button>
                </div>
            </div>
            <div class="col-12">
                <button class="btn btn-accent px-4" onclick="saveSettings()"><i class="bi bi-check-lg me-1"></i>Sacuvaj podesavanja</button>
            </div>
        </div>
    </div>
</div>
</div>

<!-- Status Bar -->
<div class="status-bar">
    <span id="statusText"><i class="bi bi-circle-fill status-dot"></i><span id="statusMsg">Spreman</span></span>
    <span class="d-flex align-items-center gap-2">
        <button type="button" id="btnAbortOp" class="btn btn-outline-danger btn-sm py-0 px-2 d-none" onclick="abortUpload()"><i class="bi bi-x-circle me-1"></i>Prekini</button>
        <span id="statusRight">Crna Berza Tools v2.0</span>
    </span>
</div>

<!-- IMDB Modal -->
<div class="modal fade" id="imdbModal" tabindex="-1" data-bs-backdrop="static">
<div class="modal-dialog modal-lg modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header">
        <h6 class="modal-title"><i class="bi bi-film me-2" style="color:var(--accent)"></i>Izaberite sadrzaj</h6>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
    </div>
    <ul class="nav nav-tabs px-3 pt-2" id="imdbTabs" role="tablist" style="border-bottom:1px solid var(--border)">
        <li class="nav-item" role="presentation">
            <button class="nav-link active" id="imdbTabTmdbBtn" data-bs-toggle="tab" data-bs-target="#imdbTabTmdb" type="button" role="tab">
                <i class="bi bi-search me-1"></i>TMDB pretraga
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link" id="imdbTabManualBtn" data-bs-toggle="tab" data-bs-target="#imdbTabManual" type="button" role="tab">
                <i class="bi bi-pencil-square me-1"></i>Rucni unos (bez TMDB)
            </button>
        </li>
    </ul>
    <div class="modal-body">
        <div class="tab-content">
            <div class="tab-pane fade show active" id="imdbTabTmdb" role="tabpanel">
                <div id="imdbBody"></div>
            </div>
            <div class="tab-pane fade" id="imdbTabManual" role="tabpanel">
                <p class="text-muted small mb-2">Za sadrzaj koji nema na TMDB-u (igrice, programi, muzika, stariji/nepoznati filmovi...). Popunite sto vise polja.</p>
                <div class="mb-2">
                    <label class="form-label small mb-1">Tip sadrzaja <span class="text-danger">*</span></label>
                    <select class="form-select form-select-sm" id="manCType">
                        <option value="movie">Film</option>
                        <option value="tv">TV Serija</option>
                        <option value="game">Igrica</option>
                        <option value="software">Program / Softver</option>
                        <option value="music">Muzika</option>
                        <option value="other">Ostalo</option>
                    </select>
                </div>
                <div class="row g-2">
                    <div class="col-md-8">
                        <label class="form-label small mb-1">Naziv <span class="text-danger">*</span></label>
                        <input type="text" class="form-control form-control-sm" id="manTitle" placeholder="npr. Cyberpunk 2077">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small mb-1">Godina</label>
                        <input type="text" class="form-control form-control-sm" id="manYear" placeholder="2020">
                    </div>
                </div>
                <div class="mb-2 mt-2">
                    <label class="form-label small mb-1">Opis (ide u BBCode opis)</label>
                    <textarea class="form-control form-control-sm" id="manOverview" rows="3" placeholder="Kratak opis..."></textarea>
                </div>
                <div class="row g-2">
                    <div class="col-md-6">
                        <label class="form-label small mb-1">IMDB URL (opciono)</label>
                        <input type="text" class="form-control form-control-sm" id="manImdb" placeholder="https://www.imdb.com/title/tt...">
                    </div>
                    <div class="col-md-6">
                        <label class="form-label small mb-1">Poster URL (opciono)</label>
                        <input type="text" class="form-control form-control-sm" id="manPoster" placeholder="https://...">
                    </div>
                </div>
                <div class="row g-2 mt-1">
                    <div class="col-md-8">
                        <label class="form-label small mb-1">Zanrovi (zarezom odvojeno)</label>
                        <input type="text" class="form-control form-control-sm" id="manGenres" placeholder="Akcija, Avantura">
                    </div>
                    <div class="col-md-4 d-flex align-items-end">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="manDomace">
                            <label class="form-check-label small" for="manDomace">Domaci sadrzaj</label>
                        </div>
                    </div>
                </div>
                <div class="alert alert-warning py-2 px-3 mt-3 small mb-2" style="font-size:12px">
                    <i class="bi bi-info-circle me-1"></i>
                    Za igrice/programe/muziku screenshots i MediaInfo ce biti preskoceni ako nema video fajla. Kategoriju izaberite rucno u prozoru za upload (dugme <i class="bi bi-list"></i> pored polja).
                </div>
                <div class="text-end">
                    <button class="btn btn-accent btn-sm" id="manSaveBtn"><i class="bi bi-check-lg me-1"></i>Sacuvaj i nastavi</button>
                </div>
            </div>
        </div>
    </div>
</div></div></div>

<!-- Upload Modal -->
<div class="modal fade" id="uploadModal" tabindex="-1" data-bs-backdrop="static">
<div class="modal-dialog modal-xl modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header" style="border-bottom:none;padding-bottom:0"><h6 class="modal-title"><i class="bi bi-cloud-upload me-2" style="color:var(--accent)"></i>Upload Pregled</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div id="uploadWarningBar" style="display:none;margin:0 16px;padding:10px 16px;background:#dc2626;border-radius:8px;font-size:13px;font-weight:600;color:#fff"><i class="bi bi-exclamation-triangle-fill me-2"></i>UPOZORENJE: Kopirajte opis PRIJE nego sto pritisnete Upload!</div>
    <div class="modal-body" id="uploadBody"></div>
    <div id="uploadDescSection" style="display:none"></div>
    <div class="modal-footer">
        <button class="btn btn-outline-light btn-sm" data-bs-dismiss="modal">Otkazi</button>
        <button class="btn btn-accent px-4" id="btnDoUpload" onclick="doUpload()"><i class="bi bi-cloud-upload me-1"></i>Upload</button>
    </div>
</div></div></div>

<!-- Cleanup Modal -->
<div class="modal fade" id="cleanupModal" tabindex="-1" data-bs-backdrop="static">
<div class="modal-dialog">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-trash3 me-2" style="color:var(--accent)"></i>Ciscenje fajlova</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body" id="cleanupBody"></div>
    <div class="modal-footer">
        <button class="btn btn-outline-light btn-sm" data-bs-dismiss="modal">Preskoci</button>
        <button class="btn btn-outline-light btn-sm" onclick="saveCleanupPrefs()"><i class="bi bi-save me-1"></i>Sacuvaj izbor</button>
        <button class="btn btn-danger btn-sm px-3" onclick="doCleanup()"><i class="bi bi-trash3 me-1"></i>Obrisi izabrano</button>
    </div>
</div></div></div>

<!-- Description Generator Modal -->
<div class="modal fade" id="descModal" tabindex="-1">
<div class="modal-dialog modal-xl">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-file-text me-2" style="color:var(--accent)"></i>Generisani opis (BBCode)</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
        <p style="font-size:12px;color:var(--muted)">Kopirajte ovaj opis i zalepite ga na sajtu. Desna strana prikazuje kako ce izgledati.</p>
        <div class="row g-3">
            <div class="col-6">
                <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;font-weight:600">BBCode</div>
                <textarea id="descOutput" class="form-control" rows="14" style="font-size:12px;font-family:monospace" readonly></textarea>
            </div>
            <div class="col-6">
                <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;font-weight:600">Pregled</div>
                <div id="descPreview" class="desc-preview" style="height:336px"></div>
            </div>
        </div>
    </div>
    <div class="modal-footer">
        <button class="btn btn-outline-light btn-sm" data-bs-dismiss="modal">Zatvori</button>
        <button class="btn btn-accent btn-sm px-3" onclick="copyDesc()"><i class="bi bi-clipboard me-1"></i>Kopiraj</button>
    </div>
</div></div></div>



<!-- Remote SFTP Help / Instructions Modal -->
<div class="modal fade" id="remoteHelpModal" tabindex="-1">
<div class="modal-dialog modal-lg modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header">
        <h6 class="modal-title"><i class="bi bi-cloud me-2" style="color:var(--accent)"></i>Uputstvo: Remote SFTP upload &mdash; instalacija na serveru</h6>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body">
        <div class="alert alert-info mb-3">
            <b>Cemu sluzi?</b> Da ne morate da vucete velike video fajlove na svoj racunar. Alat se SSH-uje na vas server, tamo radi MediaInfo, screenshots i kreira torrent, pa povuce samo te male artefakte (~MB) nazad. Sam video nikad ne prolazi kroz vasu internet vezu.
        </div>

        <div class="help-block">
            <h6><span class="step-num">1</span><i class="bi bi-gear me-1"></i>Podesite SFTP u alatu</h6>
            <ul>
                <li>Idite na <b>Podesavanja &rarr; FTP/SFTP</b></li>
                <li>Cekirajte „Omoguci FTP/SFTP upload" i unesite host, port, korisnika, lozinku</li>
                <li>Protokol mora biti <b>SFTP</b> (ne klasican FTP)</li>
            </ul>
        </div>

        <div class="help-block">
            <h6><span class="step-num">2</span><i class="bi bi-terminal me-1"></i>Instalacija alata na Linux serveru</h6>
            <p style="font-size:12px;color:var(--muted);margin:0 0 6px 0">Ulogujte se na server preko SSH (PuTTY ili <code>ssh user@host</code>) i pokrenite komande prema vasoj distribuciji. Alat za pravljenje torenta moze biti <b>bilo koji od ova tri</b>: <code>mktorrent</code> (najjednostavniji), <code>transmission-create</code> ili <code>torrenttools</code>.</p>

            <p style="font-size:12px;font-weight:600;color:var(--text);margin:8px 0 4px 0">Debian / Ubuntu (preporuceno &mdash; mktorrent):</p>
            <div class="code-block"><button type="button" class="copy-btn" onclick="copyCodeBlock(this)"><i class="bi bi-clipboard"></i>Kopiraj</button><pre>sudo apt update
sudo apt install -y ffmpeg mediainfo mktorrent</pre></div>
            <p style="font-size:11px;color:var(--muted);margin:4px 0 0 0">Alternativa &mdash; transmission paket: <code>sudo apt install -y transmission-cli</code> (komanda <code>transmission-create</code>).</p>

            <p style="font-size:12px;font-weight:600;color:var(--text);margin:10px 0 4px 0">CentOS / Rocky / RHEL:</p>
            <div class="code-block"><button type="button" class="copy-btn" onclick="copyCodeBlock(this)"><i class="bi bi-clipboard"></i>Kopiraj</button><pre>sudo dnf install -y epel-release
sudo dnf install -y ffmpeg mediainfo mktorrent</pre></div>

            <p style="font-size:12px;font-weight:600;color:var(--text);margin:10px 0 4px 0">Arch / Manjaro:</p>
            <div class="code-block"><button type="button" class="copy-btn" onclick="copyCodeBlock(this)"><i class="bi bi-clipboard"></i>Kopiraj</button><pre>sudo pacman -S --noconfirm ffmpeg mediainfo mktorrent</pre></div>

            <details style="margin-top:10px">
                <summary style="cursor:pointer;font-size:12px;color:var(--muted)">torrenttools (build sa GitHub-a) &mdash; ako bas zelite ovaj specificni alat</summary>
                <div class="code-block" style="margin-top:6px"><button type="button" class="copy-btn" onclick="copyCodeBlock(this)"><i class="bi bi-clipboard"></i>Kopiraj</button><pre>sudo apt install -y cmake build-essential git libssl-dev zlib1g-dev libboost-dev libgcrypt20-dev
git clone --recursive https://github.com/fbdtemme/torrenttools.git
cd torrenttools
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
sudo cp build/torrenttools /usr/local/bin/</pre></div>
            </details>
        </div>

        <div class="help-block">
            <h6><span class="step-num">3</span><i class="bi bi-check2-circle me-1"></i>Verifikacija</h6>
            <p style="font-size:12px;color:var(--muted);margin:0 0 6px 0">Nakon instalacije, ffmpeg i mediainfo MORAJU da rade. Za torrent &mdash; bar JEDAN od tri:</p>
            <div class="code-block"><button type="button" class="copy-btn" onclick="copyCodeBlock(this)"><i class="bi bi-clipboard"></i>Kopiraj</button><pre>ffmpeg -version | head -1
ffprobe -version | head -1
mediainfo --Version | head -1
command -v mktorrent && mktorrent -h | head -1 || echo "mktorrent: nema"
command -v transmission-create && echo "transmission-create: ima" || echo "transmission-create: nema"
command -v torrenttools && torrenttools --version || echo "torrenttools: nema"</pre></div>
            <p style="font-size:12px;color:var(--muted);margin:6px 0 0 0">Alat ce automatski izabrati prvi dostupan. Ako ni jedan ne radi (<code>command not found</code>), proverite da je paket instaliran ili dodajte putanju u <code>$PATH</code>.</p>
        </div>

        <div class="help-block">
            <h6><span class="step-num">4</span><i class="bi bi-play-circle me-1"></i>Koriscenje</h6>
            <ul>
                <li>Na glavnom ekranu prebacite toggle u gornjem desnom uglu kartice na <b>Remote (SFTP)</b></li>
                <li>Kliknite <b>Folder</b> ili <b>Fajl</b> &mdash; otvorice se browser SFTP servera</li>
                <li>Izaberite folder/video sa servera, alat ce automatski popuniti polje (<code>sftp://...</code>)</li>
                <li>Pritisnite <b>Brzi Upload</b> &mdash; sve se obradjuje na serveru, samo torrent + screenshots se prebace na vas racunar pre slanja na crnaberza.com</li>
            </ul>
        </div>

        <div class="alert alert-warning">
            <i class="bi bi-exclamation-triangle me-1"></i><b>Performanse:</b> Generisanje 10 screenshot-ova na serveru traje 10-30s u zavisnosti od CPU-a. Ako server nema grafiku, proces moze biti spor &mdash; preporuka je dedikovan VPS sa bar 2 jezgra.
        </div>
    </div>
    <div class="modal-footer">
        <button class="btn btn-accent btn-sm" data-bs-dismiss="modal">U redu</button>
    </div>
</div></div></div>

<!-- Update Available Modal -->
<div class="modal fade" id="updateModal" tabindex="-1">
<div class="modal-dialog modal-sm">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-arrow-up-circle me-2" style="color:var(--accent)"></i>Nova verzija</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body" id="updateBody" style="font-size:13px"></div>
    <div class="modal-footer">
        <button class="btn btn-outline-light btn-sm" data-bs-dismiss="modal">Preskoci</button>
        <a id="updateLink" href="#" target="_blank" class="btn btn-accent btn-sm px-3"><i class="bi bi-download me-1"></i>Preuzmi</a>
    </div>
</div></div></div>

<!-- Category Picker Modal -->
<div class="modal fade" id="catPickerModal" tabindex="-1">
<div class="modal-dialog modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header">
        <h6 class="modal-title"><i class="bi bi-list-ul me-2" style="color:var(--accent)"></i>Izaberi kategoriju</h6>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body">
        <input type="text" class="form-control form-control-sm" id="catPickerSearch" placeholder="Pretraga (naziv ili ID)...">
        <div id="catPickerList" style="max-height:50vh;overflow-y:auto"></div>
    </div>
</div></div></div>

<script src="__BOOTSTRAP_JS__"></script>
<script>
// ─── State ───
let running = false, pollTimer = null, uploadResolve = null;

// ─── Navigation ───
document.querySelectorAll('[data-page]').forEach(el => {
    el.addEventListener('click', e => {
        e.preventDefault();
        const pageId = el.dataset.page;
        const nextPage = document.getElementById('page-' + pageId);
        if (!nextPage || nextPage.classList.contains('active')) return;
        document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
        el.classList.add('active');
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        nextPage.classList.add('active');
        if(pageId==='tools' && window._bridgeReady) refreshTools();
        if(pageId==='requests' && window._bridgeReady) loadRequests();
        if(pageId==='history' && window._bridgeReady){loadHistory();loadStats();}
    });
});

// ─── Drag & Drop visual hint (Python-side handles real drop via DOM API) ───
(function(){
    const dz=document.getElementById('dropZone');
    const hint=document.getElementById('dropHint');
    if(!dz)return;
    function showHint(){hint.style.display='block'}
    function hideHint(){hint.style.display='none'}
    // Use document-level dragenter/leave with relatedTarget to only fire when
    // truly entering/leaving the WINDOW (not crossing child element boundaries).
    document.addEventListener('dragenter',function(e){
        e.preventDefault();
        // Only show when entering from outside the window
        if(!e.relatedTarget) showHint();
    },true);
    document.addEventListener('dragleave',function(e){
        e.preventDefault();
        // Only hide when leaving the window entirely
        if(!e.relatedTarget) hideHint();
    },true);
    document.addEventListener('dragover',function(e){e.preventDefault()},true);
    function loadDroppedPath(path){
        if(!path)return;
        hideHint();
        document.getElementById('pathInput').value=path;
        toast('Detekcija u toku...','info');
        startPolling();
        pywebview.api.check_existing_data(path).then(check=>{
            if(check&&check.loaded_steps&&check.loaded_steps.length>0){
                check.loaded_steps.forEach(s=>{pipeState[s]=2});
                updatePipe();
                toast('Ucitano '+check.loaded_steps.length+' korak(a)','success');
            }else{
                toast('Fajl ucitan: '+path.split(/[\\\\/]/).pop(),'success');
            }
        }).catch(()=>{});
    }
    window.__handleDroppedPath=loadDroppedPath;
    // Direct WebView2 postMessage — bypasses pywebview's slow event serialization.
    document.addEventListener('drop',async function(e){
        e.preventDefault();
        e.stopPropagation();
        hideHint();
        try{
            if(window.chrome && chrome.webview && chrome.webview.postMessageWithAdditionalObjects
               && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length){
                chrome.webview.postMessageWithAdditionalObjects('FilesDropped', e.dataTransfer.files);
            }
        }catch(_){}
        // Quickly poll backend for the captured path (usually arrives within 1-2 ticks)
        for(let i=0;i<40;i++){
            await new Promise(r=>setTimeout(r,25));
            try{
                const path=await pywebview.api.get_dropped_path();
                if(path){loadDroppedPath(path);return}
            }catch(_){}
        }
    },true);
})();

// ─── Helpers ───
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}
function fmtLog(raw){
    var e=esc(raw);
    // Separator lines (═══)
    if(raw.indexOf('\u2550\u2550\u2550')>=0){
        var clean=raw.replace(/[\u2550\\s]+/g,' ').trim();
        return '<div class="log-line log-sep"><i class="bi bi-chevron-double-right"></i><span>'+esc(clean)+'</span></div>';
    }
    // Determine type + icon
    var type='plain',icon='';
    if(raw.indexOf('[ERR]')>=0||raw.indexOf('[ERR ')>=0){type='err';icon='bi-x-circle-fill'}
    else if(raw.indexOf('[OK]')>=0){type='ok';icon='bi-check-circle-fill'}
    else if(raw.indexOf('[WARN]')>=0||raw.indexOf('[WARN ')>=0){type='warn';icon='bi-exclamation-triangle-fill'}
    else if(raw.indexOf('[INFO]')>=0){type='info';icon='bi-info-circle-fill'}
    else if(raw.indexOf('[LOAD]')>=0){type='load';icon='bi-arrow-repeat'}
    else if(raw.indexOf('[UPDATE]')>=0){type='update';icon='bi-arrow-up-circle-fill'}
    else if(raw.indexOf('[DEL]')>=0){type='warn';icon='bi-trash-fill'}
    else if(raw.indexOf('[FALLBACK]')>=0){type='warn';icon='bi-arrow-counterclockwise'}
    else if(raw.indexOf('[FIX]')>=0){type='ok';icon='bi-wrench'}
    else if(raw.indexOf('[DIAG]')>=0){type='info';icon='bi-bug-fill'}
    // Strip the [TAG] marker from displayed text (icon replaces it)
    var disp=e.replace(/\\[(ERR|OK|WARN|INFO|LOAD|UPDATE|DEL|FALLBACK|FIX|DIAG)\\]\\s*/,'');
    var iconHtml=icon?'<i class="bi '+icon+' log-ico log-'+type+'"></i>':'<i class="bi bi-dot log-ico log-plain"></i>';
    var ts=new Date().toLocaleTimeString('sr-RS',{hour12:false});
    return '<div class="log-line log-'+type+'" data-raw="'+e+'">'+
           '<span class="log-time">'+ts+'</span>'+
           iconHtml+
           '<span class="log-msg">'+disp+'</span>'+
           '<button class="log-copy" onclick="copyLogLine(this)" title="Kopiraj red"><i class="bi bi-clipboard"></i></button>'+
           '</div>';
}
function copyLogLine(btn){
    var line=btn.closest('.log-line');
    var raw=line?(line.getAttribute('data-raw')||line.querySelector('.log-msg').textContent):'';
    // decode HTML entities
    var ta=document.createElement('textarea');ta.innerHTML=raw;var txt=ta.value;
    function done(ok){
        if(ok){var ic=btn.querySelector('i');if(ic){ic.className='bi bi-check2'};setTimeout(function(){var i2=btn.querySelector('i');if(i2)i2.className='bi bi-clipboard'},1500);toast('Red kopiran','success')}
        else toast('Greska pri kopiranju','error');
    }
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(function(){done(true)},function(){pywebview.api.copy_to_clipboard(txt).then(done)})}
    else{pywebview.api.copy_to_clipboard(txt).then(done)}
}
async function copyLog(id){
    var el=document.getElementById(id);
    var lines=[].slice.call(el.querySelectorAll('.log-line')).map(function(l){var m=l.querySelector('.log-msg');return m?m.textContent:l.textContent});
    var txt=lines.join('\\n')||el.innerText||el.textContent;
    try{await pywebview.api.copy_to_clipboard(txt);toast('Ceo log kopiran!','success')}catch(ex){toast('Greska pri kopiranju','error')}
}
function clearLog(){document.getElementById('logOutput').innerHTML='';logAllLines=[]}
var logAllLines=[];
var logFilter='all';
function filterLog(f){
    logFilter=f;
    document.querySelectorAll('.log-filters .btn').forEach(b=>b.classList.toggle('active-filter',b.dataset.filter===f));
    var el=document.getElementById('logOutput');
    var lines=logAllLines;
    if(f==='err') lines=lines.filter(function(l){return l.indexOf('[ERR]')>=0});
    else if(f==='info') lines=lines.filter(function(l){return l.indexOf('[ERR]')<0});
    el.innerHTML=lines.map(function(l){return fmtLog(l)}).join('');
    el.scrollTop=el.scrollHeight;
}
function setBtns(dis){running=dis}
function toast(msg,type,dur){type=type||'info';dur=dur||4000;var w=document.getElementById('toastWrap');var icons={success:'bi-check-circle-fill',error:'bi-exclamation-circle-fill',info:'bi-info-circle-fill'};var el=document.createElement('div');el.className='app-toast '+type;el.innerHTML='<i class="bi '+icons[type]+'"></i><span>'+esc(msg)+'</span>';w.appendChild(el);setTimeout(function(){el.classList.add('out');setTimeout(function(){el.remove()},300)},dur)}
var STEPS=['imdb','screenshots','torrent','upload'];
var STEP_IDS=['pipeImdb','pipeSs','pipeTorrent','pipeUpload'];
var LINE_IDS=['pipeLine1','pipeLine2','pipeLine3'];
var pipeState=[0,0,0,0];
var _remoteProcessed=false;
function updatePipe(){
    STEP_IDS.forEach(function(id,i){
        var el=document.getElementById(id);if(!el)return;
        el.classList.remove('done','active','locked');
        if(pipeState[i]===2)el.classList.add('done');
        else if(pipeState[i]===1)el.classList.add('active');
        else if(i>0&&pipeState[i-1]!==2)el.classList.add('locked');
    });
    LINE_IDS.forEach(function(id,i){
        var el=document.getElementById(id);if(!el)return;
        if(pipeState[i]===2)el.classList.add('filled');else el.classList.remove('filled');
    });
}
function pipeClick(idx){
    if(running)return;
    if(pipeState[idx]===2){toast('Ovaj korak je vec zavrsen. Klikni "ponisti" za ponovni rad.','info');return}
    if(idx>0&&pipeState[idx-1]!==2){toast('Zavrsi prethodni korak prvo!','error');return}
    runStep(STEPS[idx]);
}
async function undoStep(idx){
    if(running)return;
    if(pipeState[idx]!==2)return;
    for(var i=3;i>=idx;i--){pipeState[i]=0}
    if(idx<=1)_remoteProcessed=false;
    updatePipe();
    await pywebview.api.reset_from_step(idx);
    toast('Ponisteno od koraka '+(idx+1),'info');
    document.getElementById('progressBar').style.width='0%';
}

// ─── Polling ───
function startPolling(){
    if(pollTimer)return;
    pollTimer=setInterval(async()=>{
        try{
            const u=await pywebview.api.get_updates();
            if(u.logs&&u.logs.length){const el=document.getElementById('logOutput');u.logs.forEach(m=>{logAllLines.push(m);if(logFilter==='all'||(logFilter==='err'&&m.indexOf('[ERR]')>=0)||(logFilter==='info'&&m.indexOf('[ERR]')<0)){el.innerHTML+=fmtLog(m)}});el.scrollTop=el.scrollHeight}
            if(u.tool_logs&&u.tool_logs.length){const el=document.getElementById('toolsLog');u.tool_logs.forEach(m=>{el.innerHTML+=fmtLog(m)});el.scrollTop=el.scrollHeight}
            const pb=document.getElementById('progressBar');
            if(u.progress<0){pb.style.width='100%';pb.className='progress-bar progress-bar-striped progress-bar-animated'}
            else{pb.style.width=u.progress+'%';pb.className='progress-bar'}
            document.getElementById('statusMsg').textContent=u.status;
        }catch(e){}
    },250);
}

// ─── Browse ───
async function browsePath(){
    const r=await pywebview.api.browse_folder();
    if(!r)return;
    document.getElementById('pathInput').value=r;
    // Check for existing data
    startPolling();
    const check=await pywebview.api.check_existing_data(r);
    if(check&&check.loaded_steps&&check.loaded_steps.length>0){
        check.loaded_steps.forEach(s=>{pipeState[s]=2});
        updatePipe();
        toast('Ucitano '+check.loaded_steps.length+' korak(a) iz prethodnog rada','success');
    }
}
async function browseDir(id){const r=await pywebview.api.browse_folder();if(r)document.getElementById(id).value=r}
async function browseFile(){
    const r=await pywebview.api.browse_main_video_file();
    if(!r)return;
    document.getElementById('pathInput').value=r;
    startPolling();
    const check=await pywebview.api.check_existing_data(r);
    if(check&&check.loaded_steps&&check.loaded_steps.length>0){
        check.loaded_steps.forEach(s=>{pipeState[s]=2});
        updatePipe();
        toast('Ucitano '+check.loaded_steps.length+' korak(a) iz prethodnog rada','success');
    }
}

// Smart browse: picks SFTP browser when remote mode is on
function _isRemoteMode(){var el=document.getElementById('srcRemote');return !!(el&&el.checked)}
async function browsePathSmart(){if(_isRemoteMode())return await browseRemote('folder');return await browsePath()}
async function browseFileSmart(){if(_isRemoteMode())return await browseRemote('file');return await browseFile()}

async function browseRemote(mode){
    // mode: 'folder' or 'file'
    const cfg=await pywebview.api.get_config();
    if(!cfg||!cfg.ftp_host||!cfg.ftp_user){
        toast('Podesite SFTP podatke u Podesavanjima!','error');
        return;
    }
    const startDir=cfg.ftp_source_dir||'/';
    const picked=await showRemoteBrowser(startDir,mode);
    if(picked){
        document.getElementById('pathInput').value='sftp://'+picked;
        _remoteProcessed=false;
        pipeState=[0,0,0,0];updatePipe();
        toast('Remote izbor: '+picked,'info');
    }
}

// Remote SFTP browser modal (dynamically created)
function showRemoteBrowser(startDir,mode){
    return new Promise(resolve=>{
        let cur=startDir;
        // Create modal element on the fly
        let m=document.getElementById('remoteBrowserModal');
        if(m)m.remove();
        m=document.createElement('div');
        m.id='remoteBrowserModal';
        m.className='modal fade';
        m.tabIndex=-1;
        m.innerHTML=`<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content">
            <div class="modal-header"><h6 class="modal-title"><i class="bi bi-cloud me-2"></i>Remote SFTP browser (${mode==='folder'?'izbor foldera':'izbor fajla'})</h6>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
            <div class="modal-body">
                <div class="input-group input-group-sm mb-2">
                    <span class="input-group-text">Putanja</span>
                    <input type="text" class="form-control" id="rbPath" value="${esc(cur)}">
                    <button class="btn btn-outline-light" id="rbGo"><i class="bi bi-arrow-right"></i></button>
                    <button class="btn btn-outline-light" id="rbUp" title="Na gore"><i class="bi bi-arrow-up"></i></button>
                </div>
                <div id="rbList" style="max-height:400px;overflow-y:auto;font-size:12px"></div>
                <div class="text-end mt-2">
                    ${mode==='folder'?'<button class="btn btn-accent btn-sm" id="rbSelect"><i class="bi bi-check2 me-1"></i>Izaberi ovaj folder</button>':''}
                </div>
            </div>
        </div></div>`;
        document.body.appendChild(m);
        const modal=new bootstrap.Modal(m);
        let resolved=false;
        const finish=v=>{resolved=true;modal.hide();resolve(v)};
        m.addEventListener('hidden.bs.modal',()=>{if(!resolved)resolve(null);m.remove()},{once:true});

        async function refresh(p){
            cur=p;
            document.getElementById('rbPath').value=p;
            const list=document.getElementById('rbList');
            list.innerHTML='<div class="text-muted text-center py-3"><i class="bi bi-hourglass-split me-1"></i>Ucitavam...</div>';
            try{
                const r=await pywebview.api.sftp_list(p);
                if(!r||!r.ok){list.innerHTML='<div class="text-danger py-2">Greska: '+esc((r&&r.error)||'nepoznata')+'</div>';return}
                let html='';
                r.entries.forEach(e=>{
                    const icon=e.dir?'<i class="bi bi-folder2 text-warning me-2"></i>':'<i class="bi bi-file-earmark me-2 text-muted"></i>';
                    const size=e.dir?'':' <span class="text-muted small">('+(e.size>1073741824?(e.size/1073741824).toFixed(1)+' GB':e.size>1048576?(e.size/1048576).toFixed(1)+' MB':(e.size/1024).toFixed(0)+' KB')+')</span>';
                    const action=e.dir?`onclick="document.getElementById('rbPath').value='${esc(e.path)}';document.getElementById('rbGo').click()"`:(mode==='file'?`onclick="window._rbPick('${esc(e.path)}')"`:'');
                    html+=`<div class="d-flex align-items-center px-2 py-1 border-bottom" style="border-color:var(--border)!important;cursor:${e.dir||mode==='file'?'pointer':'default'}" ${action}>${icon}<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(e.name)}</span>${size}</div>`;
                });
                if(!r.entries.length)html='<div class="text-muted py-2 text-center">(Prazno)</div>';
                list.innerHTML=html;
            }catch(e){list.innerHTML='<div class="text-danger py-2">'+esc(e.toString())+'</div>'}
        }
        window._rbPick=p=>finish(p);
        document.getElementById('rbGo').addEventListener('click',()=>refresh(document.getElementById('rbPath').value));
        document.getElementById('rbUp').addEventListener('click',()=>{const p=cur.replace(/\\/+$/,'').split('/').slice(0,-1).join('/')||'/';refresh(p)});
        if(mode==='folder'){
            const sb=document.getElementById('rbSelect');
            if(sb)sb.addEventListener('click',()=>finish(cur));
        }
        modal.show();
        refresh(cur);
    });
}

// ─── Actions ───
function _isRemotePath(p){return typeof p==='string'&&p.indexOf('sftp://')===0}
function _stripRemote(p){return _isRemotePath(p)?p.substring(7):p}

async function runStep(step){
    const path=document.getElementById('pathInput').value.trim();
    if(!path&&step!=='upload'){toast('Unesite putanju!','error');return}
    const si={imdb:0,screenshots:1,torrent:2,upload:3};
    var idx=si[step];
    pipeState[idx]=1;updatePipe();
    document.getElementById('progressBar').style.width='0%';
    document.getElementById('progressBar').className='progress-bar';
    setBtns(true);startPolling();
    try{
        const remote=_isRemotePath(path);
        const rp=_stripRemote(path);
        if(step==='imdb'){
            // For remote we don't have local folder, use the basename
            const r=await pywebview.api.search_imdb(remote?rp:path);
            const pick=await showImdbModal((r&&r.results)||[]);
            if(pick===null)throw 'Korak otkazan';
            const ok1=await applyImdbChoice(pick);
            if(!ok1)throw 'Nije sacuvano';
        }
        else if(step==='screenshots'){
            if(remote){
                // Remote obrada radi screenshots I torrent zajedno (na serveru).
                // Ako vec uradjeno (torrent korak), ne ponavljaj.
                if(!_remoteProcessed){
                    const r=await pywebview.api.sftp_run_remote(rp);
                    if(!r||!r.ok)throw 'Remote obrada neuspesno: '+((r&&r.error)||'');
                    _remoteProcessed=true;
                }
            }else{
                const r=await pywebview.api.run_screenshots(path);
                if(!r||!r.ok)throw 'Screenshots neuspesno';
            }
        }
        else if(step==='torrent'){
            if(remote){
                // Remote: torrent je vec napravljen u screenshots koraku ako je radjen.
                if(!_remoteProcessed){
                    const r=await pywebview.api.sftp_run_remote(rp);
                    if(!r||!r.ok)throw 'Remote obrada neuspesno: '+((r&&r.error)||'');
                    _remoteProcessed=true;
                }
            }else{
                const r=await pywebview.api.run_torrent(path);
                if(!r||!r.ok)throw 'Torrent neuspesno';
            }
        }
        else if(step==='upload'){const ud=await pywebview.api.get_upload_data();if(ud)await showUploadModal(ud)}
        pipeState[idx]=2;
        toast(step.charAt(0).toUpperCase()+step.slice(1)+' zavrseno!','success');
    }catch(e){console.error(e);pipeState[idx]=0;toast('Greska: '+step,'error')}
    updatePipe();setBtns(false);
}

// ─── IMDB Modal ───
// resolve payload:
//   {type:'tmdb', index:<i>}   - user picked TMDB result
//   {type:'manual', data:{...}} - user entered manual metadata
//   null                        - user cancelled
function showImdbModal(results){
    return new Promise(resolve=>{
        // Reset na TMDB tab pri svakom otvaranju
        try{var tt=new bootstrap.Tab(document.getElementById('imdbTabTmdbBtn'));tt.show()}catch(e){}
        const body=document.getElementById('imdbBody');
        body.innerHTML='';
        // Manual search bar
        const searchBar=document.createElement('div');
        searchBar.className='input-group mb-3';
        searchBar.innerHTML='<input type="text" class="form-control" id="imdbManualSearch" placeholder="Rucna pretraga (npr. Nobody Likes Me 2025)">'+'<button class="btn btn-accent" id="imdbSearchBtn"><i class="bi bi-search me-1"></i>Trazi</button>';
        body.appendChild(searchBar);
        const hintDiv=document.createElement('div');
        hintDiv.className='small text-muted mb-2';
        hintDiv.innerHTML='Ne vidite vas sadrzaj? Otvorite tab <b>Rucni unos (bez TMDB)</b> iznad.';
        body.appendChild(hintDiv);
        const listDiv=document.createElement('div');
        listDiv.id='imdbResultsList';
        body.appendChild(listDiv);
        function renderResults(res){
            listDiv.innerHTML='';
            if(!res||!res.length){listDiv.innerHTML='<p class="text-muted text-center">Nema rezultata. Pokusajte rucnu pretragu ili predjite na tab <b>Rucni unos</b>.</p>';return}
            res.forEach((item,i)=>{
                const t=item.title||item.name||'Nepoznato';
                const ot=item.original_title||item.original_name||'';
                const d=item.release_date||item.first_air_date||'';
                const yr=d.substring(0,4)||'????';
                const r=(item.vote_average||0).toFixed(1);
                const v=item.vote_count||0;
                const tp=item.media_type==='tv'?'TV Serija':'Film';
                const lang=(item.original_language||'?').toUpperCase();
                const ov=(item.overview||'').substring(0,200);
                const stars='\\u2605'.repeat(Math.min(Math.round((item.vote_average||0)/2),5));
                const poster=item.poster_path?`<img src="https://image.tmdb.org/t/p/w185${item.poster_path}" class="poster-img me-3" alt="" onerror="this.outerHTML='<div class=poster-ph><i class=bi bi-film fs-3 text-muted></i></div>'">`:'<div class="poster-ph me-3"><i class="bi bi-film fs-3 text-muted"></i></div>';
                const card=document.createElement('div');
                card.className='imdb-card d-flex p-3 mb-2';
                card.innerHTML=`${poster}<div class="flex-grow-1"><h6 class="mb-1">${esc(t)} <span class="text-muted">(${yr})</span></h6>${ot&&ot!==t?`<small class="text-muted d-block">${esc(ot)}</small>`:''}<small class="fw-bold" style="color:var(--accent)">${stars} ${r}/10 (${v}) &nbsp;|&nbsp; ${tp} &nbsp;|&nbsp; ${lang}</small>${ov?`<p class="text-muted small mt-1 mb-0">${esc(ov)}${(item.overview||'').length>200?'...':''}</p>`:''}</div><div class="d-flex align-items-center ms-2"><button class="btn btn-accent btn-sm px-3">Izaberi</button></div>`;
                card.querySelector('button').addEventListener('click',()=>{finishPick({type:'tmdb',index:i})});
                listDiv.appendChild(card);
            });
        }
        renderResults(results);
        document.getElementById('imdbSearchBtn').addEventListener('click',async()=>{
            const q=document.getElementById('imdbManualSearch').value.trim();
            if(!q)return;
            listDiv.innerHTML='<p class="text-muted text-center"><i class="bi bi-hourglass-split me-1"></i>Trazim...</p>';
            try{
                const r2=await pywebview.api.search_imdb_manual(q);
                renderResults(r2.results);
            }catch(e){listDiv.innerHTML='<p class="text-danger">Greska: '+esc(e.toString())+'</p>'}
        });
        document.getElementById('imdbManualSearch').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();document.getElementById('imdbSearchBtn').click()}});

        // Pre-fill manual entry with folder/file name ako je moguce
        try{
            const pathVal=(document.getElementById('pathInput').value||'').trim();
            if(pathVal){
                const base=pathVal.split(/[\\\\/]/).pop()||'';
                const noExt=base.replace(/\\.[^.]+$/,'');
                const cleaned=noExt.replace(/\\./g,' ').replace(/\\s+/g,' ').trim();
                const mTitle=document.getElementById('manTitle');
                if(mTitle&&!mTitle.value)mTitle.value=cleaned;
                const ym=cleaned.match(/(19|20)\\d{2}/);
                const mYear=document.getElementById('manYear');
                if(ym&&mYear&&!mYear.value)mYear.value=ym[0];
            }
        }catch(e){}

        // Manual save handler
        const saveBtn=document.getElementById('manSaveBtn');
        const saveHandler=async()=>{
            const ct=document.getElementById('manCType').value;
            const title=document.getElementById('manTitle').value.trim();
            const year=document.getElementById('manYear').value.trim();
            const overview=document.getElementById('manOverview').value.trim();
            const imdb=document.getElementById('manImdb').value.trim();
            const poster=document.getElementById('manPoster').value.trim();
            const genres=document.getElementById('manGenres').value.trim();
            const dom=document.getElementById('manDomace').checked;
            if(!title){toast('Unesite naziv sadrzaja!','error');return}
            const data={content_type:ct,title:title,year:year,overview:overview,imdb_url:imdb,poster_url:poster,genres:genres,is_domace:dom};
            finishPick({type:'manual',data:data});
        };
        saveBtn.onclick=saveHandler;

        const modalEl=document.getElementById('imdbModal');
        const modal=new bootstrap.Modal(modalEl);
        let resolved=false;
        function finishPick(v){resolved=true;modal.hide();resolve(v)}
        modalEl.addEventListener('hidden.bs.modal',()=>{if(!resolved)resolve(null)},{once:true});
        modal.show();
    });
}

// Helper koji prosledjuje izbor odgovarajucem API pozivu
async function applyImdbChoice(choice){
    if(!choice)return false;
    if(choice.type==='tmdb'){await pywebview.api.confirm_imdb(choice.index);return true}
    if(choice.type==='manual'){const r=await pywebview.api.save_manual_metadata(choice.data);return !!(r&&r.ok)}
    return false;
}

// ─── Upload Modal ───
function showUploadModal(data){
    return new Promise(async resolve=>{
        const body=document.getElementById('uploadBody');
        const tip=data.is_tv?'TV Serija':'Film';
        const por=data.is_domace?'Domaće':'Strano';
        const kval=data.is_hd?'HD':'SD';
        const mi=data.parsed_mediainfo;

        let miHtml='';
        if(mi){
            miHtml='<div class="preview-section"><div class="preview-header"><i class="bi bi-info-circle"></i> MEDIAINFO</div><div class="mi-grid">';
            miHtml+='<div><div class="mi-title">GENERAL</div><table class="mi-tbl"><tbody>';
            for(let[k,v] of Object.entries(mi.general||{})){miHtml+=`<tr><td class="mk">${esc(k)}</td><td class="mv"><strong>${esc(v)}</strong></td></tr>`;}
            miHtml+='</tbody></table></div>';
            miHtml+='<div><div class="mi-title">VIDEO</div><table class="mi-tbl"><tbody>';
            for(let[k,v] of Object.entries(mi.video||{})){miHtml+=`<tr><td class="mk">${esc(k)}</td><td class="mv"><strong>${esc(v)}</strong></td></tr>`;}
            miHtml+='</tbody></table></div>';
            miHtml+='<div><div class="mi-title">AUDIO</div><table class="mi-tbl"><tbody>';
            (mi.audio||[]).forEach((a,i)=>{const p=[];if(a.Language)p.push(a.Language);if(a.Format)p.push(a.Format);if(a.Channels)p.push(a.Channels);if(a.Bitrate)p.push(a.Bitrate);miHtml+=`<tr><td class="mk">${i+1}.</td><td class="mv">${esc(p.join(' / '))}</td></tr>`;});
            miHtml+='</tbody></table></div></div>';
            if(mi.subtitles&&mi.subtitles.length){
                miHtml+='<div style="padding:12px 16px;border-top:1px solid var(--border)"><div class="mi-title">SUBTITLES</div><div class="d-flex flex-wrap gap-1">';
                mi.subtitles.forEach(s=>{miHtml+=`<span class="sub-tag">${esc(s)}</span>`;});
                miHtml+='</div></div>';
            }
            miHtml+='</div>';
        }

        let ssHtml='';
        if(data.screenshot_count>0){
            try{const thumbs=await pywebview.api.get_screenshot_thumbnails();
            if(thumbs&&thumbs.length){
                ssHtml='<div class="preview-section"><div class="preview-header"><i class="bi bi-images"></i> SCREENSHOTS <span style="color:var(--muted);font-weight:400;text-transform:none;margin-left:4px">('+data.screenshot_count+')</span></div><div class="preview-body"><div class="ss-row">';
                thumbs.forEach(t=>{if(t)ssHtml+=`<img src="${t}">`;});
                ssHtml+='</div></div></div>';
            }}catch(e){}
        }

        const posterHtml=data.poster_url
            ?`<img src="${data.poster_url}" style="width:100%;border-radius:8px;box-shadow:0 4px 15px rgba(0,0,0,0.4)">`
            :'<div style="width:100%;padding-top:150%;background:var(--bg3);border-radius:8px;position:relative"><i class="bi bi-film" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:36px;color:var(--muted)"></i></div>';

        const imdbId=(data.imdb_url||'').match(/tt\\d+/);
        const imdbHtml=imdbId
            ?`<a class="imdb-link" href="#" onclick="return false"><i class="bi bi-star-fill me-1"></i>${imdbId[0]}</a>`
            :'<span style="color:var(--muted)">\u2014</span>';

        const titleText=data.tmdb_title?esc(data.tmdb_title)+(data.tmdb_year?' ('+data.tmdb_year+')':''):'';

        const flagImg={
            'sr':'https://flagcdn.com/20x15/rs.png','hr':'https://flagcdn.com/20x15/hr.png',
            'ba':'https://flagcdn.com/20x15/ba.png'
        };
        const SUB_LANGS=[
            {code:'sr',name:'Srpski'},{code:'hr',name:'Hrvatski'},{code:'ba',name:'Bosanski'}
        ];
        const detectedSubs=Array.isArray(data.subtitles)?data.subtitles.map(s=>s.toLowerCase()).filter(c=>['sr','hr','ba'].indexOf(c)>=0):[];
        const subsHtml='<div id="upSubsChips" class="d-flex flex-wrap gap-1" style="max-width:520px">'+
            SUB_LANGS.map(l=>{
                const active=detectedSubs.indexOf(l.code)>=0;
                return `<span class="sub-chip ${active?'active':''}" data-code="${l.code}" onclick="toggleSubChip(this)" title="${esc(l.name)}"><img src="${flagImg[l.code]}" alt="${l.code}">${l.code.toUpperCase()}</span>`;
            }).join('')+'</div>'+
            (detectedSubs.length===0?'<div class="small text-muted mt-1" style="font-size:11px"><i class="bi bi-info-circle me-1"></i>Auto-detekcija nije nasla titlove. Kliknite jezike koje hocete da prijavite uz upload.</div>':'<div class="small text-muted mt-1" style="font-size:11px"><i class="bi bi-info-circle me-1"></i>Detektovano. Mozete dodati/ukloniti jezike klikom na cipove.</div>');

        const genresHtml=(data.tmdb_genres&&data.tmdb_genres.length)
            ?data.tmdb_genres.map(g=>`<span class="genre-badge">${esc(g)}</span>`).join('')
            :'<span style="color:var(--muted)">\u2014</span>';

        const now=new Date();
        const months=['January','February','March','April','May','June','July','August','September','October','November','December'];
        const h=now.getHours()%12||12,m=String(now.getMinutes()).padStart(2,'0'),ap=now.getHours()>=12?'pm':'am';
        const dateStr=`${months[now.getMonth()]} ${now.getDate()}, ${now.getFullYear()} at ${h}:${m} ${ap}`;

        body.innerHTML=`
        <div class="preview-section"><div class="preview-body"><div class="d-flex gap-4">
            <div style="width:180px;flex-shrink:0">${posterHtml}</div>
            <div class="flex-grow-1">
                <table class="info-tbl">
                <tr><td class="il">Kategorija:</td><td class="iv"><span class="cat-badge">${esc(data.category_name)}</span>
                    <input type="text" class="form-control form-control-sm d-inline-block ms-2" id="upCatId" value="${data.category_id}" style="width:60px;font-size:11px;padding:2px 6px;vertical-align:middle">
                    <button class="btn btn-outline-light btn-sm ms-1 py-0 px-2" style="font-size:10px" onclick="fetchCats()">&#9776;</button>
                    <div id="catInfo" style="font-size:10px;color:var(--muted);margin-top:4px">${data.is_manual&&!data.category_id?'<span style="color:#F59E0B"><i class=\"bi bi-exclamation-triangle me-1\"></i>Unesite ID kategorije rucno (kliknite &#9776; za listu)</span>':''}</div></td></tr>
                <tr><td class="il">Dodato:</td><td class="iv" style="color:var(--accent)">${dateStr}</td></tr>
                <tr><td class="il">Titlovi:</td><td class="iv">${subsHtml}</td></tr>
                <tr><td class="il">Zanrovi:</td><td class="iv">${genresHtml}</td></tr>
                <tr><td class="il">IMDB:</td><td class="iv">${imdbHtml}</td></tr>
                </table>
                <div class="mt-2"><div class="form-check"><input class="form-check-input" type="checkbox" id="upAnon"><label class="form-check-label" for="upAnon" style="font-size:12px;color:var(--muted)">Anonimni upload</label></div></div>
            </div>
        </div></div></div>
        <div class="preview-section"><div class="preview-header"><i class="bi bi-text-left"></i> TORRENT INFO</div><div class="preview-body">
            <div class="mb-2"><label class="d-block mb-1" style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em;font-weight:600">Naziv torrenta</label>
            <input type="text" class="form-control" id="upName" value="${esc(data.auto_name)}"></div>
        </div></div>
        <div id="descPreviewSection" style="display:none">
            <div class="preview-section"><div class="preview-header"><i class="bi bi-file-earmark-text"></i> OPIS ZA SAJT (automatski se salje preko API-ja)
            </div><div class="preview-body" style="padding:0">
                <div id="uploadDescPreview" class="desc-preview" style="max-height:200px;border:none;border-radius:0;padding:16px;margin:0"></div>
                <textarea id="uploadDescOutput" style="display:none"></textarea>
            </div></div>
        </div>
        ${miHtml}
        ${ssHtml}`;

        // Generate description preview
        async function refreshUploadDesc(){
            try{
                const desc=await pywebview.api.generate_description('');
                if(desc && desc!=='.'){
                    document.getElementById('uploadDescOutput').value=desc;
                    document.getElementById('uploadDescPreview').innerHTML=bbcodeToHtml(desc);
                    document.getElementById('descPreviewSection').style.display='block';
                }else{
                    document.getElementById('descPreviewSection').style.display='none';
                }
            }catch(e){document.getElementById('descPreviewSection').style.display='none';}
        }
        await refreshUploadDesc();

        uploadResolve=resolve;
        const modalEl=document.getElementById('uploadModal');
        const modal=new bootstrap.Modal(modalEl);
        modalEl.addEventListener('hidden.bs.modal',()=>{uploadResolve=null;resolve()},{once:true});
        modal.show();
    });
}

async function doUpload(){
    const cat=document.getElementById('upCatId').value.trim();
    const name=document.getElementById('upName').value.trim();
    const anon=document.getElementById('upAnon').checked;
    const subsArr=[];
    document.querySelectorAll('#upSubsChips .sub-chip.active').forEach(el=>{
        const c=el.getAttribute('data-code');
        if(c)subsArr.push(c);
    });
    if(!cat||!name){toast('Unesite kategoriju i naziv!','error');return}
    const modal=bootstrap.Modal.getInstance(document.getElementById('uploadModal'));
    if(modal)modal.hide();
    const abortBtn=document.getElementById('btnAbortOp');
    if(abortBtn)abortBtn.classList.remove('d-none');
    let uploadOk=false;
    try{
        await pywebview.api.do_upload(parseInt(cat),name,'',anon,false,'',subsArr);
        uploadOk=true;
    }catch(e){
        console.error(e);
        if(e&&String(e).includes('otkazan')){
            toast('Upload prekinut','warning');
        }else{
            const retry=confirm('Upload nije uspeo! Pokusati ponovo?');
            if(retry){
                try{await pywebview.api.do_upload(parseInt(cat),name,'',anon,false,'',subsArr);uploadOk=true}catch(e2){toast('Upload neuspesan nakon ponovnog pokusaja','error')}
            }else{toast('Upload otkazan','error')}
        }
    }finally{
        if(abortBtn)abortBtn.classList.add('d-none');
    }
    if(uploadResolve){uploadResolve();uploadResolve=null}
    if(uploadOk){
        await showCleanupModal();
        await loadHistory();
        await loadStats();
    }
}
async function abortUpload(){
    try{await pywebview.api.cancel_operation()}catch(e){}
    toast('Prekid uploada...','warning');
}

function toggleSubChip(el){el.classList.toggle('active')}

// ─── Quick Upload ───
async function quickUpload(){
    const path=document.getElementById('pathInput').value.trim();
    if(!path){
        const remoteMode=_isRemoteMode();
        if(remoteMode){
            await browseRemote('folder');
        }else{
            const r=await pywebview.api.browse_folder();
            if(!r)return;
            document.getElementById('pathInput').value=r;
            const check=await pywebview.api.check_existing_data(r);
            if(check&&check.loaded_steps&&check.loaded_steps.length>0){
                check.loaded_steps.forEach(s=>{pipeState[s]=2});
                updatePipe();
            }
        }
    }
    const p=document.getElementById('pathInput').value.trim();
    if(!p){toast('Unesite putanju!','error');return}
    const remote=_isRemotePath(p);
    const rp=_stripRemote(p);
    setBtns(true);startPolling();
    let ok=true;
    try{
        // Step 1: IMDB (if not done)
        if(ok&&pipeState[0]!==2){
            pipeState[0]=1;updatePipe();
            const r=await pywebview.api.search_imdb(remote?rp:p);
            const pick=await showImdbModal((r&&r.results)||[]);
            if(pick===null){pipeState[0]=0;updatePipe();ok=false;toast('IMDB/unos otkazan','error')}
            else{
                const ok1=await applyImdbChoice(pick);
                if(ok1){pipeState[0]=2;updatePipe()}
                else{pipeState[0]=0;updatePipe();ok=false;toast('Nije sacuvano','error')}
            }
        }
        // Step 2+3: Screenshots+Torrent (combined for remote)
        if(remote){
            if(ok&&(pipeState[1]!==2||pipeState[2]!==2)){
                pipeState[1]=1;pipeState[2]=1;updatePipe();
                const rr=await pywebview.api.sftp_run_remote(rp);
                if(rr&&rr.ok){pipeState[1]=2;pipeState[2]=2;updatePipe()}
                else{pipeState[1]=0;pipeState[2]=0;updatePipe();ok=false;toast('Remote obrada neuspesna: '+((rr&&rr.error)||''),'error')}
            }
        }else{
            if(ok&&pipeState[1]!==2){
                pipeState[1]=1;updatePipe();
                const r2=await pywebview.api.run_screenshots(p);
                if(r2&&r2.ok){pipeState[1]=2;updatePipe()}
                else{pipeState[1]=0;updatePipe();ok=false;toast('Screenshots neuspesno','error')}
            }
            if(ok&&pipeState[2]!==2){
                pipeState[2]=1;updatePipe();
                const r3=await pywebview.api.run_torrent(p);
                if(r3&&r3.ok){pipeState[2]=2;updatePipe()}
                else{pipeState[2]=0;updatePipe();ok=false;toast('Torrent kreiranje neuspesno','error')}
            }
        }
        // Step 4: Upload
        if(ok){
            pipeState[3]=1;updatePipe();
            const ud=await pywebview.api.get_upload_data();
            if(ud)await showUploadModal(ud);
            pipeState[3]=2;updatePipe();
            toast('Brzi upload zavrsen!','success');
        }
    }catch(e){console.error(e);toast('Greska u brzom uploadu: '+e,'error')}
    setBtns(false);
}


function showRemoteHelp(){
    const m=new bootstrap.Modal(document.getElementById('remoteHelpModal'));
    m.show();
    // Pretvori sve code blokove u redove sa pojedinacnim kopiranjem (jednom)
    setTimeout(enhanceCodeBlocks,50);
}

// Univerzalni copy helper sa fallback-ovima
async function _clipCopy(text){
    let ok=false;
    if(navigator.clipboard&&navigator.clipboard.writeText){
        try{await navigator.clipboard.writeText(text);ok=true}catch(e){}
    }
    if(!ok){try{ok=await pywebview.api.copy_to_clipboard(text)}catch(e){}}
    if(!ok){
        const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';
        document.body.appendChild(ta);ta.focus();ta.select();
        try{ok=document.execCommand('copy')}catch(e){}
        ta.remove();
    }
    return ok;
}

// Pretvara svaki <pre> u listu redova; svaki red ima svoje dugme za kopiranje
function enhanceCodeBlocks(){
    document.querySelectorAll('#remoteHelpModal .code-block').forEach(function(block){
        if(block.getAttribute('data-enhanced')==='1')return;
        const pre=block.querySelector('pre');
        if(!pre)return;
        const lines=pre.textContent.replace(/\\s+$/,'').split('\\n').filter(function(l){return l.trim().length});
        const wrap=document.createElement('div');
        wrap.className='code-lines';
        lines.forEach(function(ln){
            const row=document.createElement('div');
            row.className='code-line';
            const code=document.createElement('code');
            code.textContent=ln;
            const btn=document.createElement('button');
            btn.className='code-line-copy';
            btn.title='Kopiraj ovu liniju';
            btn.innerHTML='<i class="bi bi-clipboard"></i>';
            btn.onclick=async function(){
                const ok=await _clipCopy(ln);
                const ic=btn.querySelector('i');
                if(ok){ic.className='bi bi-check2';btn.classList.add('copied');toast('Linija kopirana','success');
                    setTimeout(function(){ic.className='bi bi-clipboard';btn.classList.remove('copied')},1500);}
                else toast('Greska pri kopiranju','error');
            };
            row.appendChild(code);
            row.appendChild(btn);
            wrap.appendChild(row);
        });
        // Zadrzi i "Kopiraj sve" dugme na vrhu
        pre.style.display='none';
        block.appendChild(wrap);
        block.setAttribute('data-enhanced','1');
    });
}

// Kopiraj ceo blok (dugme "Kopiraj")
async function copyCodeBlock(btn){
    try{
        const pre=btn.parentElement.querySelector('pre');
        if(!pre)return;
        const text=pre.textContent.trim();
        const ok=await _clipCopy(text);
        const orig=btn.innerHTML;
        if(ok){btn.classList.add('copied');btn.innerHTML='<i class="bi bi-check2"></i>Kopirano!';toast('Ceo blok kopiran','success');}
        else{btn.innerHTML='<i class="bi bi-x"></i>Greska';toast('Kopiranje neuspesno','error');}
        setTimeout(function(){btn.classList.remove('copied');btn.innerHTML=orig},2000);
    }catch(e){console.error('copyCodeBlock:',e);toast('Greska pri kopiranju','error')}
}

// ─── Cleanup ───
async function showCleanupModal(){
    const cfg=await pywebview.api.get_config();
    if(!cfg.cleanup_after_upload)return;
    const files=await pywebview.api.get_cleanup_files();
    if(!files||files.length===0)return;
    let html='<p style="font-size:13px;color:var(--muted)">Izaberite fajlove za brisanje:</p>';
    files.forEach((f,i)=>{
        const checked=f.default_delete?'checked':'';
        html+=`<div class="form-check"><input class="form-check-input cleanup-cb" type="checkbox" value="${esc(f.path)}" id="cl${i}" data-type="${f.type}" ${checked}><label class="form-check-label" for="cl${i}" style="font-size:12px">${esc(f.display)}</label></div>`;
    });
    document.getElementById('cleanupBody').innerHTML=html;
    const m=new bootstrap.Modal(document.getElementById('cleanupModal'));
    m.show();
}
async function doCleanup(){
    const checks=document.querySelectorAll('.cleanup-cb:checked');
    const paths=Array.from(checks).map(c=>c.value);
    if(paths.length===0){toast('Nista nije izabrano','info');return}
    const r=await pywebview.api.cleanup_files(paths);
    toast(r.message||'Obrisano','success');
    const m=bootstrap.Modal.getInstance(document.getElementById('cleanupModal'));
    if(m)m.hide();
}
async function saveCleanupPrefs(){
    const types={screenshots:false,mediainfo:false,torrent:false,nfo:false,imdb:false};
    document.querySelectorAll('.cleanup-cb').forEach(c=>{
        if(c.checked)types[c.dataset.type]=true;
    });
    await pywebview.api.save_settings({
        cleanup_after_upload:true,
        cleanup_delete_screenshots:types.screenshots||false,
        cleanup_delete_mediainfo:types.mediainfo||false,
        cleanup_delete_torrent:types.torrent||false,
        cleanup_delete_nfo:types.nfo||false,
        cleanup_delete_imdb:types.imdb||false
    });
    toast('Preferencije ciscenja sacuvane!','success');
}

// ─── Description Generator ───
async function showDescModal(trailer){
    const desc=await pywebview.api.generate_description(trailer||'');
    if(!desc)return;
    document.getElementById('descOutput').value=desc;
    document.getElementById('descPreview').innerHTML=bbcodeToHtml(desc);
    const m=new bootstrap.Modal(document.getElementById('descModal'));
    m.show();
}
async function copyUploadDesc(){
    const ta=document.getElementById('uploadDescOutput');
    if(!ta||!ta.value)return;
    try{await pywebview.api.copy_to_clipboard(ta.value);toast('Opis kopiran!','success');}catch(e){toast('Greska pri kopiranju','error');}
}
function bbcodeToHtml(bb){
    let h=esc(bb);
    h=h.replace(/\\[center\\](.*?)\\[\\/center\\]/gs,'<div class="bb-center">$1</div>');
    h=h.replace(/\\[b\\](.*?)\\[\\/b\\]/gs,'<span class="bb-bold">$1</span>');
    h=h.replace(/\\[size=(\\d+)\\](.*?)\\[\\/size\\]/gs,'<span class="bb-size$1">$2</span>');
    h=h.replace(/\\[url=(.*?)\\](.*?)\\[\\/url\\]/gs,'<a class="bb-url" href="#" onclick="return false">$2</a>');
    h=h.replace(/\\[youtube\\](.*?)\\[\\/youtube\\]/gs,'<div style="margin:8px 0;padding:8px;background:rgba(255,0,0,.08);border-radius:6px;font-size:12px"><i class="bi bi-youtube" style="color:#ff0000;margin-right:4px"></i>YouTube: $1</div>');
    h=h.replace(/\\n/g,'<br>');
    return h;
}
function copyDesc(){
    const ta=document.getElementById('descOutput');
    ta.select();
    document.execCommand('copy');
    toast('Opis kopiran u clipboard!','success');
}

// ─── Upload History ───
var _histCache=[];
function renderHistory(hist){
    _histCache=hist||[];
    const tb=document.getElementById('historyBody');
    if(!hist||hist.length===0){tb.innerHTML='<tr><td colspan="8" class="text-center text-muted py-3">Nema uploada</td></tr>';return}
    tb.innerHTML='';
    hist.slice().reverse().forEach((h,i)=>{
        const realIdx=hist.length-1-i;
        const size=h.size?(h.size/1073741824).toFixed(2)+' GB':'?';
        const link=h.url?`<a href="${esc(h.url)}" target="_blank" class="imdb-link" style="font-size:11px">Otvori</a>`:'';
        const descBtn=h.description?`<button class="btn btn-outline-light btn-sm py-0 px-1" style="font-size:10px" onclick="showHistDesc(${realIdx})"><i class="bi bi-clipboard"></i></button>`:'';
        const delBtn=`<button class="btn btn-outline-danger btn-sm py-0 px-1" style="font-size:10px" onclick="deleteHistoryItem(${realIdx})" title="Obrisi iz istorije"><i class="bi bi-trash"></i></button>`;
        tb.innerHTML+=`<tr><td class="ps-3 text-muted">${h.torrent_id||'?'}</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(h.name||'')}</td><td>${esc(h.category||'')}</td><td>${size}</td><td style="font-size:11px">${esc(h.date||'')}</td><td>${link}</td><td>${descBtn}</td><td>${delBtn}</td></tr>`;
    });
}
async function loadHistory(){
    const hist=await pywebview.api.get_upload_history();
    renderHistory(hist);
}
async function deleteHistoryItem(idx){
    if(!confirm('Obrisati ovaj unos iz istorije?'))return;
    await pywebview.api.delete_history_item(idx);
    await loadHistory();
    await loadStats();
    toast('Unos obrisan iz istorije','success');
}
async function showHistDesc(idx){
    if(!_histCache||!_histCache[idx])return;
    const d=_histCache[idx].description||'';
    document.getElementById('descOutput').value=d;
    document.getElementById('descPreview').innerHTML=bbcodeToHtml(d);
    const m=new bootstrap.Modal(document.getElementById('descModal'));
    m.show();
}

// ─── Auto Update Check ───
async function checkForUpdate(){
    try{
        const r=await pywebview.api.check_for_update();
        if(r&&r.update_available){
            document.getElementById('updateBody').innerHTML=`Dostupna je nova verzija <strong>${esc(r.latest_version)}</strong>.<br>Trenutna: ${esc(r.current_version)}`;
            document.getElementById('updateLink').href=r.download_url||'#';
            const m=new bootstrap.Modal(document.getElementById('updateModal'));
            m.show();
        }
    }catch(e){console.log('Update check failed:',e)}
}

async function fetchCats(){
    const r=await pickCategory();
    if(r){
        document.getElementById('upCatId').value=r.id;
        const info=document.getElementById('catInfo');
        if(info)info.innerHTML='<span style="color:var(--accent)"><i class="bi bi-check2 me-1"></i>'+esc(r.name)+'</span>';
    }
}

// Unified picker - returns Promise resolving to {id, name} or null
function pickCategory(){
    return new Promise(async resolve=>{
        const list=document.getElementById('catPickerList');
        const search=document.getElementById('catPickerSearch');
        list.innerHTML='<div style="padding:10px"><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div></div>';
        search.value='';
        const modalEl=document.getElementById('catPickerModal');
        const modal=new bootstrap.Modal(modalEl);
        let resolved=false;
        const finish=v=>{resolved=true;modal.hide();resolve(v)};
        modalEl.addEventListener('hidden.bs.modal',()=>{if(!resolved)resolve(null)},{once:true});
        modal.show();

        let cats=[];
        try{
            const r=await pywebview.api.fetch_categories();
            if(r&&r.error){list.innerHTML='<div class="text-danger text-center py-3">'+esc(r.error)+'</div>';return}
            const raw=r&&r.categories;
            if(Array.isArray(raw)){
                raw.forEach(c=>{
                    const id=c.id||c.term_id||c.cat_ID||c.ID||null;
                    const nm=c.name||c.title||c.cat_name||'?';
                    if(id!==null&&id!==undefined)cats.push({id:id,name:String(nm)});
                });
            }else if(raw&&typeof raw==='object'){
                Object.entries(raw).forEach(([k,v])=>{
                    if(typeof v==='object'&&v!==null){
                        const id=v.id||v.term_id||k;
                        const nm=v.name||v.title||String(v);
                        cats.push({id:id,name:String(nm)});
                    }else{
                        cats.push({id:k,name:String(v)});
                    }
                });
            }
        }catch(e){list.innerHTML='<div class="text-danger text-center py-3">'+esc(e.toString())+'</div>';return}

        if(!cats.length){list.innerHTML='<div class="text-muted text-center py-3">Nema kategorija.</div>';return}

        function render(filter){
            const f=(filter||'').toLowerCase().trim();
            const filtered=f?cats.filter(c=>String(c.name).toLowerCase().includes(f)||String(c.id).includes(f)):cats;
            if(!filtered.length){list.innerHTML='<div class="text-muted text-center py-3">Nema rezultata za "'+esc(filter)+'"</div>';return}
            list.innerHTML=filtered.map(c=>`<div class="cat-item" onclick="window._catPick(${c.id},'${esc(c.name).replace(/'/g,"\\\\'")}')">
                <span class="cat-id">${c.id}</span>
                <span class="cat-name">${esc(c.name)}</span>
                <i class="bi bi-arrow-right text-muted"></i>
            </div>`).join('');
        }
        window._catPick=(id,name)=>finish({id:id,name:name});
        render('');
        search.oninput=e=>render(e.target.value);
        search.focus();
    });
}

async function fetchCatsSw(){
    const r=await pickCategory();
    if(r){
        document.getElementById('swCatId').value=r.id;
        swCatName=r.name||'';
        swUpdateCatLabel();
        toast('Izabrano: '+r.name,'success');
    }
}
function swUpdateCatLabel(){
    const el=document.getElementById('swCatLabel');
    if(!el)return;
    el.textContent=swCatName?('Kategorija: '+swCatName):'';
}

// ─── Tools ───
const TOOL_DEFS=[{key:'ffmpeg',name:'FFmpeg + FFprobe',desc:'Screenshots iz videa'},{key:'mediainfo',name:'MediaInfo CLI',desc:'Info o video fajlu'},{key:'torrenttools',name:'Torrenttools',desc:'Kreiranje .torrent fajla'}];
const _toolBusy=new Set(); // dlKey currently downloading

let _toolAutoState={};
async function _loadToolAutoState(){
    const cfg=await pywebview.api.get_config();
    _toolAutoState=cfg;
}
async function setToolAutoDownload(name, val){
    await pywebview.api.set_tool_auto_download(name, val);
    _toolAutoState['auto_download_tools_'+name]=val;
}
function _toolRowHtml(d,found,busy){
    const dlKey=d.dl||d.key;
    const toggleKey='auto_download_tools_'+dlKey;
    const autoOn=_toolAutoState[toggleKey]!==false;
    const toggleId='toolToggle_'+dlKey;
    const pathEsc=esc(found||'');
    const status=found?'<span class="badge bg-success">Pronadjen</span>':'<span class="badge bg-danger">Nedostaje</span>';
    let btn;
    if(busy){
        btn=`<button class="btn btn-outline-light btn-sm" disabled><span class="spinner-border spinner-border-sm me-1" style="width:10px;height:10px;border-width:1.5px"></span>Preuzimam...</button>`;
    }else{
        btn=`<button class="btn btn-outline-light btn-sm" onclick="downloadTool('${dlKey}')">${found?'Ponovo':'Preuzmi'}</button>`;
        if(found)btn+=`<button class="btn btn-outline-danger btn-sm" onclick="removeTool('${dlKey}','${d.name}')" title="Ukloni"><i class="bi bi-trash"></i></button>`;
    }
    return `<tr data-dlkey="${dlKey}">
        <td class="ps-3"><div class="d-flex align-items-center gap-2"><div class="form-check form-switch mb-0" title="Auto-preuzimanje"><input class="form-check-input" type="checkbox" id="${toggleId}" ${autoOn?'checked':''} onchange="setToolAutoDownload('${dlKey}',this.checked)"></div><div><strong>${d.name}</strong><br><small class="text-muted">${d.desc}</small></div></div></td>
        <td>${status}</td>
        <td class="path-cell" data-path="${pathEsc}"><span class="path-text">${pathEsc||'<em style="opacity:.5">(nije instaliran)</em>'}</span></td>
        <td class="actions-cell">${btn}</td>
    </tr>`;
}

async function refreshTools(toolsData){
    if(!Object.keys(_toolAutoState).length) await _loadToolAutoState();
    const t=toolsData||await pywebview.api.check_tools_status();
    window._lastToolStatus=t;
    const tb=document.getElementById('toolsBody');
    tb.innerHTML=TOOL_DEFS.map(d=>_toolRowHtml(d,t[d.key],_toolBusy.has(d.dl||d.key))).join('');
}

function _updateToolRowBusy(dlKey){
    // Re-render just the one row in place to reflect busy state without clobbering UI
    const t=window._lastToolStatus||{};
    const d=TOOL_DEFS.find(x=>(x.dl||x.key)===dlKey);
    if(!d)return;
    const tr=document.querySelector(`#toolsBody tr[data-dlkey="${dlKey}"]`);
    if(!tr)return;
    const wrap=document.createElement('tbody');
    wrap.innerHTML=_toolRowHtml(d,t[d.key],_toolBusy.has(dlKey));
    tr.replaceWith(wrap.firstElementChild);
}

async function downloadTool(n){
    if(_toolBusy.has(n))return;
    _toolBusy.add(n);
    _updateToolRowBusy(n);
    startPolling();
    try{await pywebview.api.download_tool(n)}
    catch(e){toast('Greska: '+e,'danger')}
    _toolBusy.delete(n);
    await refreshTools();
}
async function downloadAllTools(){
    const btn=event&&event.target&&event.target.closest('button');
    if(btn)btn.disabled=true;
    TOOL_DEFS.forEach(d=>_toolBusy.add(d.dl||d.key));
    await refreshTools();
    startPolling();
    try{await pywebview.api.download_all_tools()}
    catch(e){toast('Greska: '+e,'danger')}
    _toolBusy.clear();
    if(btn)btn.disabled=false;
    await refreshTools();
}
async function removeTool(n,label){
    if(_toolBusy.has(n))return;
    if(!confirm(`Ukloni "${label}" iz tools foldera?`))return;
    _toolBusy.add(n);_updateToolRowBusy(n);
    startPolling();
    const r=await pywebview.api.remove_tool(n);
    _toolBusy.delete(n);
    if(r&&r.ok)toast(`${label} uklonjen`,'success');
    else toast(r&&r.message?r.message:'Neuspesno','danger');
    await refreshTools();
}
async function openToolsDir(){await pywebview.api.open_tools_dir()}



// ─── Settings ───
async function loadSettings(cfgData){
    const c=cfgData||await pywebview.api.get_config();
    document.getElementById('cfgTmdb').value=c.tmdb_api_key||'';
    document.getElementById('cfgCb').value=c.cb_api_key||'';

    document.getElementById('cfgOutput').value=c.output_dir||'';
    document.getElementById('cfgDownload').value=c.download_path||'';
    document.getElementById('cfgAnnounce').value=c.announce_url||'';
    document.getElementById('cfgSsCount').value=c.screenshot_count||10;
    document.getElementById('cfgAutoTrailer').checked=c.auto_youtube_trailer!==false;
    document.getElementById('cfgCleanup').checked=!!c.cleanup_after_upload;
    document.getElementById('cfgDelSs').checked=c.cleanup_delete_screenshots!==false;
    document.getElementById('cfgDelMi').checked=c.cleanup_delete_mediainfo!==false;
    document.getElementById('cfgDelTorrent').checked=!!c.cleanup_delete_torrent;
    document.getElementById('cfgDelNfo').checked=c.cleanup_delete_nfo!==false;
    document.getElementById('cfgDelImdb').checked=c.cleanup_delete_imdb!==false;
    // FTP/SFTP
    document.getElementById('cfgFtpEnabled').checked=!!c.ftp_enabled;
    document.getElementById('cfgFtpProto').value=c.ftp_protocol||'sftp';
    document.getElementById('cfgFtpHost').value=c.ftp_host||'';
    document.getElementById('cfgFtpPort').value=c.ftp_port||22;
    document.getElementById('cfgFtpUser').value=c.ftp_user||'';
    document.getElementById('cfgFtpPass').value=c.ftp_pass||'';
    document.getElementById('cfgFtpDir').value=c.ftp_remote_dir||'/watch';
    document.getElementById('cfgFtpSourceDir').value=c.ftp_source_dir||'';
    document.getElementById('ftpSettings').style.display=c.ftp_enabled?'block':'none';
    document.getElementById('cfgFtpEnabled').addEventListener('change',function(){document.getElementById('ftpSettings').style.display=this.checked?'block':'none'});
    // Theme
    applyTheme(c.theme||'dark');
    document.getElementById('btnThemeDark').className='btn btn-sm '+(c.theme!=='light'?'btn-accent':'btn-outline-light');
    document.getElementById('btnThemeLight').className='btn btn-sm '+(c.theme==='light'?'btn-accent':'btn-outline-light');
}
async function saveSettings(){
    await pywebview.api.save_settings({
        tmdb_api_key:document.getElementById('cfgTmdb').value,
        cb_api_key:document.getElementById('cfgCb').value,

        output_dir:document.getElementById('cfgOutput').value,
        download_path:document.getElementById('cfgDownload').value,
        announce_url:document.getElementById('cfgAnnounce').value,
        screenshot_count:parseInt(document.getElementById('cfgSsCount').value)||10,
        auto_youtube_trailer:document.getElementById('cfgAutoTrailer').checked,
        cleanup_after_upload:document.getElementById('cfgCleanup').checked,
        cleanup_delete_screenshots:document.getElementById('cfgDelSs').checked,
        cleanup_delete_mediainfo:document.getElementById('cfgDelMi').checked,
        cleanup_delete_torrent:document.getElementById('cfgDelTorrent').checked,
        cleanup_delete_nfo:document.getElementById('cfgDelNfo').checked,
        cleanup_delete_imdb:document.getElementById('cfgDelImdb').checked,
        ftp_enabled:document.getElementById('cfgFtpEnabled').checked,
        ftp_protocol:document.getElementById('cfgFtpProto').value,
        ftp_host:document.getElementById('cfgFtpHost').value,
        ftp_port:parseInt(document.getElementById('cfgFtpPort').value)||22,
        ftp_user:document.getElementById('cfgFtpUser').value,
        ftp_pass:document.getElementById('cfgFtpPass').value,
        ftp_remote_dir:document.getElementById('cfgFtpDir').value||'/watch',
        ftp_source_dir:document.getElementById('cfgFtpSourceDir').value
    });
    toast('Podesavanja sacuvana!','success');
}

// ─── Theme ───
function setTheme(t){
    applyTheme(t);
    document.getElementById('btnThemeDark').className='btn btn-sm '+(t!=='light'?'btn-accent':'btn-outline-light');
    document.getElementById('btnThemeLight').className='btn btn-sm '+(t==='light'?'btn-accent':'btn-outline-light');
    pywebview.api.save_settings({theme:t});
}
function applyTheme(t){
    document.body.classList.toggle('light',t==='light');
    document.documentElement.setAttribute('data-bs-theme',t==='light'?'light':'dark');
}

// ─── Stats ───
function _countUp(el,target){
    if(!el)return;
    const start=parseInt(el.getAttribute('data-val')||'0')||0;
    const end=parseInt(target)||0;
    if(start===end){el.textContent=end;return}
    el.setAttribute('data-val',end);
    const dur=600,t0=performance.now();
    function step(now){
        const p=Math.min((now-t0)/dur,1);
        const eased=1-Math.pow(1-p,3);
        el.textContent=Math.round(start+(end-start)*eased);
        if(p<1)requestAnimationFrame(step);else el.textContent=end;
    }
    requestAnimationFrame(step);
}
async function loadStats(statsData){
    const s=statsData||await pywebview.api.get_stats();
    if(!s)return;
    _countUp(document.getElementById('statTotal'),s.total||0);
    document.getElementById('statSize').textContent=s.total_size||'0 GB';
    document.getElementById('statLast').textContent=s.last_date||'-';
    _countUp(document.getElementById('statQueue'),queueItems.length);
}

// ─── Sidebar collapse ───
function toggleSidebar(){
    document.body.classList.toggle('sidebar-collapsed');
    const collapsed=document.body.classList.contains('sidebar-collapsed');
    const ch=document.getElementById('sidebarChevron');
    if(ch)ch.className=collapsed?'bi bi-layout-sidebar':'bi bi-layout-sidebar-inset';
    const btn=document.getElementById('sidebarCollapseBtn');
    if(btn)btn.title=collapsed?'Prosiri meni':'Skupi meni';
    try{pywebview.api.save_settings({sidebar_collapsed:collapsed})}catch(e){}
}

// ─── Export History ───
async function exportHistory(fmt){
    const data=await pywebview.api.export_history(fmt);
    if(!data)return;
    const blob=new Blob([data.content],{type:data.mime});
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=data.filename;
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Istorija eksportovana!','success');
}



// ─── Software / Programi / Igrice tab ───
let swImagesList=[];
let swNfoPath='';
let swCatName='';

function swLog(msg){
    const el=document.getElementById('swLog');
    if(!el)return;
    const cls=msg.includes('[ERR')?'log-err':msg.includes('[OK]')?'log-ok':msg.includes('[WARN')?'log-warn':'log-info';
    el.innerHTML+='<div class="'+cls+'">'+esc(msg)+'</div>';
    el.scrollTop=el.scrollHeight;
}
function _swIsRemoteMode(){var el=document.getElementById('swSrcRemote');return !!(el&&el.checked)}
async function swBrowseFolderSmart(){if(_swIsRemoteMode())return await swBrowseRemote('folder');return await swBrowseFolder()}
async function swBrowseFileSmart(){if(_swIsRemoteMode())return await swBrowseRemote('file');return await swBrowseFile()}

async function swBrowseRemote(mode){
    const cfg=await pywebview.api.get_config();
    if(!cfg||!cfg.ftp_host||!cfg.ftp_user){toast('Podesite SFTP podatke u Podesavanjima!','error');return;}
    const startDir=cfg.ftp_source_dir||'/';
    const picked=await showRemoteBrowser(startDir,mode);
    if(picked){
        document.getElementById('swPath').value='sftp://'+picked;
        _swAutoName('sftp://'+picked);
        toast('Remote izbor: '+picked,'info');
    }
}

async function swBrowseFolder(){const r=await pywebview.api.browse_folder();if(r){document.getElementById('swPath').value=r;_swAutoName(r)}}
async function swBrowseFile(){const r=await pywebview.api.browse_any_file();if(r){document.getElementById('swPath').value=r;_swAutoName(r)}}
function _swAutoName(p){
    const nm=document.getElementById('swName');
    if(nm&&!nm.value){
        const base=p.split(/[\\\\/]/).pop()||'';
        const noExt=base.replace(/\\.[^.]+$/,'');
        nm.value=noExt.replace(/\\./g,' ').replace(/\\s+/g,' ').trim();
    }
}
async function swBrowseImages(){
    const r=await pywebview.api.browse_image_files();
    if(r&&r.length){
        swImagesList=r.slice(0,10);
        _swRenderImages();
    }
}
function swClearImages(){swImagesList=[];_swRenderImages()}
function _swRenderImages(){
    document.getElementById('swImages').value=swImagesList.length?swImagesList.length+' slika izabrano':'';
    const prev=document.getElementById('swImagesPreview');
    prev.innerHTML='';
    swImagesList.forEach((p,i)=>{prev.innerHTML+='<div class="badge bg-secondary" style="font-size:10px">'+(i+1)+'. '+esc(p.split(/[\\\\/]/).pop())+'</div>'});
}
async function swBrowseNfo(){const r=await pywebview.api.browse_nfo_file();if(r){swNfoPath=r;document.getElementById('swNfo').value=r.split(/[\\\\/]/).pop()}}
async function swMakeTorrent(){
    const path=document.getElementById('swPath').value.trim();
    if(!path){toast('Unesite putanju!','error');return}
    document.getElementById('swMakeBtn').disabled=true;
    swLog('-- Kreiranje torrenta --');
    try{
        const r=await pywebview.api.sw_make_torrent(path);
        if(r&&r.ok){swLog('[OK] Torrent kreiran: '+r.torrent_file);toast('Torrent kreiran','success')}
        else{swLog('[ERR] '+((r&&r.error)||'nepoznata greska'));toast('Greska','error')}
    }catch(e){swLog('[ERR] '+e.toString())}
    finally{document.getElementById('swMakeBtn').disabled=false}
}
async function swDoUpload(){
    const path=document.getElementById('swPath').value.trim();
    const name=document.getElementById('swName').value.trim();
    const cat=document.getElementById('swCatId').value.trim();
    const desc=document.getElementById('swDesc').value;
    const year=document.getElementById('swYear').value.trim();
    const url=document.getElementById('swUrl').value.trim();
    const anon=document.getElementById('swAnon').checked;
    const cmt=document.getElementById('swComments').checked;
    if(!path){toast('Unesite putanju!','error');return}
    if(!name){toast('Unesite naziv!','error');return}
    if(!cat||!/^[0-9]+$/.test(cat)){toast('Unesite validan ID kategorije!','error');return}
    document.getElementById('swUploadBtn').disabled=true;
    swLog('-- Upload na crnaberza.com --');
    try{
        const r=await pywebview.api.sw_upload({
            path:path,name:name,category:parseInt(cat),description:desc,
            category_name:swCatName,year:year,url:url,
            images:swImagesList,nfo_path:swNfoPath,
            anonymous:anon,allow_comments:cmt
        });
        if(r&&r.ok){
            swLog('[OK] Upload uspesan! ID: '+(r.torrent_id||'-'));
            if(r.url)swLog('  Pregled: '+r.url);
            toast('Upload uspesan!','success');
            await loadHistory();await loadStats();
        }else{
            swLog('[ERR] '+((r&&r.error)||'upload neuspesan'));
            toast('Upload neuspesan','error');
        }
    }catch(e){swLog('[ERR] '+e.toString())}
    finally{document.getElementById('swUploadBtn').disabled=false}
}

// Poll sw log when on software page
setInterval(async()=>{
    const pg=document.getElementById('page-software');
    if(!pg||!pg.classList.contains('active'))return;
    try{
        const upd=await pywebview.api.get_updates();
        if(upd&&upd.logs)upd.logs.forEach(swLog);
    }catch(e){}
},800);

// ─── Requests (queue API from site) ───
let requestsList=[];
async function loadRequests(){
    const status=document.querySelector('input[name="reqStatus"]:checked').value;
    const tbody=document.getElementById('requestsBody');
    tbody.innerHTML='<tr><td colspan="9" style="padding:0"><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div></td></tr>';
    try{
        const r=await pywebview.api.requests_fetch(status);
        if(!r||!r.ok){
            tbody.innerHTML='<tr><td colspan="9" class="text-center text-danger py-3">Greska: '+esc((r&&r.error)||'nepoznata')+'</td></tr>';
            return;
        }
        requestsList=r.items||[];
        if(!requestsList.length){
            tbody.innerHTML='<tr><td colspan="9" class="text-center text-muted py-3">Nema zahteva.</td></tr>';
            updateRequestsBadge();return;
        }
        tbody.innerHTML=requestsList.map((it,idx)=>{
            const dt=it.created?new Date(it.created*1000).toLocaleString():'-';
            const det=it.type==='tv'?(
                it.ep_mode==='all'?'Sve epizode':
                it.ep_mode==='season'?'Sezona '+(it.season||'?'):
                'S'+(it.season||'?')+'E'+(it.episode||'?')
            ):'Film';
            const stCls='req-status-'+it.status;
            const stLbl={pending:'Cekanje',processing:'U toku',done:'Zavrseno',error:'Greska'}[it.status]||it.status;
            return `<tr>
                <td class="ps-3">${it.id}</td>
                <td><span class="badge ${it.type==='tv'?'bg-primary':'bg-secondary'}" style="font-size:10px">${it.type==='tv'?'TV':'Film'}</span></td>
                <td>${esc(it.service||'')}</td>
                <td><a href="#" class="req-url-link" onclick="navigator.clipboard.writeText('${esc(it.url||'')}');toast('URL kopiran','success');return false" title="${esc(it.url||'')}">${esc((it.url||'').substring(0,40))}${(it.url||'').length>40?'...':''}</a></td>
                <td>${esc(det)}</td>
                <td style="font-size:11px;color:var(--muted)">${esc(it.notes||'')}</td>
                <td><span class="req-status-pill ${stCls}">${esc(stLbl)}</span></td>
                <td style="white-space:nowrap;font-size:11px;color:var(--muted)">${dt}</td>
                <td class="text-end pe-3" style="white-space:nowrap">
                    <button class="btn btn-outline-light btn-sm req-action-btn" onclick="reqSetStatus(${it.id},'processing')" title="Postavi: U toku"><i class="bi bi-play-fill"></i></button>
                    <button class="btn btn-outline-light btn-sm req-action-btn" onclick="reqSetStatus(${it.id},'done')" title="Postavi: Zavrseno"><i class="bi bi-check2"></i></button>
                    <button class="btn btn-outline-light btn-sm req-action-btn" onclick="reqSetStatus(${it.id},'error')" title="Postavi: Greska"><i class="bi bi-x-lg"></i></button>
                    <button class="btn btn-outline-light btn-sm req-action-btn" onclick="reqSetStatus(${it.id},'pending')" title="Vrati na cekanje"><i class="bi bi-arrow-counterclockwise"></i></button>
                </td>
            </tr>`;
        }).join('');
        updateRequestsBadge();
    }catch(e){
        tbody.innerHTML='<tr><td colspan="9" class="text-center text-danger py-3">'+esc(e.toString())+'</td></tr>';
    }
}
async function reqSetStatus(id,status){
    let notes=null;
    if(status==='error'){
        notes=prompt('Razlog greske (opciono):');
        if(notes===null)return; // canceled
    }
    try{
        const r=await pywebview.api.requests_update(id,status,notes||'');
        if(r&&r.ok){toast('Status promenjen: '+status,'success');loadRequests()}
        else{toast('Greska: '+((r&&r.error)||''),'error')}
    }catch(e){toast(e.toString(),'error')}
}
function updateRequestsBadge(){
    const b=document.getElementById('requestsBadge');
    if(!b)return;
    const pendingCount=requestsList.filter(it=>it.status==='pending').length;
    if(pendingCount>0){b.style.display='flex';b.textContent=pendingCount}else{b.style.display='none'}
}
// Auto-load requests on tab open
document.addEventListener('DOMContentLoaded',function(){
    document.querySelectorAll('input[name="reqStatus"]').forEach(r=>r.addEventListener('change',loadRequests));
});

// ─── Keyboard Shortcuts ───
document.addEventListener('keydown',function(e){
    if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;
    if(e.ctrlKey&&e.key==='q'){e.preventDefault();quickUpload()}
    if(e.ctrlKey&&e.key==='b'){e.preventDefault();batchUpload()}
    if(e.ctrlKey&&e.key==='1'){e.preventDefault();pipeClick(0)}
    if(e.ctrlKey&&e.key==='2'){e.preventDefault();pipeClick(1)}
    if(e.ctrlKey&&e.key==='3'){e.preventDefault();pipeClick(2)}
    if(e.ctrlKey&&e.key==='4'){e.preventDefault();pipeClick(3)}
});

// ─── Init ───
// INIT_DATA is embedded in HTML by Python before window creation — zero bridge calls.
function _doInit(){
    try{
        if(typeof INIT_DATA!=='undefined'){
            if(INIT_DATA.config) loadSettings(INIT_DATA.config);
            if(INIT_DATA.tools) refreshTools(INIT_DATA.tools);
            if(INIT_DATA.history) renderHistory(INIT_DATA.history);
            if(INIT_DATA.stats) loadStats(INIT_DATA.stats);
            if(INIT_DATA.queue&&Array.isArray(INIT_DATA.queue)){queueItems=INIT_DATA.queue;renderQueue();updateQueueBadge()}
            if(INIT_DATA.config&&INIT_DATA.config.sidebar_collapsed){
                document.body.classList.add('sidebar-collapsed');
                var ch=document.getElementById('sidebarChevron');if(ch)ch.className='bi bi-layout-sidebar';
            }
        }
        // Source mode toggle
        var srcL=document.getElementById('srcLocal'),srcR=document.getElementById('srcRemote');
        if(srcL&&srcR){
            srcL.addEventListener('change',function(){if(this.checked)document.getElementById('srcRemoteHint').style.display='none'});
            srcR.addEventListener('change',function(){if(this.checked)document.getElementById('srcRemoteHint').style.display='block'});
        }
    }catch(e){console.error('init:',e)}
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',_doInit);
else _doInit();
// NO polling or bridge calls at startup! Polling starts only when user triggers an action.
// pywebviewready just marks the bridge as available.
window.addEventListener('pywebviewready',function(){ window._bridgeReady=true; checkForUpdate(); });
</script>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# API CLASS  (exposed to JavaScript via pywebview)
# ═══════════════════════════════════════════════════════════════════════════════

class Api:
    def __init__(self):
        self.window = None
        self._log_q = []
        self._tlog_q = []
        self._slog_q = []
        self._progress = 0
        self._status = "Spreman"
        self._lock = threading.Lock()
        self._op_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._cached_tools = None
        self._dropped_path = None
        # runtime state
        self.imdb_url = None
        self.screenshot_files = []
        self.mediainfo_text = None
        self.torrent_file = None
        self.is_tv = False
        self.is_domace = False
        self.is_hd = True
        self.detected_subtitles = []
        self.item_output_dir = None
        self._tmdb_results = None
        self.tmdb_poster_url = None
        self.tmdb_title = None
        self.tmdb_year = None
        self.tmdb_overview = None
        self.tmdb_genres = []
        self.tmdb_url = None
        self.source_path = None
        # Rucni unos (bez TMDB): Film, Serija, Igrica, Program, Muzika, Ostalo
        self.is_manual = False
        self.content_type = None

    # ─── internal helpers ─────────────────────────────────────────────

    def _run_blocking(self, fn, *args, **kwargs):
        """Pokreni tešku operaciju u pozadinskom threadu da ne blokira UI."""
        self._cancel_event.clear()
        result = {}

        def worker():
            try:
                result["value"] = fn(*args, **kwargs)
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join()
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def cancel_operation(self):
        self._cancel_event.set()
        self._status = "Prekid..."
        return {"ok": True}

    def _log(self, msg):
        with self._lock:
            self._log_q.append(msg)

    def _tlog(self, msg):
        with self._lock:
            self._tlog_q.append(msg)

    def _slog(self, msg):
        with self._lock:
            self._slog_q.append(msg)

    def _ensure_item_dir(self, path):
        self.source_path = path
        item_name = os.path.basename(os.path.normpath(path))
        # If path is a file, strip video extension for output dir name
        if os.path.isfile(path):
            item_name = os.path.splitext(item_name)[0]
        self.item_output_dir = os.path.join(CONFIG["output_dir"], item_name)
        os.makedirs(self.item_output_dir, exist_ok=True)
        return self.item_output_dir

    def reset_from_step(self, step_index):
        """Reset state from step_index onwards. 0=imdb,1=ss,2=torrent,3=upload."""
        self._log(f"[INFO] Ponistavanje od koraka {step_index + 1}...")
        if step_index <= 0:
            self.imdb_url = None
            self._tmdb_results = None
            self.tmdb_poster_url = None
            self.tmdb_title = None
            self.tmdb_year = None
            self.tmdb_overview = None
            self.tmdb_genres = []
            self.tmdb_url = None
            self.is_tv = False
            self.is_domace = False
            self.is_manual = False
            self.content_type = None
        if step_index <= 1:
            self.screenshot_files = []
            self.mediainfo_text = None
            self.is_hd = True
            self.detected_subtitles = []
        if step_index <= 2:
            self.torrent_file = None
        self._progress = 0
        self._status = "Spreman"

    # ─── JS-callable API ──────────────────────────────────────────────

    def get_updates(self):
        with self._lock:
            logs = self._log_q[:]
            self._log_q.clear()
            tlogs = self._tlog_q[:]
            self._tlog_q.clear()
            slogs = self._slog_q[:]
            self._slog_q.clear()
        return {"logs": logs, "tool_logs": tlogs, "sync_logs": slogs,
                "progress": self._progress, "status": self._status}

    def browse_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def get_dropped_path(self):
        """Return last dropped file path. Reads pywebview's internal _dnd_state directly
        (much faster than waiting for the DOM event roundtrip)."""
        # First check if Python DOM handler already pushed it
        if self._dropped_path:
            p = self._dropped_path
            self._dropped_path = None
            return p
        # Otherwise pull from pywebview's internal drop state
        try:
            from webview.dom import _dnd_state
            paths = _dnd_state.get('paths') or []
            if paths:
                # paths is list of (filename, fullpath) tuples
                _, full = paths.pop(0)
                import urllib.parse as _up
                full = _up.unquote(full) if isinstance(full, str) else full
                return full
        except Exception:
            pass
        return None

    def browse_main_video_file(self):
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('Video fajlovi (*.mkv;*.mp4;*.avi;*.m2ts;*.mov;*.wmv;*.ts;*.webm;*.flv;*.mpg;*.mpeg)',
                        'Svi fajlovi (*.*)'))
        if result and len(result):
            return result[0]
        return None



    def _restore_tmdb_from_imdb(self, imdb_id):
        """Background TMDB lookup from IMDB id to restore metadata."""
        try:
            find_data = tmdb_request(f"find/{imdb_id}?external_source=imdb_id")
            item = None
            if find_data.get("tv_results"):
                self.is_tv = True
                item = find_data["tv_results"][0]
            elif find_data.get("movie_results"):
                self.is_tv = False
                item = find_data["movie_results"][0]
            if not item:
                return
            original_language = item.get("original_language", "")
            self.is_domace = original_language in ("sr", "hr", "bs", "sh", "cnr")
            self.tmdb_title = item.get("title") or item.get("name")
            self.tmdb_year = (item.get("release_date") or item.get("first_air_date", ""))[:4]
            if item.get("poster_path"):
                self.tmdb_poster_url = f"https://image.tmdb.org/t/p/w342{item['poster_path']}"
            search_type = "tv" if self.is_tv else "movie"
            tid = item.get("id")
            self.tmdb_url = f"https://www.themoviedb.org/{search_type}/{tid}"
            try:
                en_ov = item.get("overview", "")
                self.tmdb_overview, self.tmdb_genres = tmdb_get_local(search_type, tid, en_ov)
            except Exception:
                self.tmdb_overview = item.get("overview", "")
            tip = "TV Serija" if self.is_tv else "Film"
            poreklo = "Domace" if self.is_domace else "Strano"
            self._log(f"[LOAD] {self.tmdb_title} ({self.tmdb_year}) - {tip}/{poreklo}")
        except Exception as e:
            self._log(f"[LOAD] TMDB restore: {e}")

    def check_existing_data(self, path):
        """Check if output folder has existing data from a previous run and load it."""
        item_name = os.path.basename(os.path.normpath(path))
        if os.path.isfile(path):
            item_name = os.path.splitext(item_name)[0]
        out_dir = os.path.join(CONFIG["output_dir"], item_name)
        if not os.path.isdir(out_dir):
            return {"loaded_steps": []}

        self.item_output_dir = out_dir
        loaded = []

        # Check manual metadata (non-TMDB entries)
        manual_meta_file = os.path.join(out_dir, "manual_meta.json")
        if os.path.exists(manual_meta_file):
            try:
                with open(manual_meta_file, "r", encoding="utf-8") as f:
                    m = json.load(f)
                self.is_manual = True
                self.content_type = m.get("content_type") or "other"
                self.is_tv = (self.content_type == "tv")
                self.is_domace = bool(m.get("is_domace"))
                self.tmdb_title = m.get("title") or None
                self.tmdb_year = m.get("year") or None
                self.tmdb_overview = m.get("overview") or None
                self.tmdb_poster_url = m.get("poster_url") or None
                self.tmdb_genres = m.get("genres") or []
                self.imdb_url = m.get("imdb_url") or None
                loaded.append(0)
                tip_map = {"movie": "Film", "tv": "TV Serija", "game": "Igrica",
                           "software": "Program", "music": "Muzika", "other": "Ostalo"}
                self._log(f"[LOAD] Rucni unos: {self.tmdb_title or '?'} [{tip_map.get(self.content_type,'?')}]")
            except Exception as e:
                self._log(f"[WARN] manual_meta.json: {e}")

        # Check IMDB (TMDB-based restore path) - samo ako nije vec ucitan rucni unos
        imdb_file = os.path.join(out_dir, "imdb.txt")
        if os.path.exists(imdb_file) and not self.is_manual:
            with open(imdb_file, "r", encoding="utf-8") as f:
                self.imdb_url = f.read().strip()
            if self.imdb_url:
                loaded.append(0)
                self._log(f"[LOAD] IMDB: {self.imdb_url}")
                # Restore TMDB data in background thread (network call - don't block UI)
                imdb_match = re.search(r'tt\d+', self.imdb_url)
                if imdb_match and CONFIG.get("tmdb_api_key"):
                    threading.Thread(target=self._restore_tmdb_from_imdb,
                                     args=(imdb_match.group(0),), daemon=True).start()

        # Check screenshots + mediainfo
        ss_dir = os.path.join(out_dir, "screenshots")
        mi_file = os.path.join(out_dir, "mediainfo.txt")
        has_ss = os.path.isdir(ss_dir) and any(Path(ss_dir).glob("*.jpg"))
        has_mi = os.path.exists(mi_file)

        if has_ss or has_mi:
            if has_ss:
                self.screenshot_files = sorted(str(f) for f in Path(ss_dir).glob("*.jpg"))
                self._log(f"[LOAD] Screenshots: {len(self.screenshot_files)}")
            if has_mi:
                with open(mi_file, "r", encoding="utf-8") as f:
                    self.mediainfo_text = f.read()
                self._log("[LOAD] MediaInfo ucitan")
                width_match = re.search(r'Width\s*:\s*(\d[\d\s]*)', self.mediainfo_text)
                if width_match:
                    width = int(width_match.group(1).replace(' ', ''))
                    self.is_hd = width >= 1280
            if has_ss and has_mi:
                loaded.append(1)

        # Detect subtitles: from mediainfo (embedded) + SRT files (external)
        subs = set()
        if self.mediainfo_text:
            subs.update(detect_subtitles_from_mediainfo(self.mediainfo_text))
        subs.update(scan_srt_subtitles(path))
        self.detected_subtitles = sorted(subs)
        if self.detected_subtitles:
            self._log(f"[LOAD] Titlovi: {', '.join(self.detected_subtitles)}")

        # Check torrent
        torrent_files = list(Path(out_dir).rglob("*.torrent"))
        if torrent_files:
            self.torrent_file = str(torrent_files[0])
            loaded.append(2)
            self._log(f"[LOAD] Torrent: {os.path.basename(self.torrent_file)}")

        if loaded:
            self._log(f"[LOAD] Ucitano {len(loaded)} korak(a) iz prethodnog rada")

        return {"loaded_steps": loaded}

    def get_config(self):
        return dict(CONFIG)

    def save_settings(self, cfg):
        CONFIG.update(cfg)
        save_config(CONFIG)

    def set_tool_auto_download(self, name, value):
        """Toggle auto-download for a specific tool."""
        key = f"auto_download_tools_{name}"
        CONFIG[key] = bool(value)
        save_config(CONFIG)
        return {"ok": True}

    def check_tools_status(self):
        if self._cached_tools:
            ct = self._cached_tools
            self._cached_tools = None
            return ct
        t = check_all_tools()
        return {"ffmpeg": t["ffmpeg"] or "", "mediainfo": t["mediainfo"] or "",
                "torrenttools": t["torrenttools"] or ""}

    def download_tool(self, name):
        self._do_download(name)
        return {"ok": True}

    def download_all_tools(self):
        for t in ("ffmpeg", "mediainfo", "torrenttools"):
            self._do_download(t)

    def remove_tool(self, name):
        try:
            ok = remove_tool(name, log_cb=self._tlog)
            return {"ok": True, "removed": ok}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def open_tools_dir(self):
        os.makedirs(TOOLS_DIR, exist_ok=True)
        os.startfile(TOOLS_DIR)

    # ─── MKV Subtitle Operations ─────────────────────────────────────

    def browse_mkv_file(self):
        result = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=('MKV fajlovi (*.mkv)',))
        if result and len(result):
            return result[0]
        return None

    def browse_srt_file(self):
        result = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=('SRT fajlovi (*.srt)',))
        if result and len(result):
            return result[0]
        return None

    def browse_video_file(self):
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('Video i titl fajlovi (*.mkv;*.mp4;*.avi;*.m2ts;*.mov;*.wmv;*.srt;*.ass;*.ssa;*.sub;*.idx;*.vtt)', 'Svi fajlovi (*.*)'))
        if result and len(result):
            return result[0]
        return None

    # ─── Subtitle Sync (AutoSubSync) ─────────────────────────────────

    def sync_check_deps(self):
        return {"ffsubsync": bool(check_ffsubsync_available()),
                "autosubsync": bool(check_autosubsync_available()),
                "alass": bool(get_alass_path())}

    def sync_subtitle_run(self, video_path, subtitle_path, method="ffsubsync", suffix="_synced"):
        """Run subtitle sync on main thread-safe-ish background. Blocks caller (JS awaits)."""
        if not os.path.isfile(video_path):
            return {"ok": False, "message": "Video fajl ne postoji"}
        if not os.path.isfile(subtitle_path):
            return {"ok": False, "message": "SRT fajl ne postoji"}
        base, ext = os.path.splitext(subtitle_path)
        out = f"{base}{suffix or '_synced'}{ext or '.srt'}"
        try:
            ok, msg = sync_subtitle(video_path, subtitle_path, out, method=method, log_cb=self._slog)
            if ok:
                return {"ok": True, "path": out}
            return {"ok": False, "message": msg}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def sync_folder_subtitles(self, folder, method="ffsubsync", suffix="_synced"):
        """Sync all .srt files in folder against the largest video file.
        Returns list of {srt, ok, out, message}."""
        video = find_main_video_in_folder(folder)
        if not video:
            return {"ok": False, "message": "Nijedan video fajl nije pronadjen u folderu"}
        srts = find_srt_files_in_folder(folder)
        srts = [s for s in srts if not s.endswith(f"{suffix}.srt")]  # skip already synced
        if not srts:
            return {"ok": True, "results": [], "video": video, "message": "Nema .srt fajlova za sinhronizaciju"}
        self._slog(f"[sync] Video referenca: {os.path.basename(video)}")
        results = []
        for srt in srts:
            base, ext = os.path.splitext(srt)
            out = f"{base}{suffix}{ext}"
            ok, msg = sync_subtitle(video, srt, out, method=method, log_cb=self._slog)
            results.append({"srt": srt, "ok": ok, "out": out if ok else None, "message": msg if not ok else ""})
        return {"ok": True, "results": results, "video": video}

    def mkv_get_tracks(self, mkv_path):
        """Get subtitle tracks from MKV file using mkvmerge --identify."""
        mkvmerge = get_mkvmerge_path()
        if not mkvmerge:
            return {"error": "MKVToolNix nije instaliran. Idi na Alati tab."}
        try:
            out = subprocess.run(
                [mkvmerge, "--identify", "--identification-format", "json", mkv_path],
                capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            info = json.loads(out.stdout)
            subs = []
            for tr in info.get("tracks", []):
                if tr.get("type") == "subtitles":
                    props = tr.get("properties", {})
                    subs.append({
                        "id": tr["id"],
                        "language": props.get("language", ""),
                        "name": props.get("track_name", ""),
                        "codec": tr.get("codec", ""),
                    })
            return {"tracks": subs}
        except Exception as e:
            return {"error": str(e)}

    def mkv_add_srt(self, mkv_path, srt_path, language="srp", track_name=""):
        """Add SRT subtitle to MKV file using mkvmerge. Auto-converts encoding to UTF-8."""
        mkvmerge = get_mkvmerge_path()
        if not mkvmerge:
            return {"ok": False, "error": "MKVToolNix nije instaliran."}
        if not os.path.exists(srt_path):
            return {"ok": False, "error": f"SRT fajl ne postoji: {srt_path}"}

        # Auto-detect encoding and convert to UTF-8 if needed
        actual_srt = srt_path
        tmp_srt = None
        try:
            with open(srt_path, "rb") as f:
                raw = f.read()
            # Check for UTF-8 BOM or try UTF-8 decode
            is_utf8 = False
            if raw[:3] == b'\xef\xbb\xbf':
                is_utf8 = True
            else:
                try:
                    raw.decode("utf-8")
                    # If it decodes fine AND contains typical Serbian chars, it's UTF-8
                    is_utf8 = True
                except UnicodeDecodeError:
                    is_utf8 = False

            if not is_utf8:
                # Try common encodings for Serbian/Croatian/Bosnian subtitles
                decoded = None
                for enc in ("cp1250", "cp1251", "iso-8859-2", "iso-8859-16", "latin-1"):
                    try:
                        decoded = raw.decode(enc)
                        # Verify it contains expected characters (ćčžšđ)
                        if any(c in decoded for c in "ćčžšđĆČŽŠĐ"):
                            break
                        decoded = None
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        continue
                if not decoded:
                    decoded = raw.decode("cp1250", errors="replace")

                tmp_srt = srt_path + ".utf8.srt"
                with open(tmp_srt, "w", encoding="utf-8") as f:
                    f.write(decoded)
                actual_srt = tmp_srt

        except Exception as e:
            print(f"[MKV] Encoding detection failed: {e}, using original file")

        output = mkv_path + ".tmp.mkv"
        try:
            cmd = [mkvmerge, "-o", output, mkv_path,
                   "--sub-charset", "0:UTF-8",
                   "--language", f"0:{language}"]
            if track_name:
                cmd.extend(["--track-name", f"0:{track_name}"])
            cmd.append(actual_srt)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
            if result.returncode > 1:
                return {"ok": False, "error": result.stdout + result.stderr}
            # Replace original with new file
            os.replace(output, mkv_path)
            return {"ok": True}
        except Exception as e:
            if os.path.exists(output):
                try: os.remove(output)
                except: pass
            return {"ok": False, "error": str(e)}
        finally:
            if tmp_srt and os.path.exists(tmp_srt):
                try: os.remove(tmp_srt)
                except: pass

    def mkv_remove_track(self, mkv_path, track_id):
        """Remove a subtitle track from MKV file."""
        mkvmerge = get_mkvmerge_path()
        if not mkvmerge:
            return {"ok": False, "error": "MKVToolNix nije instaliran."}
        output = mkv_path + ".tmp.mkv"
        try:
            cmd = [mkvmerge, "-o", output, "--subtitle-tracks", f"!{track_id}", mkv_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
            if result.returncode > 1:
                return {"ok": False, "error": result.stdout + result.stderr}
            os.replace(output, mkv_path)
            return {"ok": True}
        except Exception as e:
            if os.path.exists(output):
                try: os.remove(output)
                except: pass
            return {"ok": False, "error": str(e)}

    def mkv_extract_srt(self, mkv_path, track_id):
        """Extract a subtitle track from MKV to SRT file."""
        mkvextract = get_mkvextract_path()
        if not mkvextract:
            return {"ok": False, "error": "MKVToolNix nije instaliran."}
        srt_output = os.path.splitext(mkv_path)[0] + f"_track{track_id}.srt"
        try:
            result = subprocess.run(
                [mkvextract, "tracks", mkv_path, f"{track_id}:{srt_output}"],
                capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
            if result.returncode != 0:
                return {"ok": False, "error": result.stdout + result.stderr}
            return {"ok": True, "path": srt_output}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── Auto-check Tools ────────────────────────────────────────────

    def quick_check_tools(self):
        """Fast local-only check: are tools present on disk? No network."""
        finder = {"ffmpeg": get_ffmpeg_path, "mediainfo": get_mediainfo_path,
                  "torrenttools": get_torrenttools_path}
        missing = []
        for name in TOOL_INFO:
            if not finder.get(name, lambda: None)():
                missing.append(name)
        return {"missing": missing}

    def start_bg_tool_check(self):
        """Start auto-check in a background thread so it doesn't block JS bridge."""
        t = threading.Thread(target=self._bg_tool_check, daemon=True)
        t.start()

    def _start_bg_tasks(self):
        """Start background tasks after window is created."""
        import time
        time.sleep(1)  # Brief grace period so UI finishes first paint
        threading.Thread(target=self._bg_tool_check, daemon=True).start()
        threading.Thread(target=self._bg_update_check, daemon=True).start()

    def _bg_update_check(self):
        """Check for updates in background thread."""
        try:
            result = self.check_for_update()
            if result and result.get('update_available'):
                # Signal JS via log message that update is available
                self._log(f"[UPDATE] Nova verzija {result['latest_version']} dostupna! Trenutna: {result['current_version']}")
        except Exception:
            pass

    def _bg_tool_check(self):
        """Auto-download missing tools, update outdated ones (background thread)."""
        cfg = load_config()
        try:
            self._check_latest_versions()
        except Exception:
            pass
        installed = load_tool_versions()
        finder = {"ffmpeg": get_ffmpeg_path, "mediainfo": get_mediainfo_path,
                  "torrenttools": get_torrenttools_path}
        for name, info in TOOL_INFO.items():
            per_tool_key = f"auto_download_tools_{name}"
            if not cfg.get(per_tool_key, True):
                self._tlog(f"Auto-preuzimanje za {name} je iskljuceno.")
                continue
            try:
                found = finder.get(name, lambda: None)()
            except Exception:
                found = None
            local_ver = installed.get(name, "")
            if not found or local_ver != info["version"]:
                self._tlog(f"Auto-preuzimanje: {name}...")
                try:
                    self._do_download(name)
                except Exception as e:
                    self._tlog(f"[ERR] {name}: {e}")
            else:
                self._tlog(f"{name} v{local_ver} - OK")

    def _check_latest_versions(self):
        """Try to fetch latest tool versions from online sources (short timeouts)."""
        try:
            req = urllib.request.Request("https://www.gyan.dev/ffmpeg/builds/release-version",
                                         headers={"User-Agent": "CrnaBerza/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                ver = resp.read().decode().strip()
            if ver:
                TOOL_INFO["ffmpeg"]["version"] = ver
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/MediaArea/MediaInfo/releases/latest",
                headers={"User-Agent": "CrnaBerza/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            ver = data.get("tag_name", "").lstrip("v")
            if ver:
                TOOL_INFO["mediainfo"]["version"] = ver
                TOOL_INFO["mediainfo"]["url"] = (
                    f"https://mediaarea.net/download/binary/mediainfo/{ver}/"
                    f"MediaInfo_CLI_{ver}_Windows_x64.zip")
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/fbdtemme/torrenttools/releases/latest",
                headers={"User-Agent": "CrnaBerza/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            ver = data.get("tag_name", "").lstrip("v")
            if ver:
                TOOL_INFO["torrenttools"]["version"] = ver
                for asset in data.get("assets", []):
                    if "windows" in asset["name"].lower() and asset["name"].endswith(".msi"):
                        TOOL_INFO["torrenttools"]["url"] = asset["browser_download_url"]
                        break
        except Exception:
            pass

    # ─── IMDB ─────────────────────────────────────────────────────────

    def search_imdb(self, path):
        return self._run_blocking(self._search_imdb_impl, path)

    def _search_imdb_impl(self, path):
        self._progress = 0
        self._status = "IMDB pretraga..."
        self._log("═══ KORAK 1: IMDB PRETRAGA ═══")
        folder_name = os.path.basename(os.path.normpath(path))
        clean_name, year, season = clean_folder_name(folder_name)
        out_dir = self._ensure_item_dir(path)
        self._log(f"  Folder:   {folder_name}")
        self._log(f"  Output:   {out_dir}")
        self._log(f"  Pretraga: {clean_name}")
        if year:
            self._log(f"  Godina:   {year}")

        if not CONFIG["tmdb_api_key"]:
            self._log("[WARN] TMDB API kljuc nije podesen - mozete nastaviti preko rucnog unosa.")
            self._tmdb_results = []
            return {"results": [], "no_api_key": True}

        try:
            results = self._tmdb_search(clean_name, year)
        except Exception as e:
            self._log(f"[WARN] TMDB pretraga nije uspela: {e}")
            results = []

        if not results:
            self._log("[INFO] Nema TMDB rezultata. Mozete preci na 'Rucni unos' tab.")

        self._tmdb_results = results or []
        return {"results": self._tmdb_results}

    def search_imdb_manual(self, query):
        """Manual TMDB search from user input in the modal."""
        clean_name, year, _ = clean_folder_name(query)
        results = self._tmdb_search(clean_name, year)
        if not results:
            return {"results": []}
        self._tmdb_results = results
        return {"results": results}

    def _tmdb_search(self, query, year=None):
        """Search TMDB with multi + movie + tv fallback, return up to 10 results."""
        encoded_query = urllib.parse.quote(query)
        seen_ids = set()
        combined = []

        # 1) search/multi
        try:
            year_param = f"&year={year}" if year else ""
            response = tmdb_request(f"search/multi?query={encoded_query}&include_adult=false{year_param}")
            for r in response.get("results", []):
                if r.get("media_type") == "person":
                    continue
                key = (r.get("media_type", "movie"), r.get("id"))
                if key not in seen_ids:
                    seen_ids.add(key)
                    combined.append(r)
        except Exception:
            pass

        # 2) If less than 5 results, also try search/movie and search/tv
        if len(combined) < 5:
            for stype in ("movie", "tv"):
                try:
                    year_key = "year" if stype == "movie" else "first_air_date_year"
                    year_param = f"&{year_key}={year}" if year else ""
                    resp = tmdb_request(f"search/{stype}?query={encoded_query}&include_adult=false{year_param}")
                    for r in resp.get("results", []):
                        r["media_type"] = stype
                        key = (stype, r.get("id"))
                        if key not in seen_ids:
                            seen_ids.add(key)
                            combined.append(r)
                except Exception:
                    pass

        # 3) If still few results and year was used, retry without year
        if len(combined) < 3 and year:
            try:
                response = tmdb_request(f"search/multi?query={encoded_query}&include_adult=false")
                for r in response.get("results", []):
                    if r.get("media_type") == "person":
                        continue
                    key = (r.get("media_type", "movie"), r.get("id"))
                    if key not in seen_ids:
                        seen_ids.add(key)
                        combined.append(r)
            except Exception:
                pass

        # Sort by popularity descending
        combined.sort(key=lambda x: x.get("popularity", 0), reverse=True)
        return combined[:10]

    def confirm_imdb(self, index):
        if not self._tmdb_results or index >= len(self._tmdb_results):
            return

        selected = self._tmdb_results[index]
        search_type = "tv" if selected.get("media_type") == "tv" else "movie"
        # Kada biramo iz TMDB-a, poništi flag za rucni unos
        self.is_manual = False
        self.content_type = "tv" if search_type == "tv" else "movie"

        self._log("  Preuzimanje IMDB ID-a...")
        try:
            details = tmdb_request(f"{search_type}/{selected['id']}/external_ids")
        except Exception as e:
            self._log(f"[ERR] IMDB ID: {e}")
            return

        imdb_id = details.get("imdb_id")
        if not imdb_id:
            self._log("[ERR] IMDB ID nije pronadjen")
            return

        self.imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
        self.tmdb_url = f"https://www.themoviedb.org/{search_type}/{selected['id']}"
        title = selected.get("title") or selected.get("name")
        self.tmdb_title = title
        self.tmdb_year = (selected.get("release_date") or selected.get("first_air_date", ""))[:4]
        if selected.get("poster_path"):
            self.tmdb_poster_url = f"https://image.tmdb.org/t/p/w342{selected['poster_path']}"
        # Pokusaj dohvatiti opis i zanrove na srpskom (sr/hr/bs fallback)
        en_ov = selected.get("overview", "")
        try:
            self.tmdb_overview, self.tmdb_genres = tmdb_get_local(search_type, selected['id'], en_ov)
        except Exception as e:
            print(f"[WARN] tmdb_get_local error: {e}")
            self.tmdb_overview = en_ov
            self.tmdb_genres = []
        self._log(f"[OK] {title}")
        self._log(f"[OK] IMDB: {self.imdb_url}")

        # Auto-detect TV/Film and Domace/Strano
        self._log("  Detekcija tipa i jezika...")
        try:
            find_data = tmdb_request(f"find/{imdb_id}?external_source=imdb_id")
            if find_data.get("tv_results"):
                self.is_tv = True
                original_language = find_data["tv_results"][0].get("original_language", "")
            elif find_data.get("movie_results"):
                self.is_tv = False
                original_language = find_data["movie_results"][0].get("original_language", "")
            else:
                original_language = selected.get("original_language", "")
                self.is_tv = selected.get("media_type") == "tv"

            self.is_domace = original_language in ("sr", "hr", "bs", "sh", "cnr")
            tip = "TV Serija" if self.is_tv else "Film"
            poreklo = f"Domace ({original_language})" if self.is_domace else f"Strano ({original_language})"
            self._log(f"[OK] Tip: {tip} / {poreklo}")
        except Exception as e:
            self._log(f"[INFO] TMDB detekcija: {e}")
            self.is_tv = selected.get("media_type") == "tv"
            self.is_domace = False

        os.makedirs(self.item_output_dir, exist_ok=True)
        imdb_file = os.path.join(self.item_output_dir, "imdb.txt")
        with open(imdb_file, "w", encoding="utf-8") as f:
            f.write(self.imdb_url)
        self._log(f"[OK] Sacuvano: {imdb_file}")
        self._progress = 100
        self._status = "IMDB pretraga zavrsena"

    def save_manual_metadata(self, data):
        """Manual metadata entry (no TMDB). data: {content_type, title, year,
        overview, imdb_url, poster_url, is_domace, genres}.
        content_type: movie | tv | game | software | music | other."""
        self._log("═══ KORAK 1: RUCNI UNOS (BEZ TMDB) ═══")
        ctype = (data.get("content_type") or "other").lower()
        if ctype not in ("movie", "tv", "game", "software", "music", "other"):
            ctype = "other"

        self.is_manual = True
        self.content_type = ctype
        self.is_tv = (ctype == "tv")
        self.is_domace = bool(data.get("is_domace"))

        title = (data.get("title") or "").strip()
        year = (data.get("year") or "").strip()
        overview = (data.get("overview") or "").strip()
        imdb_url = (data.get("imdb_url") or "").strip()
        poster_url = (data.get("poster_url") or "").strip()
        genres = data.get("genres") or []
        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(",") if g.strip()]

        self.tmdb_title = title or None
        self.tmdb_year = year or None
        self.tmdb_overview = overview or None
        self.tmdb_genres = genres
        self.tmdb_poster_url = poster_url or None
        self.tmdb_url = None
        # Dozvoli prazan IMDB URL - za igrice/programe cesto nema
        self.imdb_url = imdb_url if imdb_url else None

        tip_map = {"movie": "Film", "tv": "TV Serija", "game": "Igrica",
                   "software": "Program/Softver", "music": "Muzika", "other": "Ostalo"}
        tip = tip_map.get(ctype, "Ostalo")
        poreklo = "Domace" if self.is_domace else "Strano"
        self._log(f"[OK] Tip: {tip} / {poreklo}")
        if title:
            self._log(f"[OK] Naziv: {title}" + (f" ({year})" if year else ""))
        if self.imdb_url:
            self._log(f"[OK] IMDB: {self.imdb_url}")

        if self.source_path:
            self._ensure_item_dir(self.source_path)
        if self.item_output_dir:
            os.makedirs(self.item_output_dir, exist_ok=True)
            if self.imdb_url:
                imdb_file = os.path.join(self.item_output_dir, "imdb.txt")
                try:
                    with open(imdb_file, "w", encoding="utf-8") as f:
                        f.write(self.imdb_url)
                    self._log(f"[OK] Sacuvano: {imdb_file}")
                except Exception as e:
                    self._log(f"[WARN] imdb.txt: {e}")
            # Sacuvaj i rucne metapodatke za restore pri sledecem ucitavanju
            try:
                meta_file = os.path.join(self.item_output_dir, "manual_meta.json")
                with open(meta_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "content_type": ctype,
                        "title": title,
                        "year": year,
                        "overview": overview,
                        "imdb_url": imdb_url,
                        "poster_url": poster_url,
                        "is_domace": self.is_domace,
                        "genres": genres,
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self._log(f"[WARN] manual_meta.json: {e}")

        self._progress = 100
        self._status = "Rucni unos sacuvan"
        return {"ok": True}

    # ─── Screenshots & MediaInfo ──────────────────────────────────────

    def run_screenshots(self, path):
        return self._run_blocking(self._run_screenshots_impl, path)

    def _run_screenshots_impl(self, path):
        self._progress = 0
        self._status = "Screenshots & MediaInfo..."
        if not os.path.exists(path):
            self._log(f"[ERR] Putanja ne postoji: {path}")
            return {"ok": False}

        # Za non-video tipove (igrice, programi, muzika, ostalo): preskoci ako nema videa
        if self.is_manual and self.content_type in ("game", "software", "music", "other"):
            self._ensure_item_dir(path)
            video_path = find_video_file(path)
            if not video_path:
                self._log("\n═══ KORAK 2: SCREENSHOTS & MEDIAINFO (preskoceno) ═══")
                self._log("[INFO] Nema video fajla - preskacem screenshots/mediainfo (tip sadrzaja nije video)")
                self.screenshot_files = []
                self.mediainfo_text = None
                self._progress = 100
                self._status = "Preskoceno (nije video)"
                return {"ok": True, "skipped": True}

        self._do_screenshots(path)
        ok = bool(self.screenshot_files)
        self._progress = 100
        self._status = "Screenshots zavrseno" if ok else "Screenshots neuspesno"
        return {"ok": ok}

    def _do_screenshots(self, path):
        self._log("\n═══ KORAK 2: SCREENSHOTS & MEDIAINFO ═══")

        video_path = find_video_file(path)
        if not video_path:
            self._log("[ERR] Video fajl nije pronadjen")
            return

        ffmpeg_exe = get_ffmpeg_path()
        ffprobe_exe = get_ffprobe_path()
        if not ffmpeg_exe or not ffprobe_exe:
            self._log("[ERR] FFmpeg nije pronadjen! Idi na tab 'Alati'.")
            return

        video_name = os.path.basename(video_path)
        if not self.item_output_dir:
            self._ensure_item_dir(path)
        screenshots_dir = os.path.join(self.item_output_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        for f in Path(screenshots_dir).glob("*.jpg"):
            f.unlink()

        self._log(f"  Video: {video_name}")

        try:
            out = subprocess.run(
                [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            duration = float(out.stdout.strip())
        except Exception as e:
            self._log(f"[ERR] Trajanje: {e}")
            return

        try:
            out = subprocess.run(
                [ffprobe_exe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path],
                capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            resolution = out.stdout.strip()
        except Exception:
            resolution = "?"

        self._log(f"  Trajanje:   {format_duration(duration)}")
        self._log(f"  Rezolucija: {resolution}")

        count = CONFIG["screenshot_count"]
        start_time = duration * (CONFIG["skip_start_percent"] / 100)
        end_time = duration * (1 - CONFIG["skip_end_percent"] / 100)
        interval = (end_time - start_time) / (count + 1)

        self._log(f"  Generisanje {count} screenshot-ova...")
        self.screenshot_files = []

        for i in range(1, count + 1):
            timestamp = start_time + (interval * i)
            output_file = os.path.join(screenshots_dir, f"screenshot_{i:02d}.jpg")
            subprocess.run(
                [ffmpeg_exe, "-y", "-ss", str(timestamp), "-i", video_path,
                 "-vframes", "1", "-q:v", "2", "-update", "1", output_file],
                capture_output=True, timeout=60, creationflags=NO_WINDOW)
            if os.path.exists(output_file):
                size_kb = os.path.getsize(output_file) / 1024
                self._log(f"    [{i}/{count}] {format_duration(timestamp)} - {size_kb:.0f}KB")
                self.screenshot_files.append(output_file)
            self._progress = int(i * 90 / count)
            self._status = f"Screenshots: {i}/{count}"

        # MediaInfo
        self.mediainfo_text = None
        mi_path = get_mediainfo_path()
        if mi_path:
            try:
                mi_out = subprocess.run([mi_path, video_path], capture_output=True,
                                        text=True, timeout=30, creationflags=NO_WINDOW)
                self.mediainfo_text = mi_out.stdout
                mi_file = os.path.join(self.item_output_dir, "mediainfo.txt")
                with open(mi_file, "w", encoding="utf-8") as f:
                    f.write(self.mediainfo_text)
                self._log("[OK] MediaInfo sacuvan")

                width_match = re.search(r'Width\s*:\s*(\d[\d\s]*)', self.mediainfo_text)
                if width_match:
                    width = int(width_match.group(1).replace(' ', ''))
                    self.is_hd = width >= 1280
                    self._log(f"  Rezolucija: {'HD' if self.is_hd else 'SD'} ({width} px)")
                else:
                    self.is_hd = True

            except Exception as e:
                self._log(f"[ERR] MediaInfo: {e}")
        else:
            self._log("[INFO] MediaInfo nije pronadjen")

        # Detect subtitles: from mediainfo (embedded) + SRT files (external)
        subs = set()
        if self.mediainfo_text:
            subs.update(detect_subtitles_from_mediainfo(self.mediainfo_text))
        subs.update(scan_srt_subtitles(path))
        self.detected_subtitles = sorted(subs)
        if self.detected_subtitles:
            self._log(f"  Titlovi: {', '.join(self.detected_subtitles)}")

        self._log(f"[OK] {len(self.screenshot_files)} screenshot-ova sacuvano")

    # ─── Torrent ──────────────────────────────────────────────────────

    def run_torrent(self, path):
        return self._run_blocking(self._run_torrent_impl, path)

    def _run_torrent_impl(self, path):
        self._progress = 0
        self._status = "Kreiranje torrenta..."
        if not os.path.exists(path):
            self._log(f"[ERR] Putanja ne postoji: {path}")
            return {"ok": False}
        self._do_torrent(path)
        ok = bool(self.torrent_file and os.path.exists(self.torrent_file))
        self._progress = 100
        self._status = "Torrent kreiran" if ok else "Torrent neuspesno"
        return {"ok": ok}

    def _compute_piece_length(self, path):
        """Izracunaj optimalnu velicinu komada (piece length) na osnovu ukupne velicine.
        Cilj: ~1000-2000 komada da torrent fajl ostane mali (vazno zbog API limita)."""
        try:
            total = 0
            if os.path.isfile(path):
                total = os.path.getsize(path)
            else:
                for root, _dirs, files in os.walk(path):
                    for fn in files:
                        try:
                            total += os.path.getsize(os.path.join(root, fn))
                        except Exception:
                            pass
            if total <= 0:
                return None, 0
            # Ciljamo ~1500 komada
            target_pieces = 1500
            ideal = total / target_pieces
            # Zaokruzi na najblizi stepen dvojke, izmedju 256KiB i 32MiB
            exp = 18  # 256 KiB
            while (1 << exp) < ideal and exp < 25:  # do 32 MiB
                exp += 1
            piece_len = 1 << exp
            pieces = -(-total // piece_len)  # ceil
            return exp, pieces
        except Exception:
            return None, 0

    def _do_torrent(self, path):
        self._log("\n═══ KORAK 3: KREIRANJE TORRENTA ═══")

        tt_exe = get_torrenttools_path()
        if not tt_exe:
            self._log("[ERR] torrenttools nije pronadjen! Idi na tab 'Alati'.")
            return

        item_name = os.path.basename(os.path.normpath(path))
        if not self.item_output_dir:
            self._ensure_item_dir(path)
        os.makedirs(self.item_output_dir, exist_ok=True)
        output_file = os.path.join(self.item_output_dir, f"{item_name}.torrent")

        if os.path.exists(output_file):
            os.remove(output_file)

        # Izracunaj optimalnu velicinu komada (manji torrent fajl = prolazi API limit)
        exp, est_pieces = self._compute_piece_length(path)
        cmd = [tt_exe, "create", "--announce", CONFIG["announce_url"],
               "--private", "--output", output_file]
        if exp:
            # torrenttools: --piece-size prima velicinu sa K/M sufiksom (npr. 4M), power-of-two [16K, 64M]
            piece_bytes = 1 << exp
            if piece_bytes >= 1048576:
                psize = f"{piece_bytes // 1048576}M"
            else:
                psize = f"{piece_bytes // 1024}K"
            cmd += ["--piece-size", psize]
            self._log(f"  Velicina komada: {psize} (~{est_pieces} komada)")
        cmd.append(path)

        self._log(f"  Kreiranje: {item_name}")
        self._log(f"  Ovo moze potrajati za velike fajlove...")
        self._progress = -1  # indeterminate

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)

            output_data = []
            def _reader():
                try:
                    raw = proc.stdout.read()
                    output_data.append(raw)
                except Exception:
                    pass
            reader_t = threading.Thread(target=_reader, daemon=True)
            reader_t.start()

            start_t = time.time()
            while proc.poll() is None:
                elapsed = int(time.time() - start_t)
                mins, secs = divmod(elapsed, 60)
                hours, mins = divmod(mins, 60)
                if hours > 0:
                    ts = f"{hours}h {mins:02d}m {secs:02d}s"
                elif mins > 0:
                    ts = f"{mins}m {secs:02d}s"
                else:
                    ts = f"{secs}s"
                self._status = f"Hashiranje u toku... ({ts})"
                time.sleep(1)

            reader_t.join(timeout=30)

            elapsed = int(time.time() - start_t)
            mins, secs = divmod(elapsed, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                self._log(f"  Vreme: {hours}h {mins:02d}m {secs:02d}s")
            elif mins > 0:
                self._log(f"  Vreme: {mins}m {secs:02d}s")
            else:
                self._log(f"  Vreme: {secs}s")

            if output_data:
                text = output_data[0].decode("utf-8", errors="replace")
                text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
                text = re.sub(r'\x1b\].*?\x07', '', text)
                text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
                for raw_line in re.split(r'[\r\n]+', text):
                    line = raw_line.strip()
                    if not line:
                        continue
                    if any(line.startswith(p) for p in (
                        "Completed in:", "Average hash rate:",
                        "Infohash:", "Metafile written to:",
                        "Protocol version:", "Piece size:",
                        "Piece count:", "Created by:",
                    )):
                        self._log(f"  {line}")
                    elif "rror" in line or "ERR" in line:
                        self._log(f"  {line}")

        except Exception as e:
            self._log(f"[ERR] {e}")

        if os.path.exists(output_file):
            size_kb = os.path.getsize(output_file) / 1024
            self.torrent_file = output_file
            self._log(f"[OK] Kreirano: {output_file} ({size_kb:.1f} KB)")
        else:
            self._log("[ERR] Torrent kreiranje nije uspelo")

    # ─── MediaInfo Parser ─────────────────────────────────────────────

    def _parse_mediainfo(self):
        if not self.mediainfo_text:
            return None
        sections = {'general': {}, 'video': {}, 'audio': [], 'text': []}
        current = None
        for line in self.mediainfo_text.split('\n'):
            s = line.strip()
            if not s:
                continue
            if ' : ' not in s:
                low = s.lower()
                if low == 'general':
                    current = 'general'
                elif low.startswith('video'):
                    current = 'video'
                elif low.startswith('audio'):
                    current = 'audio'
                    sections['audio'].append({})
                elif low.startswith('text'):
                    current = 'text'
                    sections['text'].append({})
                elif low.startswith('menu'):
                    current = 'menu'
                else:
                    current = None
                continue
            key, val = s.split(' : ', 1)
            key, val = key.strip(), val.strip()
            if current == 'general':
                sections['general'][key] = val
            elif current == 'video':
                sections['video'][key] = val
            elif current == 'audio' and sections['audio']:
                sections['audio'][-1][key] = val
            elif current == 'text' and sections['text']:
                sections['text'][-1][key] = val

        g, v = sections['general'], sections['video']
        parsed = {'general': {}, 'video': {}, 'audio': [], 'subtitles': []}
        for k in ('Format', ):
            if g.get(k): parsed['general'][k] = g[k]
        if g.get('Duration'): parsed['general']['Duration'] = g['Duration']
        if g.get('Overall bit rate'): parsed['general']['Bitrate'] = g['Overall bit rate']
        if g.get('File size'): parsed['general']['Size'] = g['File size']
        vf = v.get('Format', '')
        bd = v.get('Bit depth', '')
        if vf: parsed['video']['Format'] = f"{vf} ({bd})" if bd else vf
        w, h = v.get('Width', ''), v.get('Height', '')
        if w and h:
            parsed['video']['Resolution'] = f"{w.replace(' pixels', '')} \u00d7 {h.replace(' pixels', '')}"
        if v.get('Display aspect ratio'): parsed['video']['Aspect ratio'] = v['Display aspect ratio']
        if v.get('Frame rate'): parsed['video']['Frame rate'] = v['Frame rate']
        vbr = v.get('Bit rate') or v.get('Nominal bit rate', '')
        if vbr: parsed['video']['Bit rate'] = vbr
        hdr = v.get('HDR format', '')
        if hdr:
            if 'dolby vision' in hdr.lower(): parsed['video']['HDR'] = 'Dolby Vision'
            elif 'hdr10+' in hdr.lower(): parsed['video']['HDR'] = 'HDR10+'
            elif 'hdr10' in hdr.lower(): parsed['video']['HDR'] = 'HDR10'
            else: parsed['video']['HDR'] = hdr.split(',')[0].strip()
        for a in sections['audio']:
            track = {}
            if a.get('Language'): track['Language'] = a['Language']
            cn = a.get('Commercial name', '')
            if cn: track['Format'] = cn
            elif a.get('Format'): track['Format'] = a['Format']
            if a.get('Channel layout'): track['Channels'] = a['Channel layout']
            elif a.get('Channel(s)'): track['Channels'] = a['Channel(s)']
            if a.get('Bit rate'): track['Bitrate'] = a['Bit rate']
            if track: parsed['audio'].append(track)
        for s in sections['text']:
            lang = s.get('Language', s.get('Title', ''))
            if lang:
                forced = ' (Forced)' if s.get('Forced', '').lower() == 'yes' else ''
                parsed['subtitles'].append(lang + forced)
        return parsed

    # ─── Upload ───────────────────────────────────────────────────────

    def get_upload_data(self):
        search_dir = self.item_output_dir or CONFIG["output_dir"]

        if not self.torrent_file:
            torrent_files = list(Path(search_dir).rglob("*.torrent"))
            self.torrent_file = str(torrent_files[0]) if torrent_files else None

        if not self.imdb_url:
            imdb_file = os.path.join(search_dir, "imdb.txt")
            if os.path.exists(imdb_file):
                with open(imdb_file, "r", encoding="utf-8") as f:
                    self.imdb_url = f.read().strip()

        if not self.screenshot_files:
            ss_dir = os.path.join(search_dir, "screenshots")
            if os.path.isdir(ss_dir):
                self.screenshot_files = sorted(str(f) for f in Path(ss_dir).glob("*.jpg"))

        if not self.mediainfo_text:
            mi_file = os.path.join(search_dir, "mediainfo.txt")
            if os.path.exists(mi_file):
                with open(mi_file, "r", encoding="utf-8") as f:
                    self.mediainfo_text = f.read()

        if self.is_manual and self.content_type not in ("movie", "tv"):
            # Za igrice/programe/muziku/ostalo - bez auto-kategorije
            cat_key = "Rucno (nema auto-kategorije)"
            cat_id = ""
        elif self.is_tv:
            cat_key = ("TV_HD_Domace" if self.is_domace else "TV_HD_Strano") if self.is_hd else \
                      ("TV_SD_Domace" if self.is_domace else "TV_SD_Strano")
            cat_id = CATEGORIES.get(cat_key, "")
        else:
            cat_key = ("Film_HD_Domace" if self.is_domace else "Film_HD_Strano") if self.is_hd else \
                      ("Film_SD_Domace" if self.is_domace else "Film_SD_Strano")
            cat_id = CATEGORIES.get(cat_key, "")

        return {
            "imdb_url": self.imdb_url or "",
            "is_tv": self.is_tv, "is_domace": self.is_domace, "is_hd": self.is_hd,
            "is_manual": self.is_manual,
            "content_type": self.content_type or ("tv" if self.is_tv else "movie"),
            "torrent_file": os.path.basename(self.torrent_file) if self.torrent_file else "",
            "screenshot_count": len(self.screenshot_files),
            "has_mediainfo": bool(self.mediainfo_text),
            "mediainfo_preview": (self.mediainfo_text or "")[:2500],
            "parsed_mediainfo": self._parse_mediainfo(),
            "poster_url": self.tmdb_poster_url or "",
            "tmdb_title": self.tmdb_title or "",
            "tmdb_year": self.tmdb_year or "",
            "tmdb_overview": self.tmdb_overview or "",
            "tmdb_genres": self.tmdb_genres or [],
            "subtitles": self.detected_subtitles,
            "watch_folder": CONFIG["download_path"],
            "category_id": cat_id,
            "category_name": cat_key.replace("_", " / "),
            "auto_name": Path(self.torrent_file).stem if self.torrent_file else "",
        }

    def get_screenshot_thumbnails(self):
        thumbs = []
        for sf in self.screenshot_files[:10]:
            try:
                if HAS_PIL:
                    img = Image.open(sf)
                    img.thumbnail((180, 110), Image.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format='JPEG', quality=70)
                    thumbs.append(f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}")
                else:
                    thumbs.append("")
            except Exception:
                thumbs.append("")
        return thumbs

    def _screenshot_b64_compressed(self, path, max_bytes=900*1024):
        """Vraca base64 screenshot-a; ako je prevelik i PIL dostupan, smanji kvalitet/dimenzije.
        Cilj: drzati ukupan payload ispod tipicnog PHP post_max_size."""
        try:
            if not os.path.exists(path):
                return ""
            if not HAS_PIL or os.path.getsize(path) <= max_bytes:
                return file_to_base64(path)
            try:
                img = Image.open(path)
                img = img.convert("RGB")
                max_w = 1920
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                for q in (85, 75, 65, 55, 45):
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=q)
                    if buf.tell() <= max_bytes or q == 45:
                        return base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception as e:
                self._log(f"  [WARN] Kompresija screenshot-a: {e}")
            return file_to_base64(path)
        except Exception:
            return ""

    def _dump_torrent_structure(self, torrent_path, out_dir):
        """Dekodira torrent i ispisuje kompletnu strukturu u konzolu + fajl za dijagnostiku."""
        try:
            if not torrent_path or not os.path.exists(torrent_path):
                self._log("  [DIAG] Torrent fajl ne postoji za dijagnostiku")
                return
            with open(torrent_path, "rb") as f:
                raw = f.read()
            meta, consumed = _bdecode(raw)
            lines = []
            lines.append(f"Fajl: {torrent_path}")
            lines.append(f"Velicina: {len(raw)} bajtova, dekodirano bajtova: {consumed}")
            if consumed != len(raw):
                lines.append(f"!!! UPOZORENJE: dekodirano {consumed} od {len(raw)} - visak podataka na kraju!")

            def describe(o, indent=0, key=""):
                pad = "  " * indent
                if isinstance(o, dict):
                    lines.append(f"{pad}{key}{{dict}} kljucevi: {[k.decode('utf-8','replace') if isinstance(k,bytes) else k for k in o.keys()]}")
                    for k, v in o.items():
                        ks = k.decode('utf-8', 'replace') if isinstance(k, bytes) else str(k)
                        # Ne ispisuj ceo 'pieces' (binarno)
                        if ks == "pieces":
                            lines.append(f"{pad}  {ks}: <{len(v) if isinstance(v,bytes) else '?'} bajtova, {(len(v)//20) if isinstance(v,bytes) else '?'} hesheva>")
                        else:
                            describe(v, indent + 1, ks + ": ")
                elif isinstance(o, list):
                    lines.append(f"{pad}{key}[list] ({len(o)} stavki)")
                    for idx, item in enumerate(o[:5]):
                        describe(item, indent + 1, f"[{idx}] ")
                    if len(o) > 5:
                        lines.append(f"{pad}  ... jos {len(o)-5}")
                elif isinstance(o, bytes):
                    try:
                        s = o.decode("utf-8")
                        if len(s) > 120:
                            s = s[:120] + "..."
                        lines.append(f"{pad}{key}'{s}' (str, {len(o)} b)")
                    except Exception:
                        lines.append(f"{pad}{key}<binarno {len(o)} b>")
                else:
                    lines.append(f"{pad}{key}{o} ({type(o).__name__})")

            describe(meta)
            report = "\n".join(lines)
            self._log("  ─── STRUKTURA TORRENTA ───")
            for ln in lines:
                self._log("  " + ln)
            self._log("  ──────────────────────────")
            try:
                with open(os.path.join(out_dir, "debug_torrent_struct.txt"), "w", encoding="utf-8") as f:
                    f.write(report)
            except Exception:
                pass
        except Exception as e:
            self._log(f"  [DIAG] Greska pri dekodiranju torrenta: {e}")

    def do_upload(self, category, name, trailer, anonymous, sync_subs=False, sync_method="ffsubsync", subtitles_override=None):
        return self._run_blocking(
            self._do_upload_wrapper,
            category, name, trailer, anonymous, sync_subs, sync_method, subtitles_override,
        )

    def _do_upload_wrapper(self, category, name, trailer, anonymous, sync_subs=False, sync_method="ffsubsync", subtitles_override=None):
        self._progress = 0
        self._status = "Upload u toku..."
        self._do_upload(category, name, trailer, anonymous, sync_subs, sync_method, subtitles_override)
        if self._cancel_event.is_set():
            raise RuntimeError("Upload otkazan")
        self._progress = 100
        self._status = "Zavrseno"

    def _do_upload(self, category, name, trailer, anonymous, sync_subs=False, sync_method="ffsubsync", subtitles_override=None):
        self._log("\n═══ KORAK 4: UPLOAD ═══")
        if not CONFIG["cb_api_key"]:
            self._log("[ERR] CB API kljuc nije podesen!")
            return
        if not self.torrent_file or not os.path.exists(self.torrent_file):
            self._log("[ERR] Torrent fajl ne postoji")
            return

        # Validacija torrent strukture pre slanja (sprecava 'Invalid torrent file structure')
        v_ok, v_msg = validate_torrent_file(self.torrent_file)
        if not v_ok:
            self._log(f"[ERR] Torrent fajl nije validan: {v_msg}")
            self._log("[ERR] Server bi odbio ovaj torrent. Ponovo kreirajte torrent (Korak 3).")
            self._log(f"  Putanja: {self.torrent_file}")
            return
        self._log(f"  Torrent validan: {v_msg}")
        # Normalizuj u kanonski bencode (resava odbijanje od strogog parsera)
        n_ok, n_msg = normalize_torrent(self.torrent_file, self._log)
        if n_ok:
            self._log(f"  Torrent normalizacija: {n_msg}")
        else:
            self._log(f"  [WARN] Normalizacija preskocena: {n_msg}")

        self._log(f"  Naziv:      {name}")
        self._log(f"  Kategorija: {category}")
        if trailer:
            self._log(f"  Trailer:    {trailer}")

        # Opis se salje preko API-ja (autoOpis=false), server koristi nas opis umesto da generise svoj
        desc = self.generate_description(trailer)

        url_to_send = self.imdb_url or ""
        if not url_to_send:
            url_to_send = "https://www.imdb.com/title/tt0000000/"

        data = {
            "torrent_file": file_to_base64(self.torrent_file),
            "url": url_to_send,
            "name": name,
            "description": desc,
            "autoOpis": False,
            "category": int(category),
            "anonymous": anonymous,
            "allow_comments": True,
        }

        if self.mediainfo_text:
            data["mediainfo"] = self.mediainfo_text
            self._log("  MediaInfo prilozen")

        # Subtitles: rucni override pobedjuje auto-detekciju ako je prosledjen
        final_subs = None
        if subtitles_override is not None:
            try:
                final_subs = [str(s).strip() for s in subtitles_override if str(s).strip()]
            except Exception:
                final_subs = None
        if final_subs is None:
            final_subs = list(self.detected_subtitles or [])
        if final_subs:
            data["subtitles"] = final_subs
            self._log(f"  Titlovi: {', '.join(final_subs)}")

        if self.screenshot_files:
            ss_b64 = []
            for idx, sf in enumerate(self.screenshot_files[:10]):
                if os.path.exists(sf):
                    ss_b64.append(self._screenshot_b64_compressed(sf))
                self._progress = int((idx + 1) * 30 / min(len(self.screenshot_files), 10))
            ss_b64 = [s for s in ss_b64 if s]
            if ss_b64:
                data["screenshots"] = ss_b64
                _tot = sum(len(s) for s in ss_b64)
                self._log(f"  Screenshots: {len(ss_b64)} (~{_tot/1048576:.1f} MB base64)")

        search_dir = self.item_output_dir or CONFIG["output_dir"]
        nfo_path = os.path.join(search_dir, "info.nfo")
        if os.path.exists(nfo_path):
            data["nfo_file"] = file_to_base64(nfo_path)

        # ─── DIJAGNOSTIKA TORRENTA ───
        # Dekodira i ispisuje kompletnu strukturu torrenta koji se salje
        self._dump_torrent_structure(self.torrent_file, search_dir)

        # Debug: sacuvaj payload (bez base64 fajlova) u debug_upload.json
        debug_data = {k: v for k, v in data.items() if k not in ("torrent_file", "nfo_file", "screenshots")}
        debug_data["_screenshots_count"] = len(data.get("screenshots", []))
        debug_path = os.path.join(search_dir, "debug_upload.json")
        try:
            with open(debug_path, "w", encoding="utf-8") as df:
                json.dump(debug_data, df, ensure_ascii=False, indent=2)
            self._log(f"  Debug payload: {debug_path}")
        except Exception:
            pass

        def _send(payload, label):
            jd = json.dumps(payload).encode("utf-8")
            self._log(f"  [{label}] Velicina zahteva: {len(jd) / 1048576:.2f} MB")
            r = urllib.request.Request(
                "https://www.crnaberza.com/wp-json/cb/v1/upload",
                data=jd, method="POST")
            r.add_header("Content-Type", "application/json; charset=utf-8")
            r.add_header("X-API-Key", CONFIG["cb_api_key"])
            with urllib.request.urlopen(r, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))

        self._log("  Slanje na crnaberza.com...")
        self._progress = 40

        if self._cancel_event.is_set():
            self._log("[WARN] Upload otkazan od strane korisnika")
            raise RuntimeError("Upload otkazan")

        result = None
        try:
            result = _send(data, "1/1")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._log(f"[ERR] HTTP {e.code}: {body}")
            # Ako je 'Invalid torrent file structure' ili 400/413 a saljemo screenshots,
            # verovatno je payload presecen zbog PHP post_max_size. Probaj bez screenshot-ova.
            is_struct_err = ("Invalid torrent" in body) or (e.code in (400, 413))
            if is_struct_err and data.get("screenshots"):
                self._log("  [FALLBACK] Mozda je payload prevelik (PHP limit). Saljem PONOVO bez screenshot-ova...")
                data_no_ss = {k: v for k, v in data.items() if k != "screenshots"}
                try:
                    result = _send(data_no_ss, "fallback bez slika")
                    self._log("  [FALLBACK] Uspelo bez screenshot-ova! Problem je velicina payload-a (server limit).")
                    self._log("  [SAVET] Smanji broj/velicinu screenshot-ova ili povecaj post_max_size/upload_max_filesize na serveru.")
                except urllib.error.HTTPError as e2:
                    body2 = e2.read().decode("utf-8", errors="replace")
                    self._log(f"[ERR] I bez slika HTTP {e2.code}: {body2}")
                except Exception as e2:
                    self._log(f"[ERR] Fallback greska: {e2}")
        except Exception as e:
            self._log(f"[ERR] Upload: {e}")

        if result is not None:
            # Debug: sacuvaj odgovor servera
            try:
                resp_path = os.path.join(search_dir, "debug_response.json")
                with open(resp_path, "w", encoding="utf-8") as rf:
                    json.dump(result, rf, ensure_ascii=False, indent=2)
            except Exception:
                pass

            self._log("[OK] Upload uspesan!")
            self._progress = 60
            torrent_id = result.get("torrent_id")
            self._log(f"  Torent ID:   {torrent_id}")
            self._log(f"  Naziv:       {result.get('name', '')}")
            if result.get("size"):
                self._log(f"  Velicina:    {result['size'] / 1073741824:.2f} GB")
            if result.get("files"):
                self._log(f"  Fajlovi:     {result['files']}")
            if result.get("url"):
                self._log(f"  Pregled:     {result['url']}")
            if result.get("download"):
                self._log(f"  Preuzimanje: {result['download']}")

            # Save to history
            self._save_upload_history({
                "torrent_id": torrent_id,
                "name": result.get("name", name),
                "category": str(category),
                "size": result.get("size", 0),
                "url": result.get("url", ""),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "description": self.generate_description(trailer),
            })

            # Windows notification
            self._notify_windows("Upload zavrsen!", result.get("name", name))

            if torrent_id:
                self._download_and_seed(torrent_id)

    def _download_and_seed(self, torrent_id):
        self._log("\n  Preuzimanje torent fajla sa sajta...")
        try:
            dl_url = f"https://www.crnaberza.com/wp-json/cb/v1/download/{torrent_id}"
            req = urllib.request.Request(dl_url)
            req.add_header("X-API-Key", CONFIG["cb_api_key"])
            with urllib.request.urlopen(req, timeout=30) as resp:
                dl_data = json.loads(resp.read().decode("utf-8"))

            if not dl_data.get("success"):
                self._log("[ERR] Download .torrent nije uspeo")
                return

            torrent_bytes = base64.b64decode(dl_data["torrent_data"])
            filename = dl_data.get("filename", f"torrent_{torrent_id}.torrent")
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

            self._log(f"  Naziv fajla: {filename}")
            self._log(f"  Bajtova: {len(torrent_bytes)}")

            download_path = CONFIG["download_path"]
            os.makedirs(download_path, exist_ok=True)
            final_path = os.path.join(download_path, filename)
            with open(final_path, "wb") as f:
                f.write(torrent_bytes)
            self._log(f"[OK] Torent sacuvan: {final_path}")

            # FTP/SFTP upload if enabled
            if CONFIG.get("ftp_enabled"):
                self._ftp_upload_torrent(final_path, filename)

            self._log("\n  Cekanje 60 sekundi za XBT tracker sinhronizaciju...")
            for i in range(60, 0, -1):
                self._status = f"XBT sync: {i}s preostalo..."
                self._progress = 70 + int((60 - i) * 30 / 60)
                time.sleep(1)
            self._log("  XBT sinhronizacija zavrsena!")
        except Exception as e:
            self._log(f"[ERR] Download/seed: {e}")

    def _ftp_upload_torrent(self, local_path, filename):
        """Upload .torrent file to remote server via FTP or SFTP."""
        protocol = CONFIG.get("ftp_protocol", "sftp")
        host = CONFIG.get("ftp_host", "")
        port = int(CONFIG.get("ftp_port", 22 if protocol == "sftp" else 21))
        user = CONFIG.get("ftp_user", "")
        password = CONFIG.get("ftp_pass", "")
        remote_dir = CONFIG.get("ftp_remote_dir", "/watch")

        if not host or not user:
            self._log("[ERR] FTP/SFTP: host i korisnik moraju biti podeseni")
            return

        remote_path = f"{remote_dir.rstrip('/')}/{filename}"
        self._log(f"\n  {protocol.upper()} upload: {filename} -> {host}:{remote_path}")

        try:
            if protocol == "sftp":
                self._sftp_upload(host, port, user, password, local_path, remote_path)
            else:
                self._ftp_upload(host, port, user, password, local_path, remote_path)
            self._log(f"[OK] {protocol.upper()} upload zavrsen!")
        except Exception as e:
            self._log(f"[ERR] {protocol.upper()} upload: {e}")

    def _sftp_upload(self, host, port, user, password, local_path, remote_path):
        """Upload via SFTP using paramiko."""
        try:
            import paramiko
        except ImportError:
            self._log("  paramiko nije instaliran, koristim subprocess ssh...")
            self._sftp_upload_subprocess(host, port, user, password, local_path, remote_path)
            return
        transport = paramiko.Transport((host, port))
        try:
            transport.connect(username=user, password=password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            try:
                sftp.put(local_path, remote_path)
            finally:
                sftp.close()
        finally:
            transport.close()

    def _sftp_upload_subprocess(self, host, port, user, password, local_path, remote_path):
        """Fallback SFTP via scp/sftp command."""
        # Try using built-in Windows OpenSSH scp
        scp_cmd = ["scp", "-P", str(port), "-o", "StrictHostKeyChecking=no",
                   local_path, f"{user}@{host}:{remote_path}"]
        self._log(f"  Pokretanje: scp -P {port} ... {user}@{host}:{remote_path}")
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60,
                                env={**os.environ, "SSHPASS": password})
        if result.returncode != 0:
            raise RuntimeError(f"scp greska: {result.stderr.strip()}")

    def _ftp_upload(self, host, port, user, password, local_path, remote_path):
        """Upload via FTP using ftplib."""
        import ftplib
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=30)
        try:
            ftp.login(user, password)
            remote_dir = '/'.join(remote_path.split('/')[:-1])
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except ftplib.error_perm:
                    ftp.mkd(remote_dir)
                    ftp.cwd(remote_dir)
            with open(local_path, 'rb') as f:
                ftp.storbinary(f'STOR {remote_path.split("/")[-1]}', f)
        finally:
            ftp.quit()

    def get_cleanup_files(self):
        """Return list of files that can be deleted after upload."""
        if not self.item_output_dir or not os.path.isdir(self.item_output_dir):
            return []
        files = []
        # Screenshots folder
        ss_dir = os.path.join(self.item_output_dir, "screenshots")
        if os.path.isdir(ss_dir):
            ss_count = len(list(Path(ss_dir).glob("*.jpg")))
            if ss_count > 0:
                files.append({"path": ss_dir, "display": f"Screenshots folder ({ss_count} fajlova)", "type": "screenshots",
                              "default_delete": CONFIG.get("cleanup_delete_screenshots", True)})
        # Mediainfo
        mi = os.path.join(self.item_output_dir, "mediainfo.txt")
        if os.path.exists(mi):
            files.append({"path": mi, "display": "mediainfo.txt", "type": "mediainfo",
                          "default_delete": CONFIG.get("cleanup_delete_mediainfo", True)})
        # Torrent file
        for tf in Path(self.item_output_dir).glob("*.torrent"):
            files.append({"path": str(tf), "display": tf.name, "type": "torrent",
                          "default_delete": CONFIG.get("cleanup_delete_torrent", False)})
        # NFO
        nfo = os.path.join(self.item_output_dir, "info.nfo")
        if os.path.exists(nfo):
            files.append({"path": nfo, "display": "info.nfo", "type": "nfo",
                          "default_delete": CONFIG.get("cleanup_delete_nfo", True)})
        # IMDB txt
        imdb = os.path.join(self.item_output_dir, "imdb.txt")
        if os.path.exists(imdb):
            files.append({"path": imdb, "display": "imdb.txt", "type": "imdb",
                          "default_delete": CONFIG.get("cleanup_delete_imdb", True)})
        # Manual metadata
        mm = os.path.join(self.item_output_dir, "manual_meta.json")
        if os.path.exists(mm):
            files.append({"path": mm, "display": "manual_meta.json", "type": "imdb",
                          "default_delete": CONFIG.get("cleanup_delete_imdb", True)})        # Debug files
        for dbg in ("debug_upload.json", "debug_response.json"):
            dp = os.path.join(self.item_output_dir, dbg)
            if os.path.exists(dp):
                files.append({"path": dp, "display": dbg, "type": "nfo",
                              "default_delete": True})
        return files

    def cleanup_files(self, paths):
        """Delete specified files/folders."""
        deleted = 0
        for p in paths:
            try:
                if os.path.isdir(p):
                    import shutil
                    shutil.rmtree(p)
                    deleted += 1
                    self._log(f"[DEL] {p}")
                elif os.path.exists(p):
                    os.remove(p)
                    deleted += 1
                    self._log(f"[DEL] {p}")
            except Exception as e:
                self._log(f"[ERR] Brisanje {p}: {e}")
        # Remove output dir if empty
        if self.item_output_dir and os.path.isdir(self.item_output_dir):
            try:
                remaining = list(Path(self.item_output_dir).iterdir())
                if not remaining:
                    os.rmdir(self.item_output_dir)
                    self._log(f"[DEL] Prazan folder obrisan: {self.item_output_dir}")
            except Exception:
                pass
        return {"message": f"Obrisano {deleted} stavki"}

    def generate_description(self, trailer=""):
        """Generate BBCode description for manual editing on site."""
        title_line = ""
        if self.tmdb_title:
            t = self.tmdb_title
            if self.tmdb_year:
                t += f" ({self.tmdb_year})"
            title_line = f"[center][b][size=24]{t}[/size][/b][/center]\n\n"

        overview = self.tmdb_overview or ""
        desc = f"{title_line}{overview}" if overview else title_line

        if trailer:
            vid = trailer.strip()
            m = re.search(r"(?:v=|youtu\.be/)([\w-]+)", vid)
            if m:
                vid = m.group(1)
            desc += f"\n\n[youtube]{vid}[/youtube]"
        elif CONFIG.get("auto_youtube_trailer", True) and self.tmdb_title:
            try:
                import fetch_trailer
                query = f"{self.tmdb_title} {self.tmdb_year or ''} official trailer".strip()
                self._log(f"  [Trailer] Trazim na YouTube-u: '{query}'...")
                found_trailer = fetch_trailer.search_youtube(query, self.tmdb_title)
                if found_trailer:
                    vid = found_trailer.strip()
                    m = re.search(r"(?:v=|youtu\.be/)([\w-]+)", vid)
                    if m:
                        vid = m.group(1)
                    desc += f"\n\n[youtube]{vid}[/youtube]"
                    self._log(f"  [Trailer] Nadjen: https://youtube.com/watch?v={vid}")
                else:
                    self._log("  [Trailer] Nije nadjen.")
            except Exception as e:
                self._log(f"  [Trailer ERR] Neuspelo trazenje: {e}")

        return desc.strip() or "."

    def copy_to_clipboard(self, text):
        """Copy text to system clipboard."""
        try:
            import subprocess
            p = subprocess.Popen(['clip'], stdin=subprocess.PIPE, shell=True)
            p.communicate(text.encode('utf-16-le'))
            return True
        except Exception:
            return False

    def get_upload_history(self):
        """Load upload history from JSON file."""
        if not os.path.exists(HISTORY_FILE):
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def delete_history_item(self, index):
        """Delete a single entry from upload history by index."""
        history = self.get_upload_history()
        if 0 <= index < len(history):
            history.pop(index)
            try:
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(history, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        return True

    def _save_upload_history(self, entry):
        """Append an entry to upload history."""
        history = self.get_upload_history()
        history.append(entry)
        # Keep last 200 entries
        if len(history) > 200:
            history = history[-200:]
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_stats(self):
        """Get upload statistics from history."""
        history = self.get_upload_history()
        total = len(history)
        total_bytes = sum(h.get("size", 0) for h in history)
        total_gb = total_bytes / 1073741824 if total_bytes else 0
        last_date = history[-1].get("date", "-") if history else "-"
        return {
            "total": total,
            "total_size": f"{total_gb:.1f} GB",
            "last_date": last_date,
        }

    def export_history(self, fmt):
        """Export upload history as JSON or CSV."""
        history = self.get_upload_history()
        if not history:
            return None
        if fmt == "csv":
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["ID", "Naziv", "Kategorija", "Velicina", "Datum", "URL"])
            for h in history:
                size_gb = f"{h.get('size', 0) / 1073741824:.2f} GB" if h.get("size") else ""
                writer.writerow([
                    h.get("torrent_id", ""),
                    h.get("name", ""),
                    h.get("category", ""),
                    size_gb,
                    h.get("date", ""),
                    h.get("url", ""),
                ])
            return {
                "content": output.getvalue(),
                "filename": "crnaberza_history.csv",
                "mime": "text/csv",
            }
        else:
            return {
                "content": json.dumps(history, ensure_ascii=False, indent=2),
                "filename": "crnaberza_history.json",
                "mime": "application/json",
            }

    def check_for_update(self):
        """Check GitHub releases for a newer version."""
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "CrnaBerza-Upload-Tool")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            current = APP_VERSION
            try:
                latest_t = tuple(int(x) for x in latest.split("."))
                current_t = tuple(int(x) for x in current.split("."))
                is_newer = latest_t > current_t
            except (ValueError, AttributeError):
                is_newer = False
            if latest and is_newer:
                dl_url = data.get("html_url", "")
                return {
                    "update_available": True,
                    "latest_version": latest,
                    "current_version": current,
                    "download_url": dl_url,
                }
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as e:
            print(f"[Update] GitHub provjera nije uspjela: {e}")
        return {"update_available": False, "current_version": APP_VERSION}

    @staticmethod
    def _notify_windows(title, message):
        """Show Windows 10/11 toast notification."""
        try:
            from ctypes import windll
            # Use PowerShell for toast notification
            ps_cmd = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) > $null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Crna Berza Tools v2.0 by Vucko").Show($toast)
            '''
            subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                             creationflags=0x08000000)  # CREATE_NO_WINDOW
        except Exception:
            pass

    def fetch_categories(self):
        if not CONFIG["cb_api_key"]:
            return {"error": "CB API kljuc nije podesen!"}
        try:
            url = "https://www.crnaberza.com/wp-json/cb/v1/categories"
            req = urllib.request.Request(url)
            req.add_header("X-API-Key", CONFIG["cb_api_key"])
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # Server vraca {success:true, categories:[...]}; extract list if present
            if isinstance(data, dict) and "categories" in data:
                cats = data.get("categories")
            else:
                cats = data
            return {"categories": cats}
        except Exception as e:
            return {"error": str(e)}

    # ─── Queue persistence ──────────────────────────────────────────

    def queue_get(self):
        """Return queue items list from disk."""
        try:
            qf = os.path.join(DATA_DIR, "queue.json")
            if os.path.exists(qf):
                with open(qf, "r", encoding="utf-8") as f:
                    items = json.load(f)
                if isinstance(items, list):
                    return items
        except Exception as e:
            print(f"[WARN] queue_get: {e}")
        return []

    def queue_save(self, items):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            qf = os.path.join(DATA_DIR, "queue.json")
            with open(qf, "w", encoding="utf-8") as f:
                json.dump(items or [], f, ensure_ascii=False, indent=2)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── File pickers for software/programs upload ──────────────────

    def browse_any_file(self):
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('Svi fajlovi (*.*)',))
        if result and len(result):
            return result[0]
        return None

    def browse_image_files(self):
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=('Slike (*.jpg;*.jpeg;*.png;*.webp;*.gif)', 'Svi fajlovi (*.*)'))
        return list(result) if result else []

    def browse_nfo_file(self):
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=('NFO/Tekst (*.nfo;*.txt)', 'Svi fajlovi (*.*)'))
        if result and len(result):
            return result[0]
        return None

    # ─── Software / Programs upload (no IMDB) ───────────────────────

    def sw_make_torrent(self, path):
        """Create a .torrent for any path (folder or file). Returns path/error."""
        try:
            is_remote = path.startswith("sftp://")
            actual_path = path[7:] if is_remote else path
            
            if not is_remote and not os.path.exists(actual_path):
                return {"ok": False, "error": "Putanja ne postoji"}

            item_name = os.path.basename(os.path.normpath(actual_path))
            stem = os.path.splitext(item_name)[0] if (not is_remote and os.path.isfile(actual_path)) else item_name
            out_dir = os.path.join(CONFIG["output_dir"], stem)
            os.makedirs(out_dir, exist_ok=True)
            output_file = os.path.join(out_dir, f"{item_name}.torrent")
            if os.path.exists(output_file):
                os.remove(output_file)

            self._log(f"  Kreiranje torrenta: {item_name}")

            if is_remote:
                host = CONFIG.get("ftp_host", "")
                port = int(CONFIG.get("ftp_port", 22))
                user = CONFIG.get("ftp_user", "")
                password = CONFIG.get("ftp_pass", "")
                if not host or not user:
                    return {"ok": False, "error": "Podesite SFTP u Podesavanjima"}
                import paramiko, shlex
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(hostname=host, port=port, username=user, password=password, timeout=30)
                try:
                    rq = shlex.quote(actual_path)
                    announce = shlex.quote(CONFIG["announce_url"])
                    tmp_remote = f"/tmp/cb_{int(time.time())}"
                    client.exec_command(f"mkdir -p {tmp_remote}")[1].read()
                    trt_remote = f"{tmp_remote}/{item_name}.torrent"

                    _, sout, _ = client.exec_command(
                        "if command -v mktorrent >/dev/null 2>&1; then echo mktorrent; "
                        "elif command -v torrenttools >/dev/null 2>&1; then echo torrenttools; "
                        "else echo NONE; fi"
                    )
                    tool = ([l for l in (sout.read().decode("utf-8") if sout else "").splitlines() if l.strip()] or ["NONE"])[-1].strip()
                    if tool == "NONE":
                        return {"ok": False, "error": "mktorrent ili torrenttools nije pronadjen na serveru"}
                    
                    if tool == "torrenttools":
                        cmd = f"torrenttools create --announce {announce} --private --output {shlex.quote(trt_remote)} {rq}"
                    else:
                        cmd = f"mktorrent -p -a {announce} -o {shlex.quote(trt_remote)} {rq}"

                    self._log(f"  Pokrecem: {tool} na remote serveru")
                    client.exec_command(cmd)[1].read() # wait
                    
                    sftp = client.open_sftp()
                    try:
                        sftp.get(trt_remote, output_file)
                    except Exception as e:
                        return {"ok": False, "error": f"Nije uspelo preuzimanje torrenta: {e}"}
                    finally:
                        sftp.close()
                    client.exec_command(f"rm -rf {tmp_remote}")
                finally:
                    client.close()

                if not os.path.exists(output_file):
                    return {"ok": False, "error": "Remote torrent fajl nije sacuvan lokalno"}

            else:
                tt_exe = get_torrenttools_path()
                if not tt_exe:
                    return {"ok": False, "error": "torrenttools nije pronadjen"}
                cmd = [tt_exe, "create", "--announce", CONFIG["announce_url"],
                       "--private", "--output", output_file]
                exp, est_pieces = self._compute_piece_length(actual_path)
                if exp:
                    piece_bytes = 1 << exp
                    psize = f"{piece_bytes // 1048576}M" if piece_bytes >= 1048576 else f"{piece_bytes // 1024}K"
                    cmd += ["--piece-size", psize]
                    self._log(f"  Velicina komada: {psize} (~{est_pieces} komada)")
                cmd.append(actual_path)
                res = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=900, creationflags=NO_WINDOW)
                if not os.path.exists(output_file):
                    return {"ok": False, "error": (res.stderr or res.stdout or "torrenttools nije kreirao fajl").strip()[:300]}

            return {"ok": True, "torrent_file": output_file}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sw_upload(self, payload):
        """Upload non-video content (game/software/music/other) without TMDB."""
        try:
            if not CONFIG.get("cb_api_key"):
                return {"ok": False, "error": "CB API kljuc nije podesen"}
            path = (payload.get("path") or "").strip()
            name = (payload.get("name") or "").strip()
            category = payload.get("category")
            if not path or not name or not category:
                return {"ok": False, "error": "path, name i category su obavezni"}
            is_remote = path.startswith("sftp://")
            if not is_remote and not os.path.exists(path):
                return {"ok": False, "error": "Putanja ne postoji"}

            # Make sure torrent exists - reuse if same item folder, else create
            actual_path = path[7:] if is_remote else path
            item_name = os.path.basename(os.path.normpath(actual_path))
            stem = os.path.splitext(item_name)[0] if (not is_remote and os.path.isfile(actual_path)) else item_name
            out_dir = os.path.join(CONFIG["output_dir"], stem)
            os.makedirs(out_dir, exist_ok=True)
            torrent_file = os.path.join(out_dir, f"{item_name}.torrent")
            if not os.path.exists(torrent_file):
                self._log("  Torrent ne postoji, kreiram ga...")
                r = self.sw_make_torrent(path)
                if not r.get("ok"):
                    return {"ok": False, "error": "Torrent: " + r.get("error", "")}
                torrent_file = r["torrent_file"]

            # Validacija torrenta pre slanja
            v_ok, v_msg = validate_torrent_file(torrent_file)
            if not v_ok:
                return {"ok": False, "error": f"Torrent nije validan: {v_msg}"}
            self._log(f"  Torrent validan: {v_msg}")
            # Normalizuj u kanonski bencode
            n_ok, n_msg = normalize_torrent(torrent_file, self._log)
            self._log(f"  Torrent normalizacija: {n_msg if n_ok else '[WARN] ' + n_msg}")

            url_val = payload.get("url") or ""
            if not url_val:
                url_val = "https://www.imdb.com/title/tt0000000/"

            # Build upload payload
            data = {
                "torrent_file": file_to_base64(torrent_file),
                "name": name,
                "description": payload.get("description") or "",
                "autoOpis": False,
                "category": int(category),
                "url": url_val,
                "anonymous": bool(payload.get("anonymous")),
                "allow_comments": payload.get("allow_comments", True),
            }

            # Optional NFO
            nfo_path = (payload.get("nfo_path") or "").strip()
            if nfo_path and os.path.exists(nfo_path):
                data["nfo_file"] = file_to_base64(nfo_path)

            # Optional images as screenshots (max 10, max 5MB each)
            images = payload.get("images") or []
            if images:
                ss_b64 = []
                for img in images[:10]:
                    if not os.path.exists(img):
                        continue
                    if os.path.getsize(img) > 5 * 1048576:
                        self._log(f"  [WARN] Preskocena (>5MB): {os.path.basename(img)}")
                        continue
                    ss_b64.append(file_to_base64(img))
                if ss_b64:
                    data["screenshots"] = ss_b64

            json_data = json.dumps(data).encode("utf-8")
            self._log(f"  Velicina zahteva: {len(json_data) / 1048576:.1f} MB")
            self._log("  Slanje na crnaberza.com...")

            req = urllib.request.Request(
                "https://www.crnaberza.com/wp-json/cb/v1/upload",
                data=json_data, method="POST")
            req.add_header("Content-Type", "application/json; charset=utf-8")
            req.add_header("X-API-Key", CONFIG["cb_api_key"])

            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            torrent_id = result.get("torrent_id")
            url_view = result.get("url", "")
            self._log("[OK] Upload uspesan!")
            self._log(f"  ID: {torrent_id}")
            if url_view:
                self._log(f"  Pregled: {url_view}")

            # Save to history
            cat_label = payload.get("category_name") or str(category)
            self._save_upload_history({
                "torrent_id": torrent_id,
                "name": result.get("name", name),
                "category": f"{category} ({cat_label})" if payload.get("category_name") else str(category),
                "size": result.get("size", 0),
                "url": url_view,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "description": data["description"],
            })
            self._notify_windows("Upload zavrsen!", result.get("name", name))

            if torrent_id:
                # Reuse existing _download_and_seed flow
                threading.Thread(target=self._download_and_seed,
                                 args=(torrent_id,), daemon=True).start()

            return {"ok": True, "torrent_id": torrent_id, "url": url_view}

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"HTTP {e.code}: {body[:300]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── Site queue API (zahtevi) ───────────────────────────────────

    def requests_fetch(self, status="pending"):
        """GET /wp-json/cb/v1/queue."""
        if not CONFIG.get("cb_api_key"):
            return {"ok": False, "error": "CB API kljuc nije podesen"}
        try:
            url = f"https://www.crnaberza.com/wp-json/cb/v1/queue?status={urllib.parse.quote(status)}"
            req = urllib.request.Request(url)
            req.add_header("X-API-Key", CONFIG["cb_api_key"])
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success"):
                return {"ok": False, "error": "API success=false"}
            return {"ok": True, "items": data.get("items", []), "count": data.get("count", 0)}
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def requests_update(self, item_id, status, notes=""):
        """POST /wp-json/cb/v1/queue/{id}."""
        if not CONFIG.get("cb_api_key"):
            return {"ok": False, "error": "CB API kljuc nije podesen"}
        try:
            payload = {"status": status}
            if notes:
                payload["notes"] = notes
            data = json.dumps(payload).encode("utf-8")
            url = f"https://www.crnaberza.com/wp-json/cb/v1/queue/{int(item_id)}"
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("X-API-Key", CONFIG["cb_api_key"])
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return {"ok": bool(result.get("success")), "result": result}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"HTTP {e.code}: {body[:200]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── Remote SFTP browser ────────────────────────────────────────

    def sftp_list(self, remote_path="/"):
        """List a directory on the configured SFTP server."""
        try:
            host = CONFIG.get("ftp_host", "")
            port = int(CONFIG.get("ftp_port", 22))
            user = CONFIG.get("ftp_user", "")
            password = CONFIG.get("ftp_pass", "")
            if not host or not user:
                return {"ok": False, "error": "Podesite SFTP u Podesavanjima"}
            try:
                import paramiko
            except ImportError:
                return {"ok": False, "error": "paramiko nije dostupan"}

            transport = paramiko.Transport((host, port))
            try:
                transport.connect(username=user, password=password)
                sftp = paramiko.SFTPClient.from_transport(transport)
                try:
                    p = remote_path or "/"
                    if not p.startswith("/"):
                        p = "/" + p
                    entries = []
                    for attr in sftp.listdir_attr(p):
                        is_dir = bool(attr.st_mode and (attr.st_mode & 0o040000))
                        full = (p.rstrip("/") + "/" + attr.filename) if p != "/" else "/" + attr.filename
                        entries.append({
                            "name": attr.filename,
                            "path": full,
                            "dir": is_dir,
                            "size": attr.st_size or 0,
                        })
                    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
                    return {"ok": True, "path": p, "entries": entries}
                finally:
                    sftp.close()
            finally:
                transport.close()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sftp_run_remote(self, remote_path):
        """Run mediainfo + ffmpeg screenshots + torrenttools ON the remote server,
        then download just the small artifacts (screenshots, mediainfo, torrent).
        Returns dict with local paths or error.
        Pretpostavlja: ffmpeg, ffprobe, mediainfo, torrenttools instalirani na serveru."""
        try:
            host = CONFIG.get("ftp_host", "")
            port = int(CONFIG.get("ftp_port", 22))
            user = CONFIG.get("ftp_user", "")
            password = CONFIG.get("ftp_pass", "")
            if not host or not user:
                return {"ok": False, "error": "Podesite SFTP u Podesavanjima"}
            import paramiko, shlex

            self._log(f"\n═══ REMOTE OBRADA: {remote_path} ═══")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=host, port=port, username=user, password=password,
                           timeout=30, banner_timeout=30)
            try:
                # Determine target path (folder or file)
                rp = remote_path
                # Quote for shell
                rq = shlex.quote(rp)
                # Find largest video if folder
                self._log("  Trazim glavni video fajl na serveru...")
                cmd_find = f'if [ -d {rq} ]; then find {rq} -type f \\( -iname "*.mkv" -o -iname "*.mp4" -o -iname "*.avi" -o -iname "*.m2ts" -o -iname "*.mov" \\) -printf "%s %p\\n" | sort -nr | head -1 | cut -d" " -f2-; else echo {rq}; fi'
                _, sout, _ = client.exec_command(cmd_find)
                video = sout.read().decode("utf-8").strip()
                if not video:
                    return {"ok": False, "error": "Nije pronadjen video fajl na serveru"}
                self._log(f"  Video: {video}")

                vq = shlex.quote(video)
                # Make remote tmp folder
                tmp_remote = f"/tmp/cb_{int(time.time())}"
                client.exec_command(f"mkdir -p {tmp_remote}")[1].read()

                # Mediainfo
                self._log("  MediaInfo na serveru...")
                _, sout, serr = client.exec_command(f"mediainfo {vq}")
                mediainfo_text = sout.read().decode("utf-8", errors="replace")

                # Duration via ffprobe
                _, sout, _ = client.exec_command(
                    f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {vq}')
                try:
                    duration = float(sout.read().decode("utf-8").strip())
                except Exception:
                    duration = 0
                self._log(f"  Trajanje: {duration:.1f}s")

                # Generate 10 screenshots remote
                count = CONFIG.get("screenshot_count", 10)
                start_t = duration * (CONFIG.get("skip_start_percent", 5) / 100)
                end_t = duration * (1 - CONFIG.get("skip_end_percent", 5) / 100)
                interval = (end_t - start_t) / (count + 1) if count else 0
                self._log(f"  Generisanje {count} screenshot-ova na serveru...")
                for i in range(1, count + 1):
                    ts = start_t + interval * i
                    out_remote = f"{tmp_remote}/ss_{i:02d}.jpg"
                    cmd = f'ffmpeg -y -ss {ts:.2f} -i {vq} -vframes 1 -q:v 2 -update 1 {shlex.quote(out_remote)} 2>/dev/null'
                    client.exec_command(cmd)[1].read()  # wait

                # Torrent on server - autodetect available tool
                announce_url = CONFIG["announce_url"]
                announce = shlex.quote(announce_url)
                tname = os.path.basename(rp.rstrip("/")) or "remote"
                trt_remote = f"{tmp_remote}/{tname}.torrent"
                self._log("  Provera dostupnih torrent alata na serveru...")
                # Prioritet: mktorrent (cist v1) > torrenttools (v1) > transmission-create (pravi v2/hybrid!)
                _, sout, _ = client.exec_command(
                    "if command -v mktorrent >/dev/null 2>&1; then echo mktorrent; "
                    "elif command -v torrenttools >/dev/null 2>&1; then echo torrenttools; "
                    "elif command -v transmission-create >/dev/null 2>&1; then echo transmission-create; "
                    "else echo NONE; fi"
                )
                tool_out = sout.read().decode("utf-8").strip() if sout else ""
                # Take last non-empty line just in case
                tool = ([l for l in tool_out.splitlines() if l.strip()] or ["NONE"])[-1].strip()
                self._log(f"  Detektovan alat: {tool}")

                # Izracunaj ukupnu velicinu i optimalan piece-size eksponent (manji torrent fajl)
                _, sz_out2, _ = client.exec_command(f"du -sb {rq} 2>/dev/null | cut -f1")
                try:
                    total_bytes = int(sz_out2.read().decode("utf-8").strip() or "0")
                except Exception:
                    total_bytes = 0
                pexp = 18  # 256 KiB default
                if total_bytes > 0:
                    ideal = total_bytes / 1500.0
                    pexp = 18
                    while (1 << pexp) < ideal and pexp < 25:  # do 32 MiB
                        pexp += 1
                est_pieces = -(-total_bytes // (1 << pexp)) if total_bytes else 0
                self._log(f"  Ukupno: {total_bytes/1073741824:.2f} GB, piece-size: {(1<<pexp)//1024} KiB (~{est_pieces} komada)")

                if tool == "torrenttools":
                    self._log("  Koristim: torrenttools")
                    pb = 1 << pexp
                    psize = f"{pb//1048576}M" if pb >= 1048576 else f"{pb//1024}K"
                    cmd = f"torrenttools create --announce {announce} --private --piece-size {psize} --output {shlex.quote(trt_remote)} {rq}"
                elif tool == "mktorrent":
                    self._log("  Koristim: mktorrent")
                    # mktorrent: -p = private, -a announce, -o output, -l = piece length eksponent (power of 2)
                    cmd = f"mktorrent -p -l {pexp} -a {announce} -o {shlex.quote(trt_remote)} {rq}"
                elif tool == "transmission-create":
                    self._log("  Koristim: transmission-create")
                    pb = 1 << pexp
                    # transmission-create: -s velicina komada u KiB
                    cmd = f"transmission-create -p -s {pb//1024} -t {announce} -o {shlex.quote(trt_remote)} {rq}"
                else:
                    return {"ok": False, "error": (
                        "Na serveru nije pronadjen nijedan torrent alat. "
                        "Instalirajte JEDNO od: torrenttools, mktorrent, ili transmission-create. "
                        "Najjednostavnije: 'sudo apt install -y mktorrent'"
                    )}

                self._log("  Kreiranje torrenta na serveru...")
                # Ukloni eventualni postojeci fajl (mktorrent puca ako vec postoji)
                client.exec_command(f"rm -f {shlex.quote(trt_remote)}")[1].read()
                stdin_, sout_, serr_ = client.exec_command(cmd)
                # Drain both streams so process completes
                _stdout = sout_.read().decode("utf-8", errors="replace") if sout_ else ""
                err_out = serr_.read().decode("utf-8", errors="replace") if serr_ else ""
                if err_out.strip():
                    self._log(f"  [WARN] Torrent stderr: {err_out.strip()[:200]}")
                # Provera da fajl postoji i nije prazan na serveru
                _, sz_out, _ = client.exec_command(
                    f"stat -c %s {shlex.quote(trt_remote)} 2>/dev/null || echo 0")
                try:
                    remote_size = int(sz_out.read().decode("utf-8").strip() or "0")
                except Exception:
                    remote_size = 0
                if remote_size <= 0:
                    return {"ok": False, "error": (
                        f"Alat '{tool}' nije kreirao torrent fajl na serveru. "
                        f"Stderr: {err_out.strip()[:200] if err_out.strip() else '(prazan)'}. "
                        f"Proverite da '{tool}' radi rucno na serveru."
                    )}
                self._log(f"  Torrent na serveru: {remote_size} bajtova")

                # Download artifacts
                sftp = client.open_sftp()
                try:
                    item_name = os.path.basename(rp.rstrip("/")) or "remote"
                    if "." in item_name and not os.path.isdir(rp):
                        stem = os.path.splitext(item_name)[0]
                    else:
                        stem = item_name
                    local_dir = os.path.join(CONFIG["output_dir"], stem)
                    os.makedirs(local_dir, exist_ok=True)
                    ss_local_dir = os.path.join(local_dir, "screenshots")
                    os.makedirs(ss_local_dir, exist_ok=True)
                    # screenshots
                    for i in range(1, count + 1):
                        rfile = f"{tmp_remote}/ss_{i:02d}.jpg"
                        lfile = os.path.join(ss_local_dir, f"screenshot_{i:02d}.jpg")
                        try:
                            sftp.get(rfile, lfile)
                        except Exception:
                            pass
                    # mediainfo
                    mi_local = os.path.join(local_dir, "mediainfo.txt")
                    with open(mi_local, "w", encoding="utf-8") as f:
                        f.write(mediainfo_text)
                    # torrent
                    trt_local = os.path.join(local_dir, f"{tname}.torrent")
                    try:
                        sftp.get(trt_remote, trt_local)
                    except Exception as ge:
                        sftp.close()
                        return {"ok": False, "error": (
                            f"Torrent nije napravljen na serveru ({tool}). "
                            f"Greska pri preuzimanju: {ge}. "
                            f"Stderr: {err_out.strip()[:150] if err_out.strip() else '(prazan)'}"
                        )}
                finally:
                    sftp.close()

                # Cleanup remote tmp
                client.exec_command(f"rm -rf {shlex.quote(tmp_remote)}")[1].read()

                # Validacija preuzetog torrenta
                v_ok, v_msg = validate_torrent_file(trt_local)
                if not v_ok:
                    return {"ok": False, "error": (
                        f"Torrent napravljen sa '{tool}' nije validan: {v_msg}. "
                        f"Pokusajte drugi alat (npr. mktorrent) ili proverite da li je '{video}' kompletan."
                    )}
                self._log(f"  Torrent validan: {v_msg}")
                # Normalizuj u kanonski bencode (resava odbijanje od sajta)
                n_ok, n_msg = normalize_torrent(trt_local, self._log)
                self._log(f"  Torrent normalizacija: {n_msg if n_ok else '[WARN] ' + n_msg}")

                # Set state
                self.item_output_dir = local_dir
                self.source_path = rp
                self.mediainfo_text = mediainfo_text
                self.torrent_file = trt_local
                self.screenshot_files = sorted(
                    str(f) for f in Path(ss_local_dir).glob("*.jpg")
                )
                width_match = re.search(r'Width\s*:\s*(\d[\d\s]*)', mediainfo_text or "")
                if width_match:
                    width = int(width_match.group(1).replace(' ', ''))
                    self.is_hd = width >= 1280

                self._log(f"[OK] Remote obrada zavrsena. {len(self.screenshot_files)} screenshot-ova.")
                return {"ok": True, "local_dir": local_dir,
                        "screenshots": len(self.screenshot_files),
                        "torrent_file": trt_local}
            finally:
                client.close()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── Tool Download ────────────────────────────────────────────────

    def _do_download(self, tool_name):
        info = TOOL_INFO.get(tool_name)
        if not info:
            return
        url = info["url"]
        dest_dir = os.path.join(TOOLS_DIR, tool_name)
        os.makedirs(dest_dir, exist_ok=True)
        zip_filename = url.split("/")[-1]

        self._tlog(f"\n{'─' * 40}")
        self._tlog(f"Preuzimanje: {tool_name}")

        tmp_dir = tempfile.mkdtemp(prefix="cb_")
        zip_path = os.path.join(tmp_dir, zip_filename)

        try:
            def on_progress(pct, dl, total):
                self._tlog(f"  {pct}% ({dl / 1048576:.1f} / {total / 1048576:.1f} MB)")

            self._tlog("  Preuzimanje fajla u temp folder...")
            download_with_progress(url, zip_path, on_progress)

            if not os.path.exists(zip_path):
                self._tlog("[ERR] Download nije uspeo")
                return

            self._tlog(f"  Preuzeto: {os.path.getsize(zip_path) / 1048576:.1f} MB")
            self._tlog("  Raspakivanje...")

            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir)
            os.makedirs(dest_dir, exist_ok=True)

            if zip_path.lower().endswith(".msi"):
                subprocess.run(
                    f'msiexec /a "{zip_path}" /qn TARGETDIR="{dest_dir}"',
                    shell=True, timeout=120, creationflags=NO_WINDOW)
            elif zip_path.lower().endswith(".7z"):
                subprocess.run(
                    ["tar", "-xf", zip_path, "-C", dest_dir],
                    timeout=120, creationflags=NO_WINDOW, check=True)
            elif zip_path.lower().endswith(".exe"):
                subprocess.run(
                    [zip_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", f"/DIR={dest_dir}"],
                    timeout=120, creationflags=NO_WINDOW)
            else:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(dest_dir)

            for leftover in Path(dest_dir).glob("*.msi"):
                try:
                    leftover.unlink()
                except Exception:
                    pass
            self._tlog(f"[OK] {tool_name} instaliran!")
            save_tool_version(tool_name, TOOL_INFO[tool_name]["version"])

        except Exception as e:
            self._tlog(f"[ERR] {tool_name}: {e}")
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def _build_html(init_data_json):
    ui_dir = _ui_bundle_dir()
    html = HTML_TEMPLATE
    html = html.replace("__BOOTSTRAP_CSS__", "vendor/bootstrap/css/bootstrap.min.css")
    html = html.replace("__BOOTSTRAP_ICONS_CSS__", "vendor/bootstrap-icons/bootstrap-icons.min.css")
    html = html.replace("__BOOTSTRAP_JS__", "vendor/bootstrap/js/bootstrap.bundle.min.js")
    html = html.replace("</head>", f"<script>var INIT_DATA={init_data_json};</script></head>", 1)
    html_path = os.path.join(ui_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return Path(html_path).resolve().as_uri()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    # Clean up leftover .old.* tool dirs from previous locked-file renames
    _pytools = os.path.join(TOOLS_DIR, "py") if os.path.isdir(os.path.join(TOOLS_DIR, "py")) else None
    if _pytools:
        for _d in os.listdir(_pytools):
            if ".old." in _d:
                try: shutil.rmtree(os.path.join(_pytools, _d), ignore_errors=True)
                except: pass
    # ─── Splash Screen (threaded tkinter) ───
    import tkinter as tk
    def _run_splash():
        s = tk.Tk()
        s.overrideredirect(True)
        sw, sh = 340, 120
        sx = (s.winfo_screenwidth() - sw) // 2
        sy = (s.winfo_screenheight() - sh) // 2
        s.geometry(f"{sw}x{sh}+{sx}+{sy}")
        s.configure(bg="#0f1923")
        s.attributes("-topmost", True)
        tk.Label(s, text="Crna Berza Tools", font=("Segoe UI", 22, "bold"), fg="#10b981", bg="#0f1923").pack(pady=(18, 2))
        tk.Label(s, text="Program se ucitava...", font=("Segoe UI", 11), fg="#8899aa", bg="#0f1923").pack()
        s.after(5000, s.destroy)
        s.mainloop()
    _splash_t = threading.Thread(target=_run_splash, daemon=True)
    _splash_t.start()

    # Wire previously installed python-tools dirs onto sys.path so their imports resolve
    _ensure_all_py_tools_on_path()

    api = Api()
    # Pre-gather init data and embed in HTML so JS never calls Python at startup
    _init_history = []
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                _init_history = json.load(f)
    except Exception:
        pass
    _init_total = len(_init_history)
    _init_bytes = sum(h.get('size', 0) for h in _init_history)
    _init_gb = _init_bytes / 1073741824 if _init_bytes else 0
    _init_last = _init_history[-1].get('date', '-') if _init_history else '-'
    # Only cheap filesystem checks at startup - avoid importing ffsubsync/autosubsync here
    # (heavy numpy/scipy imports caused 5-10s UI lag). JS will call check_tools_status() async after load.
    _init_tools = {
        'ffmpeg': get_ffmpeg_path() or '',
        'mediainfo': get_mediainfo_path() or '',
        'torrenttools': get_torrenttools_path() or '',
    }
    _init_data = json.dumps({
        'config': dict(CONFIG),
        'tools': _init_tools,
        'history': _init_history,
        'stats': {'total': _init_total, 'total_size': f'{_init_gb:.1f} GB', 'last_date': _init_last},
        'queue': api.queue_get(),
    })
    _html_url = _build_html(_init_data)
    window = webview.create_window(
        "Crna Berza Tools v2.0 by Vucko",
        url=_html_url,
        js_api=api,
        width=1100,
        height=800,
        min_size=(900, 650),
        hidden=True,
    )
    api.window = window

    # ─── Drag & Drop: minimal DOM handler just to enable native path capture ──
    # WebView2 only stores dropped paths if num_listeners > 0. We register a
    # tiny no-op drop handler on a hidden element. The actual paths are read
    # via api.get_dropped_path() from _dnd_state (much faster than DOM event).
    def _register_dom_drop():
        try:
            from webview.dom import DOMEventHandler, _dnd_state
            # Bump listener counter manually — no need for actual DOM event
            _dnd_state['num_listeners'] += 1
            api._log("[DND] Drop capture aktivan")
        except Exception as e:
            api._log(f"[DND ERR] {e}")

    window.events.loaded += _register_dom_drop

    def _on_started():
        def _show_after_splash():
            _splash_t.join(timeout=6)
            window.show()
        threading.Thread(target=_show_after_splash, daemon=True).start()
        threading.Thread(target=api._start_bg_tasks, daemon=True).start()
    webview.start(_on_started)
    os._exit(0)

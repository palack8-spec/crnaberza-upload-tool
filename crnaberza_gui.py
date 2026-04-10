#!/usr/bin/env python3
"""Crna Berza Upload Tool — pywebview + Bootstrap 5 GUI"""

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

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CrnaBerza")
TOOLS_DIR = os.path.join(DATA_DIR, "tools")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".m2ts", ".wmv", ".mov")
CONFIG_FILE = os.path.join(DATA_DIR, "crnaberza_config.json")
NO_WINDOW = subprocess.CREATE_NO_WINDOW

TOOL_INFO = {
    "ffmpeg": {"version": "7.1", "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"},
    "mediainfo": {"version": "24.12", "url": "https://mediaarea.net/download/binary/mediainfo/24.12/MediaInfo_CLI_24.12_Windows_x64.zip"},
    "torrenttools": {"version": "0.6.2", "url": "https://github.com/fbdtemme/torrenttools/releases/download/v0.6.2/torrenttools-0.6.2-windows-x86_64.msi"},
}
TOOLS_VERSION_FILE = os.path.join(TOOLS_DIR, "versions.json")

CATEGORIES = {
    "Film_HD_Domace": 73, "Film_HD_Strano": 48,
    "Film_SD_Domace": 29, "Film_SD_Strano": 54,
    "TV_HD_Domace": 75,   "TV_HD_Strano": 77,
    "TV_SD_Domace": 30,   "TV_SD_Strano": 34,
}

DEFAULT_CONFIG = {
    "tmdb_api_key": "", "cb_api_key": "",
    "output_dir": os.path.join(os.path.expanduser("~"), "Videos", "Crna Berza"),
    "download_path": os.path.join(os.path.expanduser("~"), "Downloads", "torrents"),
    "announce_url": "http://xbt.crnaberza.com/announce",
    "screenshot_count": 10, "skip_start_percent": 5, "skip_end_percent": 5,
    "cleanup_after_upload": False,
    "cleanup_delete_screenshots": True,
    "cleanup_delete_mediainfo": True,
    "cleanup_delete_torrent": False,
    "cleanup_delete_nfo": True,
    "cleanup_delete_imdb": True,
    "theme": "dark",
}

HISTORY_FILE = os.path.join(DATA_DIR, "upload_history.json")
APP_VERSION = "1.3.0"
GITHUB_REPO = "palack8-spec/crnaberza-upload-tool"


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(saved)
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


CONFIG = load_config()


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

def check_all_tools():
    return {"ffmpeg": get_ffmpeg_path(), "ffprobe": get_ffprobe_path(),
            "mediainfo": get_mediainfo_path(), "torrenttools": get_torrenttools_path()}

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def tmdb_request(endpoint):
    url = f"https://api.themoviedb.org/3/{endpoint}"
    sep = "&" if "?" in url else "?"
    url += f"{sep}api_key={CONFIG['tmdb_api_key']}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


_CYR_TO_LAT = {
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Ђ':'Đ','Е':'E','Ж':'Ž','З':'Z','И':'I',
    'Ј':'J','К':'K','Л':'L','Љ':'Lj','М':'M','Н':'N','Њ':'Nj','О':'O','П':'P','Р':'R',
    'С':'S','Т':'T','Ћ':'Ć','У':'U','Ф':'F','Х':'H','Ц':'C','Ч':'Č','Џ':'Dž','Ш':'Š',
    'а':'a','б':'b','в':'v','г':'g','д':'d','ђ':'đ','е':'e','ж':'ž','з':'z','и':'i',
    'ј':'j','к':'k','л':'l','љ':'lj','м':'m','н':'n','њ':'nj','о':'o','п':'p','р':'r',
    'с':'s','т':'t','ћ':'ć','у':'u','ф':'f','х':'h','ц':'c','ч':'č','џ':'dž','ш':'š',
}

def cyr_to_lat(text):
    return ''.join(_CYR_TO_LAT.get(c, c) for c in text)


def tmdb_get_local(search_type, tmdb_id, en_overview=""):
    """Try sr-RS, hr-HR, bs-BS for overview & genres. Fallback to English."""
    for lang in ("sr-RS", "hr-HR", "bs-BS"):
        try:
            details = tmdb_request(f"{search_type}/{tmdb_id}?language={lang}")
            ov = details.get("overview", "")
            genres = [cyr_to_lat(g.get("name", "")) for g in details.get("genres", []) if g.get("name")]
            if ov:
                return cyr_to_lat(ov), genres
        except Exception:
            pass
    return en_overview, []


def clean_folder_name(folder_name):
    clean = folder_name
    year = season = None
    ym = re.search(r'(19|20)\d{2}', clean)
    if ym: year = ym.group(0)
    sm = re.search(r'S(\d{1,2})', clean, re.IGNORECASE)
    if sm: season = int(sm.group(1))
    clean = clean.replace('.', ' ')
    clean = re.sub(r'\s*(19|20)\d{2}.*$', '', clean)
    clean = re.sub(r'\s+S\d{1,2}.*$', '', clean, flags=re.IGNORECASE)
    return clean.strip(), year, season


def find_video_file(path):
    p = Path(path)
    if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
        return str(p)
    videos = []
    for ext in VIDEO_EXTENSIONS:
        videos.extend(p.rglob(f"*{ext}"))
    return str(max(videos, key=lambda f: f.stat().st_size)) if videos else None


def format_duration(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def file_to_base64(filepath):
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def download_with_progress(url, dest_path, progress_callback=None):
    req = urllib.request.Request(url, headers={"User-Agent": "CrnaBerza/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        last_pct = -1
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total > 0:
                    pct = int(downloaded * 100 / total)
                    if pct != last_pct and pct % 10 == 0:
                        last_pct = pct
                        progress_callback(pct, downloaded, total)


# ═══════════════════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="sr" data-bs-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crna Berza Upload Tool</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<style>
:root{--bg:#020617;--bg2:#0F172A;--bg3:#1E293B;--accent:#22C55E;--accent2:#16A34A;--accent-glow:rgba(34,197,94,.2);--border:rgba(255,255,255,0.06);--border-solid:#334155;--text:#F8FAFC;--muted:#94A3B8}
*{scrollbar-width:thin;scrollbar-color:#334155 var(--bg)}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;overflow:hidden;height:100vh;margin:0}
.sidebar{width:200px;position:fixed;left:0;top:0;bottom:0;background:var(--bg2);border-right:1px solid var(--border-solid);z-index:100;display:flex;flex-direction:column}
.sidebar::after{content:'';position:absolute;top:0;right:0;bottom:0;width:1px;background:linear-gradient(180deg,transparent,rgba(34,197,94,0.15),transparent)}
.sidebar .logo{padding:18px 15px;text-align:center;border-bottom:1px solid var(--border-solid)}
.sidebar .logo h5{margin:0;font-weight:800;letter-spacing:.5px;background:linear-gradient(135deg,#22C55E 0%,#4ADE80 50%,#86EFAC 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sidebar .logo small{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:1px}
.sidebar .nav{flex:1;padding-top:8px}
.sidebar .nav-link{color:#64748B;padding:11px 20px;font-size:13px;transition:all .2s;border-left:3px solid transparent;display:flex;align-items:center;gap:10px}
.sidebar .nav-link:hover{color:#F1F5F9;background:rgba(34,197,94,.06)}
.sidebar .nav-link:hover i{color:var(--accent);filter:drop-shadow(0 0 4px rgba(34,197,94,.4))}
.sidebar .nav-link.active{color:var(--accent);background:rgba(34,197,94,.08);border-left-color:var(--accent)}
.sidebar .nav-link.active i{color:var(--accent);filter:drop-shadow(0 0 6px rgba(34,197,94,.5))}
.sidebar .nav-link i{font-size:16px;width:20px;text-align:center;transition:all .2s}
.main-content{margin-left:200px;padding:14px 20px;height:calc(100vh - 34px);overflow-y:auto}
.card{background:var(--bg2);border:1px solid var(--border-solid);border-radius:10px;transition:border-color .2s}
.card-header{background:transparent;border-bottom:1px solid var(--border-solid);font-size:13px;font-weight:600}
.btn-accent{background:linear-gradient(135deg,#16A34A,#22C55E);color:#fff;border:none;font-weight:600;transition:all .2s;box-shadow:0 2px 12px var(--accent-glow)}
.btn-accent:hover,.btn-accent:focus{background:linear-gradient(135deg,#22C55E,#4ADE80);color:#fff;box-shadow:0 4px 20px rgba(34,197,94,.35);transform:translateY(-1px)}
.btn-accent:active{background:#15803D;color:#fff;transform:translateY(0)}
.btn-outline-accent{background:transparent;color:var(--accent);border:1px solid var(--accent);font-weight:600;transition:all .2s}
.btn-outline-accent:hover,.btn-outline-accent:focus{background:rgba(34,197,94,0.1);color:#4ADE80;border-color:#4ADE80}
.btn-outline-accent:disabled{opacity:.5;cursor:not-allowed}
.form-control,.form-select{background:var(--bg3);border-color:var(--border-solid);color:var(--text);font-size:13px;transition:border-color .2s,box-shadow .2s}
.form-control:focus,.form-select:focus{background:var(--bg3);border-color:var(--accent);color:var(--text);box-shadow:0 0 0 2px rgba(34,197,94,.15)}
.form-control::placeholder{color:#64748B}
.log-box{background:#030712;color:#94A3B8;font-family:'Cascadia Code','Fira Code','Consolas',monospace;font-size:12px;border-radius:8px;padding:12px;overflow-y:auto;white-space:pre-wrap;word-wrap:break-word;border:1px solid var(--border-solid)}
.progress{height:5px;background:var(--border-solid);border-radius:3px}
.progress-bar{background:linear-gradient(90deg,#16A34A,#22C55E);transition:width .3s}
.status-bar{position:fixed;bottom:0;left:200px;right:0;background:var(--bg2);border-top:1px solid var(--border-solid);padding:5px 20px;font-size:11px;color:var(--muted);z-index:100;height:34px;display:flex;align-items:center;justify-content:space-between}
.status-bar::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(34,197,94,0.15),transparent)}
.imdb-card{background:var(--bg2);border:1px solid var(--border-solid);border-radius:10px;transition:all .2s;cursor:default}
.imdb-card:hover{border-color:var(--accent);box-shadow:0 4px 20px var(--accent-glow);transform:translateY(-1px)}
.poster-img{width:80px;min-height:120px;border-radius:8px;object-fit:cover;background:var(--bg3)}
.poster-ph{width:80px;min-height:120px;border-radius:8px;background:var(--bg3);display:flex;align-items:center;justify-content:center}
.upload-section{background:var(--bg2);border-radius:10px;padding:16px;margin-bottom:12px;border:1px solid var(--border-solid)}
.upload-section .lbl{color:var(--accent);font-weight:600;font-size:12px;min-width:100px}
.table-dark{--bs-table-bg:transparent}
.table-dark td,.table-dark th{border-color:var(--border-solid)}
.modal-content{background:var(--bg2);border:1px solid var(--border-solid)}
.modal-header,.modal-footer{border-color:var(--border-solid)}
.ss-thumb{width:160px;height:100px;object-fit:cover;border-radius:6px;border:1px solid var(--border-solid)}
.page{display:none}.page.active{display:block}
.page-title{font-size:16px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:10px}
.page-title i{color:var(--accent);font-size:22px}
.form-text{color:var(--muted) !important;font-size:11px}
.badge{font-weight:500}
.btn-outline-light{border-color:var(--border-solid);color:var(--text);transition:all .2s}
.btn-outline-light:hover{background:rgba(34,197,94,.06);border-color:var(--accent);color:#fff}
.preview-section{background:var(--bg3);border:1px solid var(--border-solid);border-radius:12px;overflow:hidden;margin-bottom:12px}
.preview-header{padding:10px 16px;border-bottom:1px solid var(--border-solid);display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em}
.preview-header i{color:var(--accent);font-size:14px}
.preview-body{padding:16px}
.info-tbl{width:100%;font-size:13px;border-collapse:separate;border-spacing:0}
.info-tbl td{padding:9px 14px;border-bottom:1px solid var(--border)}
.info-tbl .il{color:var(--muted);width:140px;white-space:nowrap;font-style:italic}
.info-tbl .iv{color:var(--text)}
.genre-badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:600;margin-right:4px;margin-bottom:2px}
.genre-badge:nth-child(3n+1){background:rgba(34,197,94,.12);color:#4ADE80}
.genre-badge:nth-child(3n+2){background:rgba(59,130,246,.12);color:#60A5FA}
.genre-badge:nth-child(3n){background:rgba(168,85,247,.12);color:#C084FC}
.sub-flag{display:inline-block;padding:2px 0;margin-right:6px}
.mi-grid{display:grid;grid-template-columns:1fr 1fr 1fr}
.mi-grid>div{padding:14px 16px}
.mi-grid>div:not(:last-child){border-right:1px solid var(--border-solid)}
.mi-title{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px}
.mi-tbl{width:100%;font-size:11px}
.mi-tbl td{padding:2px 0}
.mi-tbl .mk{color:var(--muted);padding-right:10px;white-space:nowrap}
.mi-tbl .mv{color:var(--text)}
.ss-row{display:flex;gap:10px;overflow-x:auto;padding:4px}
.ss-row::-webkit-scrollbar{height:6px}
.ss-row::-webkit-scrollbar-thumb{background:var(--border-solid);border-radius:3px}
.ss-row img{width:200px;height:125px;object-fit:cover;border-radius:8px;border:1px solid var(--border-solid);flex-shrink:0;transition:opacity .2s}
.ss-row img:hover{opacity:.85}
.cat-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.25);color:var(--accent)}
.imdb-link{color:#FACC15;text-decoration:none;font-size:13px;transition:color .2s}
.imdb-link:hover{color:#FDE68A}
.sub-tag{display:inline-flex;align-items:center;font-size:11px;background:var(--bg3);border:1px solid var(--border-solid);border-radius:4px;padding:2px 8px;color:var(--text)}
.pipeline{display:flex;align-items:flex-start;user-select:none}.pipe-step{display:flex;flex-direction:column;align-items:center;cursor:pointer;position:relative;z-index:1;flex:0 0 auto}
.pipe-circle{width:50px;height:50px;border-radius:50%;background:var(--bg3);border:2px solid var(--border-solid);display:flex;align-items:center;justify-content:center;font-size:18px;color:var(--muted);transition:all .3s}
.pipe-step:hover:not(.locked) .pipe-circle{border-color:rgba(34,197,94,.4);color:var(--accent);box-shadow:0 0 15px rgba(34,197,94,.1)}
.pipe-step.locked{cursor:not-allowed;opacity:.35}.pipe-step.locked .pipe-circle{pointer-events:none}
.pipe-step.done .pipe-circle{background:var(--accent2);border-color:var(--accent);color:#fff;box-shadow:0 0 15px var(--accent-glow)}.pipe-step.active .pipe-circle{background:linear-gradient(135deg,#16A34A,#22C55E);border-color:var(--accent);color:#fff;box-shadow:0 0 20px rgba(34,197,94,.3);animation:pulse-glow 2s infinite}
.pipe-undo{font-size:9px;margin-top:4px;color:var(--muted);cursor:pointer;opacity:0;transition:opacity .2s;text-transform:uppercase;letter-spacing:.5px}.pipe-step.done .pipe-undo{opacity:1}.pipe-undo:hover{color:#EF4444}
@keyframes pulse-glow{0%,100%{box-shadow:0 0 15px rgba(34,197,94,.2)}50%{box-shadow:0 0 25px rgba(34,197,94,.35)}}
.pipe-label{font-size:10px;margin-top:8px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px;transition:color .2s}
.pipe-step.done .pipe-label,.pipe-step.active .pipe-label{color:var(--accent)}
.pipe-line{flex:1;height:2px;background:var(--border-solid);margin:25px 4px 0;position:relative;overflow:hidden}.pipe-line::after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,var(--accent2),var(--accent));transform:scaleX(0);transform-origin:left;transition:transform .5s ease}
.pipe-line.filled::after{transform:scaleX(1)}
.toast-wrap{position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px}.app-toast{background:rgba(15,23,42,.95);backdrop-filter:blur(12px);border:1px solid var(--border-solid);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:10px;font-size:12px;color:var(--text);box-shadow:0 8px 30px rgba(0,0,0,.5);animation:toastIn .3s ease;min-width:260px}
.app-toast.out{animation:toastOut .3s ease forwards}
.app-toast.success{border-left:3px solid var(--accent)}.app-toast.error{border-left:3px solid #EF4444}
.app-toast.info{border-left:3px solid #3B82F6}
.app-toast i{font-size:16px;flex-shrink:0}
.app-toast.success i{color:var(--accent)}
.app-toast.error i{color:#EF4444}
.app-toast.info i{color:#3B82F6}
@keyframes toastIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes toastOut{from{opacity:1}to{transform:translateX(100%);opacity:0}}

/* ─── Light Theme ─── */
body.light{--bg:#F1F5F9;--bg2:#FFFFFF;--bg3:#F8FAFC;--accent:#16A34A;--accent2:#15803D;--accent-glow:rgba(22,163,74,.1);--border:rgba(0,0,0,0.06);--border-solid:#E2E8F0;--text:#0F172A;--muted:#64748B}
body.light{color-scheme:light}
body.light *{scrollbar-color:#CBD5E1 #F1F5F9}
body.light .sidebar{background:#FFFFFF;border-right-color:#E2E8F0}
body.light .sidebar::after{background:none}
body.light .sidebar .logo{border-bottom-color:#E2E8F0}
body.light .sidebar .logo h5{background:linear-gradient(135deg,#16A34A 0%,#22C55E 50%,#4ADE80 100%);-webkit-background-clip:text;background-clip:text}
body.light .sidebar .nav-link{color:#475569}
body.light .sidebar .nav-link:hover{color:#16A34A;background:rgba(22,163,74,.05)}
body.light .sidebar .nav-link:hover i{color:#16A34A;filter:none}
body.light .sidebar .nav-link.active{color:#16A34A;background:rgba(22,163,74,.08);border-left-color:#16A34A}
body.light .sidebar .nav-link.active i{color:#16A34A;filter:none}
body.light .card{background:#FFFFFF;border-color:#E2E8F0;box-shadow:0 1px 3px rgba(0,0,0,.04)}
body.light .card-header{border-bottom-color:#E2E8F0;color:#1E293B}
body.light .form-control,body.light .form-select{background:#FFFFFF;border-color:#CBD5E1;color:#0F172A}
body.light .form-control:focus,body.light .form-select:focus{background:#FFFFFF;border-color:#16A34A;color:#0F172A;box-shadow:0 0 0 2px rgba(22,163,74,.12)}
body.light .form-control::placeholder{color:#94A3B8}
body.light .log-box{background:#F8FAFC;color:#334155;border-color:#E2E8F0}
body.light .modal-content{background:#FFFFFF;border-color:#E2E8F0;box-shadow:0 20px 60px rgba(0,0,0,.12)}
body.light .modal-header,.body.light .modal-footer{border-color:#E2E8F0}
body.light .modal-footer{border-color:#E2E8F0}
body.light .table-dark{--bs-table-bg:#fff;--bs-table-color:#0F172A;--bs-table-border-color:#E2E8F0}
body.light .btn-close-white{filter:none}
body.light .status-bar{background:#FFFFFF;border-top-color:#E2E8F0;color:#64748B}
body.light .status-bar::before{background:none}
body.light .btn-outline-light{border-color:#CBD5E1;color:#334155}
body.light .btn-outline-light:hover{background:rgba(22,163,74,.05);border-color:#16A34A;color:#16A34A}
body.light .pipe-circle{background:#FFFFFF;border-color:#CBD5E1;color:#94A3B8}
body.light .pipe-step:hover:not(.locked) .pipe-circle{border-color:rgba(22,163,74,.4);color:#16A34A;box-shadow:0 0 12px rgba(22,163,74,.08)}
body.light .pipe-line{background:#CBD5E1}
body.light .pipe-label{color:#64748B}
body.light .pipe-undo{color:#64748B}
body.light .stat-card{background:#FFFFFF;border-color:#E2E8F0;box-shadow:0 1px 3px rgba(0,0,0,.04)}
body.light .progress{background:#E2E8F0}
body.light .app-toast{background:rgba(255,255,255,.97);border-color:#E2E8F0;color:#0F172A;box-shadow:0 8px 30px rgba(0,0,0,.08)}
body.light .desc-preview{background:#FFFFFF;border-color:#E2E8F0;color:#334155}
body.light .badge.bg-success{background:#16A34A !important}
body.light .imdb-link{color:#CA8A04}
body.light .imdb-link:hover{color:#A16207}
body.light .preview-section{background:#F8FAFC;border-color:#E2E8F0}
body.light .preview-header{border-bottom-color:#E2E8F0;color:#64748B}
body.light .preview-header i{color:#16A34A}
body.light .info-tbl td{border-bottom-color:#F1F5F9}
body.light .info-tbl .il{color:#64748B}
body.light .info-tbl .iv{color:#0F172A}
body.light .genre-badge:nth-child(3n+1){background:rgba(22,163,74,.08);color:#16A34A}
body.light .genre-badge:nth-child(3n+2){background:rgba(37,99,235,.08);color:#2563EB}
body.light .genre-badge:nth-child(3n){background:rgba(147,51,234,.08);color:#9333EA}
body.light .cat-badge{background:rgba(22,163,74,.08);border-color:rgba(22,163,74,.2);color:#16A34A}
body.light .sub-tag{background:#F8FAFC;border-color:#E2E8F0;color:#334155}
body.light .mi-grid>div:not(:last-child){border-right-color:#E2E8F0}
body.light .mi-title{color:#64748B}
body.light .mi-tbl .mk{color:#64748B}
body.light .mi-tbl .mv{color:#0F172A}
body.light .ss-row::-webkit-scrollbar-thumb{background:#CBD5E1}
body.light .ss-row img{border-color:#E2E8F0}
body.light .imdb-card{background:#FFFFFF;border-color:#E2E8F0}
body.light .imdb-card:hover{border-color:#16A34A;box-shadow:0 4px 20px rgba(22,163,74,.08)}
body.light .poster-img{background:#F1F5F9}
body.light .poster-ph{background:#F1F5F9}
body.light .upload-section{background:#FFFFFF;border-color:#E2E8F0}
body.light .pipe-step.done .pipe-circle{box-shadow:0 0 12px rgba(22,163,74,.15)}
body.light .pipe-step.active .pipe-circle{box-shadow:0 0 16px rgba(22,163,74,.2)}
body.light .log-filters .btn.active-filter{background:#16A34A;border-color:#16A34A}

/* Stats Card */
#statsRow{display:flex;gap:8px}
#statsRow>.col{flex:1 1 0;min-width:0;max-width:none}
.stat-card{text-align:center;padding:14px 8px;border-radius:10px;background:var(--bg3);border:1px solid var(--border-solid);height:100%}
.stat-val{font-size:20px;font-weight:700;color:var(--accent);line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}

/* Log Filters */
.log-filters{display:flex;gap:4px;align-items:center}
.log-filters .btn{font-size:10px;padding:1px 8px;border-radius:10px}
.log-filters .btn.active-filter{background:var(--accent);color:#fff;border-color:var(--accent)}

/* Queue Badge */
.queue-badge{position:absolute;top:-4px;right:-4px;background:#ef4444;color:#fff;font-size:9px;width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700}

/* Desc Preview */
.desc-preview{background:var(--bg3);border:1px solid var(--border-solid);border-radius:8px;padding:12px;font-size:12px;color:var(--text);overflow-y:auto;max-height:350px;line-height:1.6}
.desc-preview .bb-center{text-align:center}
.desc-preview .bb-bold{font-weight:700}
.desc-preview .bb-size24{font-size:20px}
.desc-preview .bb-url{color:var(--accent);text-decoration:underline}
</style>
</head>
<body>

<div class="toast-wrap" id="toastWrap"></div>

<!-- Sidebar -->
<div class="sidebar">
    <div class="logo">
        <h5><i class="bi bi-film"></i> Crna Berza</h5>
        <small>Upload Tool V1 by Vucko</small>
    </div>
    <nav class="nav flex-column">
        <a class="nav-link active" href="#" data-page="main"><i class="bi bi-house-fill"></i>Glavni</a>
        <a class="nav-link" href="#" data-page="queue" style="position:relative"><i class="bi bi-list-check"></i>Red cekanja<span class="queue-badge" id="queueBadge" style="display:none">0</span></a>
        <a class="nav-link" href="#" data-page="history"><i class="bi bi-clock-history"></i>Istorija</a>
        <a class="nav-link" href="#" data-page="tools"><i class="bi bi-wrench-adjustable"></i>Alati</a>
        <a class="nav-link" href="#" data-page="settings"><i class="bi bi-gear-fill"></i>Podesavanja</a>
    </nav>
</div>

<!-- Main Content -->
<div class="main-content">

<!-- PAGE: Main -->
<div id="page-main" class="page active">
    <div class="page-title"><i class="bi bi-play-circle-fill"></i> Glavni</div>

    <div class="card p-3 mb-2" id="dropZone">
        <label class="form-label fw-semibold mb-2" style="font-size:13px">Putanja do foldera / video fajla</label>
        <div id="dropHint" style="display:none;text-align:center;padding:30px;border:2px dashed var(--accent);border-radius:10px;color:var(--accent);font-size:14px;margin-bottom:10px"><i class="bi bi-folder-plus" style="font-size:24px"></i><br>Prevucite folder ovde</div>
        <div class="d-flex gap-2">
            <div class="input-group flex-grow-1">
                <input type="text" class="form-control" id="pathInput" placeholder="C:\\Movies\\...">
                <button class="btn btn-outline-light" onclick="browsePath()" style="white-space:nowrap"><i class="bi bi-folder2-open me-1"></i>Izaberi</button>
            </div>
            <button class="btn btn-accent px-3" onclick="quickUpload()" id="btnQuick" title="Pokreni sve korake odjednom" style="white-space:nowrap"><i class="bi bi-lightning-fill me-1"></i>Brzi Upload</button>
            <button class="btn btn-outline-accent px-3" onclick="batchUpload()" id="btnBatch" title="Upload vise foldera odjednom" style="white-space:nowrap"><i class="bi bi-collection-fill me-1"></i>Batch</button>
        </div>
    </div>

    <!-- Stats -->
    <div class="row g-2 mb-2" id="statsRow">
        <div class="col"><div class="stat-card"><div class="stat-val" id="statTotal">0</div><div class="stat-lbl">Uploada</div></div></div>
        <div class="col"><div class="stat-card"><div class="stat-val" id="statSize">0 GB</div><div class="stat-lbl">Ukupno</div></div></div>
        <div class="col"><div class="stat-card"><div class="stat-val" id="statLast">-</div><div class="stat-lbl">Poslednji</div></div></div>
        <div class="col"><div class="stat-card"><div class="stat-val" id="statQueue">0</div><div class="stat-lbl">U redu</div></div></div>
    </div>

    <div class="card p-3 mb-2">
        <div class="pipeline" id="pipeline">
            <div class="pipe-step" id="pipeImdb" onclick="pipeClick(0)">
                <div class="pipe-circle"><i class="bi bi-film"></i></div>
                <div class="pipe-label">IMDB</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(0)">ponisti</div>
            </div>
            <div class="pipe-line" id="pipeLine1"></div>
            <div class="pipe-step locked" id="pipeSs" onclick="pipeClick(1)">
                <div class="pipe-circle"><i class="bi bi-camera"></i></div>
                <div class="pipe-label">Screenshots</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(1)">ponisti</div>
            </div>
            <div class="pipe-line" id="pipeLine2"></div>
            <div class="pipe-step locked" id="pipeTorrent" onclick="pipeClick(2)">
                <div class="pipe-circle"><i class="bi bi-magnet-fill"></i></div>
                <div class="pipe-label">Torrent</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(2)">ponisti</div>
            </div>
            <div class="pipe-line" id="pipeLine3"></div>
            <div class="pipe-step locked" id="pipeUpload" onclick="pipeClick(3)">
                <div class="pipe-circle"><i class="bi bi-cloud-upload"></i></div>
                <div class="pipe-label">Upload</div>
                <div class="pipe-undo" onclick="event.stopPropagation();undoStep(3)">ponisti</div>
            </div>
        </div>
    </div>

    <div class="progress mb-2"><div class="progress-bar" id="progressBar" style="width:0%"></div></div>

    <div class="card mb-2">
        <div class="card-header d-flex justify-content-between align-items-center px-3 py-2">
            <span><i class="bi bi-terminal me-1"></i>Log</span>
            <div class="d-flex gap-1 align-items-center">
                <div class="log-filters">
                    <button class="btn btn-outline-light btn-sm active-filter" onclick="filterLog('all')" data-filter="all">Sve</button>
                    <button class="btn btn-outline-light btn-sm" onclick="filterLog('info')" data-filter="info">Info</button>
                    <button class="btn btn-outline-light btn-sm" onclick="filterLog('err')" data-filter="err">Greske</button>
                </div>
                <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:11px" onclick="clearLog()">Obrisi</button>
            </div>
        </div>
        <div class="card-body p-0">
            <div class="log-box" id="logOutput" style="height:180px;border:none;border-radius:0 0 10px 10px"></div>
        </div>
    </div>
</div>

<!-- PAGE: Tools -->
<div id="page-tools" class="page">
    <div class="page-title"><i class="bi bi-wrench-adjustable-circle"></i> Alati</div>
    <p class="text-muted small mb-3">Program koristi spoljne alate. Klikni 'Preuzmi' za automatsku instalaciju.</p>

    <div class="card mb-3">
        <div class="card-body p-0">
            <table class="table table-dark table-borderless mb-0 align-middle" style="font-size:13px">
                <thead><tr class="text-muted small"><th class="ps-3">Alat</th><th>Status</th><th>Putanja</th><th></th></tr></thead>
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
        <div class="card-header px-3 py-2"><i class="bi bi-terminal me-1"></i>Log preuzimanja</div>
        <div class="card-body p-0">
            <div class="log-box" id="toolsLog" style="height:180px;border:none;border-radius:0 0 10px 10px"></div>
        </div>
    </div>
</div>

<!-- PAGE: History -->
<div id="page-history" class="page">
    <div class="page-title"><i class="bi bi-clock-history"></i> Istorija uploada</div>
    <div class="card mb-3">
        <div class="card-body p-0">
            <table class="table table-dark table-borderless mb-0 align-middle" style="font-size:12px">
                <thead><tr class="text-muted small"><th class="ps-3">#</th><th>Naziv</th><th>Kategorija</th><th>Velicina</th><th>Datum</th><th>Link</th><th>Opis</th></tr></thead>
                <tbody id="historyBody"><tr><td colspan="7" class="text-center text-muted py-3">Nema uploada</td></tr></tbody>
            </table>
        </div>
    </div>
    <div class="d-flex gap-2">
        <button class="btn btn-outline-light btn-sm" onclick="loadHistory()"><i class="bi bi-arrow-clockwise me-1"></i>Osvezi</button>
        <button class="btn btn-outline-light btn-sm" onclick="exportHistory('json')"><i class="bi bi-filetype-json me-1"></i>Export JSON</button>
        <button class="btn btn-outline-light btn-sm" onclick="exportHistory('csv')"><i class="bi bi-filetype-csv me-1"></i>Export CSV</button>
    </div>
</div>

<!-- PAGE: Queue -->
<div id="page-queue" class="page">
    <div class="page-title"><i class="bi bi-list-check"></i> Red cekanja</div>
    <div class="d-flex gap-2 mb-3">
        <button class="btn btn-outline-light btn-sm" onclick="queueAddFolder()"><i class="bi bi-folder-plus me-1"></i>Dodaj folder</button>
        <button class="btn btn-accent btn-sm" onclick="queueStartAll()" id="queueStartBtn"><i class="bi bi-play-fill me-1"></i>Pokreni sve</button>
        <button class="btn btn-outline-danger btn-sm" onclick="queueClear()"><i class="bi bi-trash me-1"></i>Obrisi red</button>
    </div>
    <div id="queueList" class="mb-3">
        <p class="text-muted text-center" style="font-size:12px">Red cekanja je prazan. Dodajte foldere za upload.</p>
    </div>
    <div id="queueProgress" style="display:none">
        <div style="font-size:12px;color:var(--muted);margin-bottom:4px"><span id="qCurrent">0</span> / <span id="qTotal">0</span> — <span id="qStatus">Cekanje...</span></div>
        <div class="progress" style="height:6px;border-radius:3px"><div id="qBar" class="progress-bar" style="width:0%;transition:width 0.3s"></div></div>
    </div>
</div>

<!-- PAGE: Settings -->
<div id="page-settings" class="page">
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
    <span id="statusText">Spreman</span>
    <span class="text-muted" id="statusRight"></span>
</div>

<!-- IMDB Modal -->
<div class="modal fade" id="imdbModal" tabindex="-1" data-bs-backdrop="static">
<div class="modal-dialog modal-lg modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-film me-2" style="color:var(--accent)"></i>Izaberite film / seriju</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body" id="imdbBody"></div>
</div></div></div>

<!-- Upload Modal -->
<div class="modal fade" id="uploadModal" tabindex="-1" data-bs-backdrop="static">
<div class="modal-dialog modal-xl modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-cloud-upload me-2" style="color:var(--accent)"></i>Upload Pregled</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body" id="uploadBody"></div>
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

<!-- Batch Upload Modal -->
<div class="modal fade" id="batchModal" tabindex="-1">
<div class="modal-dialog modal-lg">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-collection-fill me-2" style="color:var(--accent)"></i>Batch Upload</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
        <p style="font-size:12px;color:var(--muted);margin-bottom:8px">Izaberite foldere za upload. Svaki folder ce proci kroz kompletnu proceduru (IMDB, Screenshots, Torrent, Upload).</p>
        <div class="d-flex gap-2 mb-3">
            <button class="btn btn-outline-light btn-sm" onclick="batchAddFolder()"><i class="bi bi-folder-plus me-1"></i>Dodaj folder</button>
            <button class="btn btn-outline-danger btn-sm" onclick="batchClearAll()"><i class="bi bi-trash me-1"></i>Obrisi sve</button>
        </div>
        <div id="batchList" style="max-height:300px;overflow-y:auto"></div>
        <div id="batchProgress" style="display:none;margin-top:12px">
            <div style="font-size:12px;color:var(--muted);margin-bottom:4px"><span id="batchCurrent">0</span> / <span id="batchTotal">0</span> — <span id="batchStatus">Cekanje...</span></div>
            <div class="progress" style="height:6px;border-radius:3px"><div id="batchBar" class="progress-bar" style="width:0%;transition:width 0.3s"></div></div>
        </div>
    </div>
    <div class="modal-footer">
        <button class="btn btn-outline-light btn-sm" data-bs-dismiss="modal" id="batchCloseBtn">Zatvori</button>
        <button class="btn btn-accent btn-sm px-3" id="batchStartBtn" onclick="batchStart()"><i class="bi bi-play-fill me-1"></i>Pokreni Batch</button>
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

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
// ─── State ───
let running = false, pollTimer = null, uploadResolve = null;

// ─── Navigation ───
document.querySelectorAll('[data-page]').forEach(el => {
    el.addEventListener('click', e => {
        e.preventDefault();
        document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
        el.classList.add('active');
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('page-' + el.dataset.page).classList.add('active');
    });
});

// ─── Drag & Drop ───
(function(){
    const dz=document.getElementById('dropZone');
    const hint=document.getElementById('dropHint');
    if(!dz)return;
    let dragCounter=0;
    window.addEventListener('dragenter',function(e){e.preventDefault();dragCounter++;hint.style.display='block'});
    window.addEventListener('dragleave',function(e){e.preventDefault();dragCounter--;if(dragCounter<=0){dragCounter=0;hint.style.display='none'}});
    window.addEventListener('dragover',function(e){e.preventDefault()});
    window.addEventListener('drop',async function(e){
        e.preventDefault();dragCounter=0;hint.style.display='none';
        if(e.dataTransfer.files&&e.dataTransfer.files.length>0){
            const path=e.dataTransfer.files[0].path||e.dataTransfer.files[0].name;
            if(path){
                document.getElementById('pathInput').value=path;
                startPolling();
                const check=await pywebview.api.check_existing_data(path);
                if(check&&check.loaded_steps&&check.loaded_steps.length>0){
                    check.loaded_steps.forEach(s=>{pipeState[s]=2});
                    updatePipe();
                    toast('Ucitano '+check.loaded_steps.length+' korak(a)','success');
                }
            }
        }
    });
})();

// ─── Helpers ───
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}
function clearLog(){document.getElementById('logOutput').innerHTML='';logAllLines=[]}
var logAllLines=[];
var logFilter='all';
function filterLog(f){
    logFilter=f;
    document.querySelectorAll('.log-filters .btn').forEach(b=>b.classList.toggle('active-filter',b.dataset.filter===f));
    const el=document.getElementById('logOutput');
    if(f==='all'){el.innerHTML=logAllLines.map(l=>esc(l)).join('\\n');}
    else if(f==='err'){el.innerHTML=logAllLines.filter(l=>l.indexOf('[ERR]')>=0).map(l=>esc(l)).join('\\n');}
    else{el.innerHTML=logAllLines.filter(l=>l.indexOf('[ERR]')<0).map(l=>esc(l)).join('\\n');}
    el.scrollTop=el.scrollHeight;
}
function setBtns(dis){running=dis}
function toast(msg,type,dur){type=type||'info';dur=dur||4000;var w=document.getElementById('toastWrap');var icons={success:'bi-check-circle-fill',error:'bi-exclamation-circle-fill',info:'bi-info-circle-fill'};var el=document.createElement('div');el.className='app-toast '+type;el.innerHTML='<i class="bi '+icons[type]+'"></i><span>'+esc(msg)+'</span>';w.appendChild(el);setTimeout(function(){el.classList.add('out');setTimeout(function(){el.remove()},300)},dur)}
var STEPS=['imdb','screenshots','torrent','upload'];
var STEP_IDS=['pipeImdb','pipeSs','pipeTorrent','pipeUpload'];
var LINE_IDS=['pipeLine1','pipeLine2','pipeLine3'];
var pipeState=[0,0,0,0];
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
            if(u.logs&&u.logs.length){const el=document.getElementById('logOutput');u.logs.forEach(m=>{logAllLines.push(m);if(logFilter==='all'||(logFilter==='err'&&m.indexOf('[ERR]')>=0)||(logFilter==='info'&&m.indexOf('[ERR]')<0)){el.innerHTML+=esc(m)+'\\n'}});el.scrollTop=el.scrollHeight}
            if(u.tool_logs&&u.tool_logs.length){const el=document.getElementById('toolsLog');u.tool_logs.forEach(m=>{el.innerHTML+=esc(m)+'\\n'});el.scrollTop=el.scrollHeight}
            const pb=document.getElementById('progressBar');
            if(u.progress<0){pb.style.width='100%';pb.className='progress-bar progress-bar-striped progress-bar-animated'}
            else{pb.style.width=u.progress+'%';pb.className='progress-bar'}
            document.getElementById('statusText').textContent=u.status;
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

// ─── Actions ───
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
        if(step==='imdb'){const r=await pywebview.api.search_imdb(path);if(r&&r.results){const i=await showImdbModal(r.results);if(i!==null)await pywebview.api.confirm_imdb(i)}else{throw 'Nema rezultata'}}
        else if(step==='screenshots'){const r=await pywebview.api.run_screenshots(path);if(!r||!r.ok)throw 'Screenshots neuspesno'}
        else if(step==='torrent'){const r=await pywebview.api.run_torrent(path);if(!r||!r.ok)throw 'Torrent neuspesno'}
        else if(step==='upload'){const ud=await pywebview.api.get_upload_data();if(ud)await showUploadModal(ud)}
        pipeState[idx]=2;
        toast(step.charAt(0).toUpperCase()+step.slice(1)+' zavrseno!','success');
    }catch(e){console.error(e);pipeState[idx]=0;toast('Greska: '+step,'error')}
    updatePipe();setBtns(false);
}

// ─── IMDB Modal ───
function showImdbModal(results){
    return new Promise(resolve=>{
        const body=document.getElementById('imdbBody');
        body.innerHTML='';
        results.forEach((item,i)=>{
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
            card.querySelector('button').addEventListener('click',()=>{modal.hide();resolve(i)});
            body.appendChild(card);
        });
        const modalEl=document.getElementById('imdbModal');
        const modal=new bootstrap.Modal(modalEl);
        modalEl.addEventListener('hidden.bs.modal',()=>resolve(null),{once:true});
        modal.show();
    });
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
                miHtml+='<div style="padding:12px 16px;border-top:1px solid var(--border-solid)"><div class="mi-title">SUBTITLES</div><div class="d-flex flex-wrap gap-1">';
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

        const flagImg={'sr':'<img src="https://flagcdn.com/20x15/rs.png" style="vertical-align:middle;margin-right:3px">','hr':'<img src="https://flagcdn.com/20x15/hr.png" style="vertical-align:middle;margin-right:3px">','ba':'<img src="https://flagcdn.com/20x15/ba.png" style="vertical-align:middle;margin-right:3px">'};
        const subsHtml=(data.subtitles&&data.subtitles.length)
            ?data.subtitles.map(s=>`<span class="sub-flag">${flagImg[s]||''}</span>`).join('')
            :'<span style="color:var(--muted)">\u2014</span>';

        const genresHtml=(data.tmdb_genres&&data.tmdb_genres.length)
            ?data.tmdb_genres.map(g=>`<span class="genre-badge">${esc(g)}</span>`).join('')
            :'<span style="color:var(--muted)">\u2014</span>';

        const now=new Date();
        const months=['January','February','March','April','May','June','July','August','September','October','November','December'];
        const h=now.getHours()%12||12,m=String(now.getMinutes()).padStart(2,'0'),ap=now.getHours()>=12?'pm':'am';
        const dateStr=`${months[now.getMonth()]} ${now.getDate()}, ${now.getFullYear()} at ${h}:${m} ${ap}`;

        body.innerHTML=`
        <div class="preview-section"><div class="preview-body"><div class="d-flex gap-4">
            <div style="width:220px;flex-shrink:0">${posterHtml}</div>
            <div class="flex-grow-1">
                <table class="info-tbl">
                <tr><td class="il">Kategorija:</td><td class="iv"><span class="cat-badge">${esc(data.category_name)}</span>
                    <input type="text" class="form-control form-control-sm d-inline-block ms-2" id="upCatId" value="${data.category_id}" style="width:60px;font-size:11px;padding:2px 6px;vertical-align:middle">
                    <button class="btn btn-outline-light btn-sm ms-1 py-0 px-2" style="font-size:10px" onclick="fetchCats()">&#9776;</button>
                    <div id="catInfo" style="font-size:10px;color:var(--muted);margin-top:4px"></div></td></tr>
                <tr><td class="il">Dodato:</td><td class="iv" style="color:var(--accent)">${dateStr}</td></tr>
                <tr><td class="il">Fajlovi:</td><td class="iv"><a href="#" onclick="return false" style="color:var(--accent);text-decoration:none">1 fajl</a></td></tr>
                <tr><td class="il">Titlovi:</td><td class="iv">${subsHtml}</td></tr>
                <tr><td class="il">Zanrovi:</td><td class="iv">${genresHtml}</td></tr>
                <tr><td class="il">IMDB / Eksterni:</td><td class="iv">${imdbHtml}</td></tr>
                <tr><td class="il">NFO:</td><td class="iv"><span style="color:var(--muted)">\u2014</span></td></tr>
                </table>
                <div class="mt-2"><div class="form-check"><input class="form-check-input" type="checkbox" id="upAnon"><label class="form-check-label" for="upAnon" style="font-size:12px;color:var(--muted)">Anonimni upload</label></div></div>
            </div>
        </div></div></div>
        <div class="preview-section"><div class="preview-header"><i class="bi bi-text-left"></i> OPIS</div><div class="preview-body">
            ${titleText?`<h5 style="text-align:center;font-weight:700;margin-bottom:12px">${titleText}</h5>`:''}
            ${data.tmdb_overview?`<p style="color:var(--muted);font-size:13px;margin-bottom:12px">${esc(data.tmdb_overview)}</p>`:''}
            <div class="mb-2"><label class="d-block mb-1" style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em;font-weight:600">Naziv torrenta</label>
            <input type="text" class="form-control" id="upName" value="${esc(data.auto_name)}"></div>
            <div style="text-align:center;margin-top:16px"><label class="d-block mb-1" style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em;font-weight:600"><i class="bi bi-youtube" style="color:#ff0000;margin-right:4px"></i>YouTube Trailer</label>
            <input type="text" class="form-control" id="upTrailer" placeholder="https://www.youtube.com/watch?v=..." style="text-align:center"></div>
        </div></div>
        ${miHtml}
        ${ssHtml}`;

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
    const trailer=document.getElementById('upTrailer').value.trim();
    const anon=document.getElementById('upAnon').checked;
    if(!cat||!name){toast('Unesite kategoriju i naziv!','error');return}
    const modal=bootstrap.Modal.getInstance(document.getElementById('uploadModal'));
    if(modal)modal.hide();
    let uploadOk=false;
    try{
        await pywebview.api.do_upload(parseInt(cat),name,trailer,anon);
        uploadOk=true;
    }catch(e){
        console.error(e);
        const retry=confirm('Upload nije uspeo! Pokusati ponovo?');
        if(retry){
            try{await pywebview.api.do_upload(parseInt(cat),name,trailer,anon);uploadOk=true}catch(e2){toast('Upload neuspesan nakon ponovnog pokusaja','error')}
        }else{toast('Upload otkazan','error')}
    }
    if(uploadResolve){uploadResolve();uploadResolve=null}
    if(uploadOk){
        await showDescModal(trailer);
        await showCleanupModal();
        await loadHistory();
        await loadStats();
    }
}

// ─── Quick Upload ───
async function quickUpload(){
    const path=document.getElementById('pathInput').value.trim();
    if(!path){
        const r=await pywebview.api.browse_folder();
        if(!r)return;
        document.getElementById('pathInput').value=r;
        const check=await pywebview.api.check_existing_data(r);
        if(check&&check.loaded_steps&&check.loaded_steps.length>0){
            check.loaded_steps.forEach(s=>{pipeState[s]=2});
            updatePipe();
        }
    }
    const p=document.getElementById('pathInput').value.trim();
    if(!p){toast('Unesite putanju!','error');return}
    setBtns(true);startPolling();
    let ok=true;
    try{
        // Step 1: IMDB (if not done)
        if(ok&&pipeState[0]!==2){
            pipeState[0]=1;updatePipe();
            const r=await pywebview.api.search_imdb(p);
            if(r&&r.results){const i=await showImdbModal(r.results);if(i!==null)await pywebview.api.confirm_imdb(i);pipeState[0]=2;updatePipe()}
            else{pipeState[0]=0;updatePipe();ok=false;toast('IMDB pretraga neuspesna','error')}
        }
        // Step 2: Screenshots (if not done)
        if(ok&&pipeState[1]!==2){
            pipeState[1]=1;updatePipe();
            const r2=await pywebview.api.run_screenshots(p);
            if(r2&&r2.ok){pipeState[1]=2;updatePipe()}
            else{pipeState[1]=0;updatePipe();ok=false;toast('Screenshots neuspesno','error')}
        }
        // Step 3: Torrent (if not done)
        if(ok&&pipeState[2]!==2){
            pipeState[2]=1;updatePipe();
            const r3=await pywebview.api.run_torrent(p);
            if(r3&&r3.ok){pipeState[2]=2;updatePipe()}
            else{pipeState[2]=0;updatePipe();ok=false;toast('Torrent kreiranje neuspesno','error')}
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

// ─── Batch Upload ───
let batchFolders=[];
function batchUpload(){
    batchFolders=[];
    renderBatchList();
    document.getElementById('batchProgress').style.display='none';
    document.getElementById('batchStartBtn').disabled=false;
    document.getElementById('batchCloseBtn').disabled=false;
    const m=new bootstrap.Modal(document.getElementById('batchModal'));
    m.show();
}
async function batchAddFolder(){
    const f=await pywebview.api.browse_folder();
    if(f&&!batchFolders.includes(f)){batchFolders.push(f);renderBatchList()}
}
function batchRemove(i){batchFolders.splice(i,1);renderBatchList()}
function batchClearAll(){batchFolders=[];renderBatchList()}
function renderBatchList(){
    const el=document.getElementById('batchList');
    if(!batchFolders.length){el.innerHTML='<p class="text-muted text-center" style="font-size:12px">Nema foldera. Kliknite "Dodaj folder".</p>';return}
    el.innerHTML=batchFolders.map((f,i)=>`<div class="d-flex align-items-center gap-2 mb-1" style="font-size:12px" id="batchItem${i}"><span class="badge bg-secondary" style="min-width:24px">${i+1}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)">${esc(f)}</span><span id="batchSt${i}" style="font-size:11px;color:var(--muted)"></span><button class="btn btn-outline-danger btn-sm py-0 px-1" style="font-size:10px" onclick="batchRemove(${i})"><i class="bi bi-x"></i></button></div>`).join('');
}
async function batchStart(){
    if(!batchFolders.length){toast('Dodajte foldere prvo!','error');return}
    document.getElementById('batchStartBtn').disabled=true;
    document.getElementById('batchCloseBtn').disabled=true;
    document.getElementById('batchProgress').style.display='block';
    const total=batchFolders.length;
    document.getElementById('batchTotal').textContent=total;
    let done=0;
    for(let i=0;i<total;i++){
        document.getElementById('batchCurrent').textContent=i+1;
        document.getElementById('batchStatus').textContent=batchFolders[i].split('\\\\').pop()||batchFolders[i];
        const stEl=document.getElementById('batchSt'+i);
        if(stEl)stEl.innerHTML='<span style="color:#F59E0B">⏳ U toku...</span>';
        try{
            // Reset state for this item
            await pywebview.api.reset_for_batch(batchFolders[i]);
            // Step 1: IMDB
            const r1=await pywebview.api.search_imdb(batchFolders[i]);
            if(r1&&r1.results){const pick=await showImdbModal(r1.results);if(pick!==null)await pywebview.api.confirm_imdb(pick)}
            // Step 2: Screenshots
            await pywebview.api.run_screenshots(batchFolders[i]);
            // Step 3: Torrent
            await pywebview.api.run_torrent(batchFolders[i]);
            // Step 4: Upload
            const ud=await pywebview.api.get_upload_data();
            if(ud)await showUploadModal(ud);
            if(stEl)stEl.innerHTML='<span style="color:var(--accent)">✔ Zavrsen</span>';
            done++;
        }catch(e){
            console.error('Batch error:',e);
            if(stEl)stEl.innerHTML='<span style="color:#ef4444">✘ Greska</span>';
        }
        document.getElementById('batchBar').style.width=((i+1)/total*100)+'%';
    }
    document.getElementById('batchStatus').textContent=`Gotovo! ${done}/${total} uspesno.`;
    document.getElementById('batchCloseBtn').disabled=false;
    toast(`Batch zavrsen: ${done}/${total} uspesno.`,done===total?'success':'warning');
    await loadHistory();
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
    if(!hist||hist.length===0){tb.innerHTML='<tr><td colspan="7" class="text-center text-muted py-3">Nema uploada</td></tr>';return}
    tb.innerHTML='';
    hist.slice().reverse().forEach((h,i)=>{
        const size=h.size?(h.size/1073741824).toFixed(2)+' GB':'?';
        const link=h.url?`<a href="${esc(h.url)}" target="_blank" class="imdb-link" style="font-size:11px">Otvori</a>`:'';
        const descBtn=h.description?`<button class="btn btn-outline-light btn-sm py-0 px-1" style="font-size:10px" onclick="showHistDesc(${hist.length-1-i})"><i class="bi bi-clipboard"></i></button>`:'';
        tb.innerHTML+=`<tr><td class="ps-3 text-muted">${h.torrent_id||'?'}</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(h.name||'')}</td><td>${esc(h.category||'')}</td><td>${size}</td><td style="font-size:11px">${esc(h.date||'')}</td><td>${link}</td><td>${descBtn}</td></tr>`;
    });
}
async function loadHistory(){
    const hist=await pywebview.api.get_upload_history();
    renderHistory(hist);
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
    const el=document.getElementById('catInfo');
    el.textContent='Ucitavanje...';
    const r=await pywebview.api.fetch_categories();
    if(r.error){el.textContent=r.error;return}
    let parts=[];
    if(Array.isArray(r.categories))r.categories.forEach(c=>parts.push(`[${c.id||c.term_id||'?'}] ${c.name||'?'}`));
    else for(let[id,nm] of Object.entries(r.categories))parts.push(`[${id}] ${nm}`);
    el.textContent=parts.join(' | ');
}

// ─── Tools ───
async function refreshTools(toolsData){
    const t=toolsData||await pywebview.api.check_tools_status();
    const defs=[{key:'ffmpeg',name:'FFmpeg + FFprobe',desc:'Screenshots iz videa'},{key:'mediainfo',name:'MediaInfo CLI',desc:'Info o video fajlu'},{key:'torrenttools',name:'Torrenttools',desc:'Kreiranje .torrent fajla'}];
    const tb=document.getElementById('toolsBody');tb.innerHTML='';
    defs.forEach(d=>{
        const found=t[d.key];
        tb.innerHTML+=`<tr><td class="ps-3"><strong>${d.name}</strong><br><small class="text-muted">${d.desc}</small></td><td>${found?'<span class="badge bg-success">Pronadjen</span>':'<span class="badge bg-danger">Nedostaje</span>'}</td><td><small class="text-muted" style="font-size:11px;word-break:break-all">${esc(found||'')}</small></td><td><button class="btn btn-outline-light btn-sm" onclick="downloadTool('${d.key}')">${found?'Ponovo':'Preuzmi'}</button></td></tr>`;
    });
}
async function downloadTool(n){startPolling();await pywebview.api.download_tool(n);await refreshTools()}
async function downloadAllTools(){startPolling();await pywebview.api.download_all_tools();await refreshTools()}
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
    document.getElementById('cfgCleanup').checked=!!c.cleanup_after_upload;
    document.getElementById('cfgDelSs').checked=c.cleanup_delete_screenshots!==false;
    document.getElementById('cfgDelMi').checked=c.cleanup_delete_mediainfo!==false;
    document.getElementById('cfgDelTorrent').checked=!!c.cleanup_delete_torrent;
    document.getElementById('cfgDelNfo').checked=c.cleanup_delete_nfo!==false;
    document.getElementById('cfgDelImdb').checked=c.cleanup_delete_imdb!==false;
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
        cleanup_after_upload:document.getElementById('cfgCleanup').checked,
        cleanup_delete_screenshots:document.getElementById('cfgDelSs').checked,
        cleanup_delete_mediainfo:document.getElementById('cfgDelMi').checked,
        cleanup_delete_torrent:document.getElementById('cfgDelTorrent').checked,
        cleanup_delete_nfo:document.getElementById('cfgDelNfo').checked,
        cleanup_delete_imdb:document.getElementById('cfgDelImdb').checked
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
async function loadStats(statsData){
    const s=statsData||await pywebview.api.get_stats();
    if(!s)return;
    document.getElementById('statTotal').textContent=s.total||0;
    document.getElementById('statSize').textContent=s.total_size||'0 GB';
    document.getElementById('statLast').textContent=s.last_date||'-';
    document.getElementById('statQueue').textContent=queueItems.length;
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

// ─── Queue System ───
let queueItems=[];
let queueRunning=false;
function updateQueueBadge(){
    const b=document.getElementById('queueBadge');
    if(queueItems.length>0){b.style.display='flex';b.textContent=queueItems.length}else{b.style.display='none'}
    document.getElementById('statQueue').textContent=queueItems.length;
}
function renderQueue(){
    const el=document.getElementById('queueList');
    if(!queueItems.length){el.innerHTML='<p class="text-muted text-center" style="font-size:12px">Red cekanja je prazan. Dodajte foldere za upload.</p>';updateQueueBadge();return}
    el.innerHTML=queueItems.map((q,i)=>`<div class="card p-2 px-3 mb-1 d-flex flex-row align-items-center gap-2" style="font-size:12px" id="qi${i}"><span class="badge bg-secondary" style="min-width:22px">${i+1}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(q.path)}</span><span id="qiSt${i}" style="font-size:11px;min-width:80px;text-align:right">${q.status==='done'?'<span style=color:var(--accent)>✔ Zavrsen</span>':q.status==='error'?'<span style=color:#ef4444>✘ Greska</span>':q.status==='running'?'<span style=color:#F59E0B>⏳ U toku</span>':'<span style=color:var(--muted)>Ceka</span>'}</span><button class="btn btn-outline-danger btn-sm py-0 px-1" style="font-size:10px" onclick="queueRemove(${i})"><i class="bi bi-x"></i></button></div>`).join('');
    updateQueueBadge();
}
async function queueAddFolder(){
    const f=await pywebview.api.browse_folder();
    if(f&&!queueItems.find(q=>q.path===f)){queueItems.push({path:f,status:'waiting'});renderQueue();updateQueueBadge()}
}
function queueRemove(i){if(queueItems[i]&&queueItems[i].status==='waiting'){queueItems.splice(i,1);renderQueue()}}
function queueClear(){queueItems=queueItems.filter(q=>q.status==='running');renderQueue()}
async function queueStartAll(){
    if(queueRunning){toast('Red se vec izvrsava!','info');return}
    const pending=queueItems.filter(q=>q.status==='waiting');
    if(!pending.length){toast('Nema stavki za obradu!','error');return}
    queueRunning=true;
    document.getElementById('queueStartBtn').disabled=true;
    document.getElementById('queueProgress').style.display='block';
    const total=pending.length;
    document.getElementById('qTotal').textContent=total;
    let done=0;
    for(let i=0;i<queueItems.length;i++){
        if(queueItems[i].status!=='waiting')continue;
        queueItems[i].status='running';renderQueue();
        document.getElementById('qCurrent').textContent=done+1;
        document.getElementById('qStatus').textContent=queueItems[i].path.split('\\\\').pop()||queueItems[i].path;
        try{
            await pywebview.api.reset_for_batch(queueItems[i].path);
            const r1=await pywebview.api.search_imdb(queueItems[i].path);
            if(r1&&r1.results){const pick=await showImdbModal(r1.results);if(pick!==null)await pywebview.api.confirm_imdb(pick)}
            await pywebview.api.run_screenshots(queueItems[i].path);
            await pywebview.api.run_torrent(queueItems[i].path);
            const ud=await pywebview.api.get_upload_data();
            if(ud)await showUploadModal(ud);
            queueItems[i].status='done';done++;
        }catch(e){
            console.error('Queue error:',e);
            queueItems[i].status='error';
        }
        renderQueue();
        document.getElementById('qBar').style.width=((done)/total*100)+'%';
    }
    document.getElementById('qStatus').textContent=`Gotovo! ${done}/${total} uspesno.`;
    queueRunning=false;
    document.getElementById('queueStartBtn').disabled=false;
    toast(`Red zavrsen: ${done}/${total} uspesno.`,done===total?'success':'warning');
    await loadHistory();await loadStats();
}

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
// NO JS->Python calls here! Python pushes data via evaluate_js to avoid COM deadlock.
window.addEventListener('pywebviewready',function(){
    window._pywebviewReady=true;
});
function _initFromPython(d){
    try{
        if(d.config) loadSettings(d.config);
        if(d.tools) refreshTools(d.tools);
        if(d.history) renderHistory(d.history);
        if(d.stats) loadStats(d.stats);
    }catch(e){console.error('init:',e)}
    startPolling();
    setTimeout(checkForUpdate,3000);
}
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
        self._progress = 0
        self._status = "Spreman"
        self._lock = threading.Lock()
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

    # ─── internal helpers ─────────────────────────────────────────────

    def _log(self, msg):
        with self._lock:
            self._log_q.append(msg)

    def _tlog(self, msg):
        with self._lock:
            self._tlog_q.append(msg)

    def _ensure_item_dir(self, path):
        item_name = os.path.basename(os.path.normpath(path))
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
        return {"logs": logs, "tool_logs": tlogs,
                "progress": self._progress, "status": self._status}

    def browse_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def reset_for_batch(self, path):
        """Reset all state for a new batch item, then load existing data if any."""
        self.reset_from_step(0)
        self._log_q.clear()
        self._tlog_q.clear()
        result = self.check_existing_data(path)
        return result

    def check_existing_data(self, path):
        """Check if output folder has existing data from a previous run and load it."""
        item_name = os.path.basename(os.path.normpath(path))
        out_dir = os.path.join(CONFIG["output_dir"], item_name)
        if not os.path.isdir(out_dir):
            return {"loaded_steps": []}

        self.item_output_dir = out_dir
        loaded = []

        # Check IMDB
        imdb_file = os.path.join(out_dir, "imdb.txt")
        if os.path.exists(imdb_file):
            with open(imdb_file, "r", encoding="utf-8") as f:
                self.imdb_url = f.read().strip()
            if self.imdb_url:
                loaded.append(0)
                self._log(f"[LOAD] IMDB: {self.imdb_url}")
                # Try to restore TMDB data from IMDB
                imdb_match = re.search(r'tt\d+', self.imdb_url)
                if imdb_match and CONFIG.get("tmdb_api_key"):
                    try:
                        imdb_id = imdb_match.group(0)
                        find_data = tmdb_request(f"find/{imdb_id}?external_source=imdb_id")
                        item = None
                        if find_data.get("tv_results"):
                            self.is_tv = True
                            item = find_data["tv_results"][0]
                        elif find_data.get("movie_results"):
                            self.is_tv = False
                            item = find_data["movie_results"][0]
                        if item:
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
                mi_lower = self.mediainfo_text.lower()
                self.detected_subtitles = []
                if re.search(r'serbian|srpski|srp', mi_lower):
                    self.detected_subtitles.append("sr")
                if re.search(r'croatian|hrvatski|hrv', mi_lower):
                    self.detected_subtitles.append("hr")
                if re.search(r'bosnian|bosanski|bos', mi_lower):
                    self.detected_subtitles.append("ba")
            if has_ss and has_mi:
                loaded.append(1)

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

    def check_tools_status(self):
        t = check_all_tools()
        return {"ffmpeg": t["ffmpeg"] or "", "mediainfo": t["mediainfo"] or "",
                "torrenttools": t["torrenttools"] or ""}

    def download_tool(self, name):
        self._do_download(name)

    def download_all_tools(self):
        for t in ("ffmpeg", "mediainfo", "torrenttools"):
            self._do_download(t)

    def open_tools_dir(self):
        os.makedirs(TOOLS_DIR, exist_ok=True)
        os.startfile(TOOLS_DIR)

    # ─── Auto-check Tools ────────────────────────────────────────────

    def quick_check_tools(self):
        """Fast local-only check: are tools present on disk? No network."""
        finder = {"ffmpeg": get_ffmpeg_path, "mediainfo": get_mediainfo_path,
                  "torrenttools": get_torrenttools_path}
        missing = []
        for name in TOOL_INFO:
            if not finder[name]():
                missing.append(name)
        return {"missing": missing}

    def start_bg_tool_check(self):
        """Start auto-check in a background thread so it doesn't block JS bridge."""
        t = threading.Thread(target=self._bg_tool_check, daemon=True)
        t.start()

    def push_init_data(self):
        """Push ALL init data to JS via evaluate_js — no blocking JS->Python bridge."""
        import time
        # Wait for pywebview to be fully ready
        for _ in range(50):
            try:
                r = self.window.evaluate_js('window._pywebviewReady||false')
                if r:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        # Gather data
        history = []
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
        except Exception:
            pass
        total = len(history)
        total_bytes = sum(h.get('size', 0) for h in history)
        total_gb = total_bytes / 1073741824 if total_bytes else 0
        last_date = history[-1].get('date', '-') if history else '-'
        data = {
            'config': dict(CONFIG),
            'tools': {'ffmpeg': '', 'mediainfo': '', 'torrenttools': ''},
            'history': history,
            'stats': {'total': total, 'total_size': f'{total_gb:.1f} GB', 'last_date': last_date}
        }
        # Push to JS — this runs on a background thread so it won't block window moves
        try:
            self.window.evaluate_js(f'_initFromPython({json.dumps(data)})')
        except Exception:
            pass
        # Start bg tasks
        threading.Thread(target=self._bg_init_tools, daemon=True).start()
        threading.Thread(target=self._bg_update_check, daemon=True).start()

    def _bg_init_tools(self):
        """Detect tools + start auto-download in background, then notify JS."""
        try:
            tools = check_all_tools()
            tools_js = json.dumps({'ffmpeg': tools['ffmpeg'] or '', 'mediainfo': tools['mediainfo'] or '', 'torrenttools': tools['torrenttools'] or ''})
            if self.window:
                self.window.evaluate_js(f'refreshTools({tools_js})')
        except Exception:
            pass
        # Continue with auto-download of missing/outdated tools
        self._bg_tool_check()

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
        try:
            self._check_latest_versions()
        except Exception:
            pass
        installed = load_tool_versions()
        for name, info in TOOL_INFO.items():
            finder = {"ffmpeg": get_ffmpeg_path, "mediainfo": get_mediainfo_path,
                       "torrenttools": get_torrenttools_path}
            found = finder[name]()
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
            self._log("[ERR] TMDB API kljuc nije podesen!")
            return None

        encoded_query = urllib.parse.quote(clean_name)
        try:
            response = tmdb_request(f"search/multi?query={encoded_query}&include_adult=false")
        except Exception as e:
            self._log(f"[ERR] TMDB pretraga: {e}")
            return None

        results = response.get("results", [])[:5]
        if not results:
            self._log("[ERR] Nema rezultata.")
            return None

        self._tmdb_results = results
        return {"results": results}

    def confirm_imdb(self, index):
        if not self._tmdb_results or index >= len(self._tmdb_results):
            return

        selected = self._tmdb_results[index]
        search_type = "tv" if selected.get("media_type") == "tv" else "movie"

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
        self.tmdb_overview, self.tmdb_genres = tmdb_get_local(search_type, selected['id'], en_ov)
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

    # ─── Screenshots & MediaInfo ──────────────────────────────────────

    def run_screenshots(self, path):
        self._progress = 0
        self._status = "Screenshots & MediaInfo..."
        if not os.path.exists(path):
            self._log(f"[ERR] Putanja ne postoji: {path}")
            return {"ok": False}
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

                mi_lower = self.mediainfo_text.lower()
                self.detected_subtitles = []
                if re.search(r'serbian|srpski|srp', mi_lower):
                    self.detected_subtitles.append("sr")
                if re.search(r'croatian|hrvatski|hrv', mi_lower):
                    self.detected_subtitles.append("hr")
                if re.search(r'bosnian|bosanski|bos', mi_lower):
                    self.detected_subtitles.append("ba")
                if self.detected_subtitles:
                    self._log(f"  Titlovi: {', '.join(self.detected_subtitles)}")
            except Exception as e:
                self._log(f"[ERR] MediaInfo: {e}")
        else:
            self._log("[INFO] MediaInfo nije pronadjen")

        self._log(f"[OK] {len(self.screenshot_files)} screenshot-ova sacuvano")

    # ─── Torrent ──────────────────────────────────────────────────────

    def run_torrent(self, path):
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

        self._log(f"  Kreiranje: {item_name}")
        self._log(f"  Ovo moze potrajati za velike fajlove...")
        self._progress = -1  # indeterminate

        try:
            proc = subprocess.Popen(
                [tt_exe, "create", "--announce", CONFIG["announce_url"],
                 "--private", "--output", output_file, path],
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

        if self.is_tv:
            cat_key = ("TV_HD_Domace" if self.is_domace else "TV_HD_Strano") if self.is_hd else \
                      ("TV_SD_Domace" if self.is_domace else "TV_SD_Strano")
        else:
            cat_key = ("Film_HD_Domace" if self.is_domace else "Film_HD_Strano") if self.is_hd else \
                      ("Film_SD_Domace" if self.is_domace else "Film_SD_Strano")

        return {
            "imdb_url": self.imdb_url or "",
            "is_tv": self.is_tv, "is_domace": self.is_domace, "is_hd": self.is_hd,
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
            "category_id": CATEGORIES.get(cat_key, ""),
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

    def do_upload(self, category, name, trailer, anonymous):
        self._progress = 0
        self._status = "Upload u toku..."
        self._do_upload(category, name, trailer, anonymous)
        self._progress = 100
        self._status = "Zavrseno"

    def _do_upload(self, category, name, trailer, anonymous):
        self._log("\n═══ KORAK 4: UPLOAD ═══")
        if not CONFIG["cb_api_key"]:
            self._log("[ERR] CB API kljuc nije podesen!")
            return
        if not self.torrent_file or not os.path.exists(self.torrent_file):
            self._log("[ERR] Torrent fajl ne postoji")
            return

        self._log(f"  Naziv:      {name}")
        self._log(f"  Kategorija: {category}")
        if trailer:
            self._log(f"  Trailer:    {trailer}")

        # Opis: server sam generise sa TMDB-a na osnovu IMDB linka
        # Saljemo samo trailer ako postoji
        desc = ""
        if trailer:
            desc = f"[youtube]{trailer}[/youtube]"

        data = {
            "torrent_file": file_to_base64(self.torrent_file),
            "url": self.imdb_url or "",
            "name": name,
            "description": desc,
            "category": int(category),
            "anonymous": anonymous,
            "allow_comments": True,
        }

        if self.mediainfo_text:
            data["mediainfo"] = self.mediainfo_text
            self._log("  MediaInfo prilozen")

        if self.detected_subtitles:
            data["subtitles"] = self.detected_subtitles
            self._log(f"  Titlovi: {', '.join(self.detected_subtitles)}")

        if self.screenshot_files:
            ss_b64 = []
            for idx, sf in enumerate(self.screenshot_files[:10]):
                if os.path.exists(sf):
                    ss_b64.append(file_to_base64(sf))
                self._progress = int((idx + 1) * 30 / min(len(self.screenshot_files), 10))
            if ss_b64:
                data["screenshots"] = ss_b64
                self._log(f"  Screenshots: {len(ss_b64)}")

        search_dir = self.item_output_dir or CONFIG["output_dir"]
        nfo_path = os.path.join(search_dir, "info.nfo")
        if os.path.exists(nfo_path):
            data["nfo_file"] = file_to_base64(nfo_path)

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

        json_data = json.dumps(data).encode("utf-8")
        self._log(f"  Velicina zahteva: {len(json_data) / 1048576:.1f} MB")
        self._log("  Slanje na crnaberza.com...")
        self._progress = 40

        req = urllib.request.Request(
            "https://www.crnaberza.com/wp-json/cb/v1/upload",
            data=json_data, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("X-API-Key", CONFIG["cb_api_key"])

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw_response = resp.read().decode("utf-8")
                result = json.loads(raw_response)

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

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._log(f"[ERR] HTTP {e.code}: {body}")
        except Exception as e:
            self._log(f"[ERR] Upload: {e}")

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

            self._log("\n  Cekanje 60 sekundi za XBT tracker sinhronizaciju...")
            for i in range(60, 0, -1):
                self._status = f"XBT sync: {i}s preostalo..."
                self._progress = 70 + int((60 - i) * 30 / 60)
                time.sleep(1)
            self._log("  XBT sinhronizacija zavrsena!")

            download_path = CONFIG["download_path"]
            os.makedirs(download_path, exist_ok=True)
            final_path = os.path.join(download_path, filename)
            with open(final_path, "wb") as f:
                f.write(torrent_bytes)
            self._log(f"[OK] Torent sacuvan: {final_path}")
        except Exception as e:
            self._log(f"[ERR] Download/seed: {e}")

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
        # Debug files
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

        if self.tmdb_genres:
            desc += f"\n\n[b]Zanrovi:[/b] {', '.join(self.tmdb_genres)}"

        if self.imdb_url:
            desc += f"\n\n[url={self.imdb_url}]IMDB[/url]"

        if trailer:
            desc += f"\n\n[youtube]{trailer}[/youtube]"

        return desc

    def get_upload_history(self):
        """Load upload history from JSON file."""
        if not os.path.exists(HISTORY_FILE):
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

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
        except Exception:
            pass
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
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Crna Berza Upload Tool").Show($toast)
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
                categories = json.loads(resp.read().decode("utf-8"))
            return {"categories": categories}
        except Exception as e:
            return {"error": str(e)}

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

if __name__ == "__main__":
    api = Api()
    window = webview.create_window(
        "Crna Berza Upload Tool V1",
        html=HTML_TEMPLATE,
        js_api=api,
        width=1100,
        height=800,
        min_size=(900, 650),
    )
    api.window = window
    def _on_started():
        threading.Thread(target=api.push_init_data, daemon=True).start()
    webview.start(_on_started)
    os._exit(0)

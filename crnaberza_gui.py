#!/usr/bin/env python3
"""Crna Berza Upload Tool — pywebview + Bootstrap 5 GUI"""

import os, sys, re, json, base64, shutil, subprocess, threading, time, zipfile, tempfile
import urllib.parse, urllib.request
from pathlib import Path
from io import BytesIO

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
    "announce_url": "http://www.crnaberza.com/announce",
    "screenshot_count": 10, "skip_start_percent": 5, "skip_end_percent": 5,
}


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
:root{--bg:#0a0d14;--bg2:#0f121a;--bg3:#111827;--accent:#10b981;--accent2:#059669;--accent-glow:rgba(16,185,129,.25);--border:rgba(255,255,255,0.06);--border-solid:#1f2937;--text:#e5e7eb;--muted:#94a3b8}
*{scrollbar-width:thin;scrollbar-color:#1f2937 var(--bg)}
body{background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,sans-serif,'Segoe UI';overflow:hidden;height:100vh;margin:0}
.sidebar{width:200px;position:fixed;left:0;top:0;bottom:0;background:rgba(10,13,20,0.95);border-right:1px solid var(--border);z-index:100;display:flex;flex-direction:column}
.sidebar::after{content:'';position:absolute;top:0;right:0;bottom:0;width:1px;background:linear-gradient(180deg,transparent,rgba(16,185,129,0.3),transparent)}
.sidebar .logo{padding:18px 15px;text-align:center;border-bottom:1px solid var(--border)}
.sidebar .logo h5{margin:0;font-weight:800;letter-spacing:.5px;background:linear-gradient(135deg,#10b981 0%,#34d399 40%,#6ee7b7 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sidebar .logo small{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:1px}
.sidebar .nav{flex:1;padding-top:8px}
.sidebar .nav-link{color:var(--muted);padding:11px 20px;font-size:13px;transition:all .2s;border-left:3px solid transparent;display:flex;align-items:center;gap:10px}
.sidebar .nav-link:hover{color:#fff;background:rgba(16,185,129,.08)}
.sidebar .nav-link:hover i{color:var(--accent);filter:drop-shadow(0 0 6px rgba(16,185,129,.6))}
.sidebar .nav-link.active{color:var(--accent);background:rgba(16,185,129,.1);border-left-color:var(--accent)}
.sidebar .nav-link.active i{color:var(--accent);filter:drop-shadow(0 0 8px rgba(16,185,129,.7))}
.sidebar .nav-link i{font-size:16px;width:20px;text-align:center;transition:all .2s}
.main-content{margin-left:200px;padding:20px 25px;height:calc(100vh - 34px);overflow-y:auto}
.card{background:var(--bg2);border:1px solid var(--border-solid);border-radius:10px}
.card-header{background:transparent;border-bottom:1px solid var(--border-solid);font-size:13px;font-weight:600}
.btn-accent{background:linear-gradient(135deg,#059669,#10b981);color:#fff;border:none;font-weight:600;transition:all .2s;box-shadow:0 0 20px var(--accent-glow),0 0 1px rgba(16,185,129,0.5) inset}
.btn-accent:hover,.btn-accent:focus{background:linear-gradient(135deg,#10b981,#34d399);color:#fff;box-shadow:0 0 28px rgba(16,185,129,.45),0 0 1px rgba(16,185,129,.8) inset;transform:translateY(-1px)}
.btn-accent:active{background:#047857;color:#fff;transform:translateY(0)}
.form-control,.form-select{background:var(--bg3);border-color:var(--border-solid);color:var(--text);font-size:13px}
.form-control:focus,.form-select:focus{background:var(--bg3);border-color:var(--accent);color:var(--text);box-shadow:0 0 0 2px rgba(16,185,129,.2)}
.form-control::placeholder{color:var(--muted)}
.log-box{background:#060810;color:#8b949e;font-family:'Cascadia Code','Fira Code','Consolas',monospace;font-size:12px;border-radius:8px;padding:12px;overflow-y:auto;white-space:pre-wrap;word-wrap:break-word;border:1px solid var(--border-solid)}
.progress{height:5px;background:var(--border-solid);border-radius:3px}
.progress-bar{background:linear-gradient(90deg,#059669,#10b981);transition:width .3s}
.status-bar{position:fixed;bottom:0;left:200px;right:0;background:rgba(10,13,20,0.95);border-top:1px solid var(--border);padding:5px 20px;font-size:11px;color:var(--muted);z-index:100;height:34px;display:flex;align-items:center;justify-content:space-between}
.status-bar::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(16,185,129,0.3),transparent)}
.imdb-card{background:var(--bg2);border:1px solid var(--border-solid);border-radius:10px;transition:all .2s;cursor:default}
.imdb-card:hover{border-color:var(--accent);box-shadow:0 4px 20px var(--accent-glow);transform:translateY(-1px)}
.poster-img{width:80px;min-height:120px;border-radius:8px;object-fit:cover;background:#111827}
.poster-ph{width:80px;min-height:120px;border-radius:8px;background:#111827;display:flex;align-items:center;justify-content:center}
.upload-section{background:var(--bg2);border-radius:10px;padding:16px;margin-bottom:12px;border:1px solid var(--border-solid)}
.upload-section .lbl{color:var(--accent);font-weight:600;font-size:12px;min-width:100px}
.table-dark{--bs-table-bg:transparent}
.table-dark td,.table-dark th{border-color:var(--border-solid)}
.modal-content{background:var(--bg);border:1px solid var(--border-solid)}
.modal-header,.modal-footer{border-color:var(--border-solid)}
.ss-thumb{width:160px;height:100px;object-fit:cover;border-radius:6px;border:1px solid var(--border-solid)}
.page{display:none}.page.active{display:block}
.page-title{font-size:18px;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.page-title i{color:var(--accent);font-size:22px}
.form-text{color:var(--muted) !important;font-size:11px}
.badge{font-weight:500}
.btn-outline-light{border-color:var(--border-solid);color:var(--text)}
.btn-outline-light:hover{background:rgba(16,185,129,.08);border-color:var(--accent);color:#fff}
.preview-section{background:#111827;border:1px solid #1f2937;border-radius:12px;overflow:hidden;margin-bottom:12px}
.preview-header{padding:10px 16px;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.05em}
.preview-header i{color:#10b981;font-size:14px}
.preview-body{padding:16px}
.info-tbl{width:100%;font-size:13px}
.info-tbl td{padding:7px 12px;border-bottom:1px solid rgba(31,41,55,0.5)}
.info-tbl .il{color:#6b7280;width:120px;white-space:nowrap}
.info-tbl .iv{color:#d1d5db}
.mi-grid{display:grid;grid-template-columns:1fr 1fr 1fr}
.mi-grid>div{padding:14px 16px}
.mi-grid>div:not(:last-child){border-right:1px solid #1f2937}
.mi-title{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px}
.mi-tbl{width:100%;font-size:11px}
.mi-tbl td{padding:2px 0}
.mi-tbl .mk{color:#6b7280;padding-right:10px;white-space:nowrap}
.mi-tbl .mv{color:#e5e7eb}
.ss-row{display:flex;gap:10px;overflow-x:auto;padding:4px}
.ss-row::-webkit-scrollbar{height:6px}
.ss-row::-webkit-scrollbar-thumb{background:#374151;border-radius:3px}
.ss-row img{width:200px;height:125px;object-fit:cover;border-radius:8px;border:1px solid #1f2937;flex-shrink:0;transition:opacity .2s}
.ss-row img:hover{opacity:.8}
.cat-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;background:rgba(6,78,59,0.4);border:1px solid rgba(4,120,87,0.5);color:#6ee7b7}
.imdb-link{color:#facc15;text-decoration:none;font-size:13px}
.imdb-link:hover{color:#fde047}
.sub-tag{display:inline-flex;align-items:center;font-size:11px;background:#1f2937;border:1px solid #374151;border-radius:4px;padding:2px 8px;color:#d1d5db}
.startup-overlay{position:fixed;inset:0;background:var(--bg);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;transition:opacity .6s}.startup-overlay.fade-out{opacity:0;pointer-events:none}
.startup-spinner{width:36px;height:36px;border:3px solid var(--border-solid);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.startup-title{font-size:22px;font-weight:800;margin-top:20px;background:linear-gradient(135deg,#10b981,#34d399,#6ee7b7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}.startup-status{color:var(--muted);font-size:12px;margin-top:10px;min-height:16px}
.pipeline{display:flex;align-items:flex-start;user-select:none}.pipe-step{display:flex;flex-direction:column;align-items:center;cursor:pointer;position:relative;z-index:1;flex:0 0 auto}
.pipe-circle{width:50px;height:50px;border-radius:50%;background:var(--bg3);border:2px solid var(--border-solid);display:flex;align-items:center;justify-content:center;font-size:18px;color:var(--muted);transition:all .3s}
.pipe-step:hover:not(.locked) .pipe-circle{border-color:rgba(16,185,129,.5);color:var(--accent);box-shadow:0 0 20px rgba(16,185,129,.15)}
.pipe-step.locked{cursor:not-allowed;opacity:.35}.pipe-step.locked .pipe-circle{pointer-events:none}
.pipe-step.done .pipe-circle{background:var(--accent2);border-color:var(--accent);color:#fff;box-shadow:0 0 20px var(--accent-glow)}.pipe-step.active .pipe-circle{background:linear-gradient(135deg,#059669,#10b981);border-color:var(--accent);color:#fff;box-shadow:0 0 30px rgba(16,185,129,.4);animation:pulse-glow 2s infinite}
.pipe-undo{font-size:9px;margin-top:4px;color:var(--muted);cursor:pointer;opacity:0;transition:opacity .2s;text-transform:uppercase;letter-spacing:.5px}.pipe-step.done .pipe-undo{opacity:1}.pipe-undo:hover{color:#ef4444}
@keyframes pulse-glow{0%,100%{box-shadow:0 0 20px rgba(16,185,129,.3)}50%{box-shadow:0 0 35px rgba(16,185,129,.5)}}
.pipe-label{font-size:10px;margin-top:8px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px;transition:color .2s}
.pipe-step.done .pipe-label,.pipe-step.active .pipe-label{color:var(--accent)}
.pipe-line{flex:1;height:2px;background:var(--border-solid);margin:25px 4px 0;position:relative;overflow:hidden}.pipe-line::after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,var(--accent2),var(--accent));transform:scaleX(0);transform-origin:left;transition:transform .5s ease}
.pipe-line.filled::after{transform:scaleX(1)}
.toast-wrap{position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px}.app-toast{background:rgba(17,24,39,.95);backdrop-filter:blur(12px);border:1px solid var(--border-solid);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:10px;font-size:12px;color:var(--text);box-shadow:0 8px 30px rgba(0,0,0,.4);animation:toastIn .3s ease;min-width:260px}
.app-toast.out{animation:toastOut .3s ease forwards}
.app-toast.success{border-left:3px solid #10b981}.app-toast.error{border-left:3px solid #ef4444}
.app-toast.info{border-left:3px solid #3b82f6}
.app-toast i{font-size:16px;flex-shrink:0}
.app-toast.success i{color:#10b981}
.app-toast.error i{color:#ef4444}
.app-toast.info i{color:#3b82f6}
@keyframes toastIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes toastOut{from{opacity:1}to{transform:translateX(100%);opacity:0}}
</style>
</head>
<body>

<div class="startup-overlay" id="startupOverlay">
    <div class="startup-spinner"></div>
    <div class="startup-title">Crna Berza</div>
    <div class="startup-status" id="startupStatus">Provera alata...</div>
</div>
<div class="toast-wrap" id="toastWrap"></div>

<!-- Sidebar -->
<div class="sidebar">
    <div class="logo">
        <h5><i class="bi bi-film"></i> Crna Berza</h5>
        <small>Upload Tool V1 by Vucko</small>
    </div>
    <nav class="nav flex-column">
        <a class="nav-link active" href="#" data-page="main"><i class="bi bi-house-fill"></i>Glavni</a>
        <a class="nav-link" href="#" data-page="tools"><i class="bi bi-wrench-adjustable"></i>Alati</a>
        <a class="nav-link" href="#" data-page="settings"><i class="bi bi-gear-fill"></i>Podesavanja</a>
    </nav>
</div>

<!-- Main Content -->
<div class="main-content">

<!-- PAGE: Main -->
<div id="page-main" class="page active">
    <div class="page-title"><i class="bi bi-play-circle-fill"></i> Glavni</div>

    <div class="card p-3 mb-3">
        <label class="form-label fw-semibold mb-2" style="font-size:13px">Putanja do foldera / video fajla</label>
        <div class="input-group">
            <input type="text" class="form-control" id="pathInput" placeholder="C:\\Movies\\...">
            <button class="btn btn-outline-light" onclick="browsePath()"><i class="bi bi-folder2-open me-1"></i>Izaberi</button>
        </div>
    </div>

    <div class="card p-3 mb-3">
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

    <div class="progress mb-3"><div class="progress-bar" id="progressBar" style="width:0%"></div></div>

    <div class="card mb-2">
        <div class="card-header d-flex justify-content-between align-items-center px-3 py-2">
            <span><i class="bi bi-terminal me-1"></i>Log</span>
            <button class="btn btn-sm btn-outline-light py-0 px-2" style="font-size:11px" onclick="clearLog()">Obrisi</button>
        </div>
        <div class="card-body p-0">
            <div class="log-box" id="logOutput" style="height:320px;border:none;border-radius:0 0 10px 10px"></div>
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
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-film me-2" style="color:#10b981"></i>Izaberite film / seriju</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body" id="imdbBody"></div>
</div></div></div>

<!-- Upload Modal -->
<div class="modal fade" id="uploadModal" tabindex="-1" data-bs-backdrop="static">
<div class="modal-dialog modal-xl modal-dialog-scrollable">
<div class="modal-content">
    <div class="modal-header"><h6 class="modal-title"><i class="bi bi-cloud-upload me-2" style="color:#10b981"></i>Upload Pregled</h6>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
    <div class="modal-body" id="uploadBody"></div>
    <div class="modal-footer">
        <button class="btn btn-outline-light btn-sm" data-bs-dismiss="modal">Otkazi</button>
        <button class="btn btn-accent px-4" id="btnDoUpload" onclick="doUpload()"><i class="bi bi-cloud-upload me-1"></i>Upload</button>
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

// ─── Helpers ───
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}
function clearLog(){document.getElementById('logOutput').innerHTML=''}
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
            if(u.logs&&u.logs.length){const el=document.getElementById('logOutput');u.logs.forEach(m=>{el.innerHTML+=esc(m)+'\\n'});el.scrollTop=el.scrollHeight}
            if(u.tool_logs&&u.tool_logs.length){const el=document.getElementById('toolsLog');u.tool_logs.forEach(m=>{el.innerHTML+=esc(m)+'\\n'});el.scrollTop=el.scrollHeight}
            const pb=document.getElementById('progressBar');
            if(u.progress<0){pb.style.width='100%';pb.className='progress-bar progress-bar-striped progress-bar-animated'}
            else{pb.style.width=u.progress+'%';pb.className='progress-bar'}
            document.getElementById('statusText').textContent=u.status;
        }catch(e){}
    },250);
}

// ─── Browse ───
async function browsePath(){const r=await pywebview.api.browse_folder();if(r)document.getElementById('pathInput').value=r}
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
        if(step==='imdb'){const r=await pywebview.api.search_imdb(path);if(r&&r.results){const i=await showImdbModal(r.results);if(i!==null)await pywebview.api.confirm_imdb(i)}}
        else if(step==='screenshots')await pywebview.api.run_screenshots(path);
        else if(step==='torrent')await pywebview.api.run_torrent(path);
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
            card.innerHTML=`${poster}<div class="flex-grow-1"><h6 class="mb-1">${esc(t)} <span class="text-muted">(${yr})</span></h6>${ot&&ot!==t?`<small class="text-muted d-block">${esc(ot)}</small>`:''}<small class="fw-bold" style="color:#10b981">${stars} ${r}/10 (${v}) &nbsp;|&nbsp; ${tp} &nbsp;|&nbsp; ${lang}</small>${ov?`<p class="text-muted small mt-1 mb-0">${esc(ov)}${(item.overview||'').length>200?'...':''}</p>`:''}</div><div class="d-flex align-items-center ms-2"><button class="btn btn-accent btn-sm px-3">Izaberi</button></div>`;
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
                miHtml+='<div style="padding:12px 16px;border-top:1px solid #1f2937"><div class="mi-title">SUBTITLES</div><div class="d-flex flex-wrap gap-1">';
                mi.subtitles.forEach(s=>{miHtml+=`<span class="sub-tag">${esc(s)}</span>`;});
                miHtml+='</div></div>';
            }
            miHtml+='</div>';
        }

        let ssHtml='';
        if(data.screenshot_count>0){
            try{const thumbs=await pywebview.api.get_screenshot_thumbnails();
            if(thumbs&&thumbs.length){
                ssHtml='<div class="preview-section"><div class="preview-header"><i class="bi bi-images"></i> SCREENSHOTS <span style="color:#6b7280;font-weight:400;text-transform:none;margin-left:4px">('+data.screenshot_count+')</span></div><div class="preview-body"><div class="ss-row">';
                thumbs.forEach(t=>{if(t)ssHtml+=`<img src="${t}">`;});
                ssHtml+='</div></div></div>';
            }}catch(e){}
        }

        const posterHtml=data.poster_url
            ?`<img src="${data.poster_url}" style="width:100%;border-radius:8px;box-shadow:0 4px 15px rgba(0,0,0,0.4)">`
            :'<div style="width:100%;padding-top:150%;background:#1f2937;border-radius:8px;position:relative"><i class="bi bi-film" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:36px;color:#374151"></i></div>';

        const imdbId=(data.imdb_url||'').match(/tt\\d+/);
        const imdbHtml=imdbId
            ?`<a class="imdb-link" href="#" onclick="return false"><i class="bi bi-star-fill me-1"></i>${imdbId[0]}</a>`
            :'<span style="color:#6b7280">\\u2014</span>';

        const titleText=data.tmdb_title?esc(data.tmdb_title)+(data.tmdb_year?' ('+data.tmdb_year+')':''):'';

        const subsHtml=(data.subtitles&&data.subtitles.length)
            ?data.subtitles.map(s=>`<span class="sub-tag">${esc(s.toUpperCase())}</span>`).join('')
            :'<span style="color:#6b7280">\\u2014</span>';

        body.innerHTML=`
        <div class="preview-section"><div class="preview-body"><div class="d-flex gap-4">
            <div style="width:220px;flex-shrink:0">${posterHtml}</div>
            <div class="flex-grow-1">
                <table class="info-tbl">
                <tr><td class="il">Kategorija:</td><td class="iv"><span class="cat-badge">${esc(data.category_name)}</span>
                    <input type="text" class="form-control form-control-sm d-inline-block ms-2" id="upCatId" value="${data.category_id}" style="width:60px;font-size:11px;padding:2px 6px;vertical-align:middle">
                    <button class="btn btn-outline-light btn-sm ms-1 py-0 px-2" style="font-size:10px" onclick="fetchCats()">&#9776;</button>
                    <div id="catInfo" style="font-size:10px;color:#6b7280;margin-top:4px"></div></td></tr>
                <tr><td class="il">Tip:</td><td class="iv">${tip} / ${por}</td></tr>
                <tr><td class="il">Kvalitet:</td><td class="iv">${kval}</td></tr>
                <tr><td class="il">Torrent:</td><td class="iv" style="font-size:12px;word-break:break-all">${esc(data.torrent_file||'Nema')}</td></tr>
                <tr><td class="il">Titlovi:</td><td class="iv">${subsHtml}</td></tr>
                <tr><td class="il">IMDB / Eksterni:</td><td class="iv">${imdbHtml}</td></tr>
                <tr><td class="il">Screenshots:</td><td class="iv">${data.screenshot_count} fajlova</td></tr>
                </table>
                <div class="mt-2"><div class="form-check"><input class="form-check-input" type="checkbox" id="upAnon"><label class="form-check-label" for="upAnon" style="font-size:12px;color:#94a3b8">Anonimni upload</label></div></div>
            </div>
        </div></div></div>
        <div class="preview-section"><div class="preview-header"><i class="bi bi-text-left"></i> OPIS</div><div class="preview-body">
            ${titleText?`<h5 style="text-align:center;font-weight:700;margin-bottom:12px">${titleText}</h5>`:''}
            ${data.tmdb_overview?`<p style="color:#94a3b8;font-size:13px;margin-bottom:12px">${esc(data.tmdb_overview)}</p>`:''}
            <div class="mb-2"><label class="d-block mb-1" style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;font-weight:600">Naziv torrenta</label>
            <input type="text" class="form-control" id="upName" value="${esc(data.auto_name)}"></div>
            <div><label class="d-block mb-1" style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;font-weight:600">Dodatni opis</label>
            <textarea class="form-control" id="upDesc" rows="2" placeholder="Opcioni opis..."></textarea></div>
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
    const desc=document.getElementById('upDesc').value.trim();
    const anon=document.getElementById('upAnon').checked;
    if(!cat||!name){toast('Unesite kategoriju i naziv!','error');return}
    const modal=bootstrap.Modal.getInstance(document.getElementById('uploadModal'));
    if(modal)modal.hide();
    await pywebview.api.do_upload(parseInt(cat),name,desc,anon);
    if(uploadResolve){uploadResolve();uploadResolve=null}
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
async function refreshTools(){
    const t=await pywebview.api.check_tools_status();
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
async function loadSettings(){
    const c=await pywebview.api.get_config();
    document.getElementById('cfgTmdb').value=c.tmdb_api_key||'';
    document.getElementById('cfgCb').value=c.cb_api_key||'';
    document.getElementById('cfgOutput').value=c.output_dir||'';
    document.getElementById('cfgDownload').value=c.download_path||'';
    document.getElementById('cfgAnnounce').value=c.announce_url||'';
    document.getElementById('cfgSsCount').value=c.screenshot_count||10;
}
async function saveSettings(){
    await pywebview.api.save_settings({
        tmdb_api_key:document.getElementById('cfgTmdb').value,
        cb_api_key:document.getElementById('cfgCb').value,
        output_dir:document.getElementById('cfgOutput').value,
        download_path:document.getElementById('cfgDownload').value,
        announce_url:document.getElementById('cfgAnnounce').value,
        screenshot_count:parseInt(document.getElementById('cfgSsCount').value)||10
    });
    toast('Podesavanja sacuvana!','success');
}

// ─── Init ───
window.addEventListener('pywebviewready',async()=>{
    startPolling();await loadSettings();
    var ov=document.getElementById('startupOverlay');
    var st=document.getElementById('startupStatus');
    try{
        st.textContent='Provera alata i verzija...';
        var r=await pywebview.api.auto_check_tools();
        if(r.downloaded&&r.downloaded.length>0){st.textContent=r.downloaded.length+' alat(a) preuzeto/azurirano!';await new Promise(function(res){setTimeout(res,1500)})}
        else{st.textContent='Svi alati spremni';await new Promise(function(res){setTimeout(res,800)})}
    }catch(e){st.textContent='Greska pri proveri alata';console.error(e);await new Promise(function(res){setTimeout(res,1000)})}
    ov.classList.add('fade-out');setTimeout(function(){ov.remove()},600);
    await refreshTools()});
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

    def auto_check_tools(self):
        """Auto-download missing tools, update outdated ones on startup."""
        self._check_latest_versions()
        installed = load_tool_versions()
        downloaded = []
        for name, info in TOOL_INFO.items():
            finder = {"ffmpeg": get_ffmpeg_path, "mediainfo": get_mediainfo_path,
                       "torrenttools": get_torrenttools_path}
            found = finder[name]()
            local_ver = installed.get(name, "")
            if not found or local_ver != info["version"]:
                self._tlog(f"Auto-preuzimanje: {name}...")
                self._do_download(name)
                downloaded.append(name)
            else:
                self._tlog(f"{name} v{local_ver} - OK")
        return {"downloaded": downloaded}

    def _check_latest_versions(self):
        """Try to fetch latest tool versions from online sources."""
        try:
            req = urllib.request.Request("https://www.gyan.dev/ffmpeg/builds/release-version",
                                         headers={"User-Agent": "CrnaBerza/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                ver = resp.read().decode().strip()
            if ver:
                TOOL_INFO["ffmpeg"]["version"] = ver
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/MediaArea/MediaInfo/releases/latest",
                headers={"User-Agent": "CrnaBerza/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
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
            with urllib.request.urlopen(req, timeout=3) as resp:
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
        title = selected.get("title") or selected.get("name")
        self.tmdb_title = title
        self.tmdb_year = (selected.get("release_date") or selected.get("first_air_date", ""))[:4]
        if selected.get("poster_path"):
            self.tmdb_poster_url = f"https://image.tmdb.org/t/p/w342{selected['poster_path']}"
        self.tmdb_overview = selected.get("overview", "")
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
        self._do_screenshots(path)
        self._progress = 100
        self._status = "Screenshots zavrseno"

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
        self._do_torrent(path)
        self._progress = 100
        self._status = "Torrent kreiran"

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

    def do_upload(self, category, name, description, anonymous):
        self._progress = 0
        self._status = "Upload u toku..."
        self._do_upload(category, name, description, anonymous)
        self._progress = 100
        self._status = "Zavrseno"

    def _do_upload(self, category, name, custom_desc, anonymous):
        self._log("\n═══ KORAK 4: UPLOAD ═══")
        if not CONFIG["cb_api_key"]:
            self._log("[ERR] CB API kljuc nije podesen!")
            return
        if not self.torrent_file or not os.path.exists(self.torrent_file):
            self._log("[ERR] Torrent fajl ne postoji")
            return

        self._log(f"  Naziv:      {name}")
        self._log(f"  Kategorija: {category}")

        data = {
            "torrent_file": file_to_base64(self.torrent_file),
            "url": self.imdb_url or "",
            "name": name,
            "description": custom_desc if custom_desc else "Auto-generated from IMDB",
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
                result = json.loads(resp.read().decode("utf-8"))

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
    webview.start()
    os._exit(0)

#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# crnaberza.py - Sve u jednom: IMDB pretraga, screenshots, mediainfo,
#                torrent kreiranje i upload na crnaberza.com
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys
import re
import json
import base64
import shutil
import subprocess
import urllib.parse
import urllib.request
import argparse
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# KONFIGURACIJA - Prilagodi ove vrednosti
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    "tmdb_api_key": "12345abcde",           # TMDB API ključ (themoviedb.org)
    "cb_api_key": "",                        # Crna Berza API ključ
    "mediainfo_path": r"C:\tools\MediaInfo_CLI_26.01_Windows_x64\MediaInfo.exe",
    "output_dir": r"C:\Users\Administrator\Videos\api",
    "announce_url": "http://www.crnaberza.com/announce",
    "screenshot_count": 10,
    "skip_start_percent": 5,
    "skip_end_percent": 5,
}

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".m2ts", ".wmv", ".mov")


# ═══════════════════════════════════════════════════════════════════════════════
# POMOĆNE FUNKCIJE
# ═══════════════════════════════════════════════════════════════════════════════

def print_header(text):
    print(f"\n{'═' * 65}")
    print(f"  {text}")
    print(f"{'═' * 65}\n")


def print_info(text):
    print(f"  [INFO] {text}")


def print_ok(text):
    print(f"  [OK]   {text}")


def print_err(text):
    print(f"  [ERR]  {text}")


def tmdb_request(endpoint):
    url = f"https://api.themoviedb.org/3/{endpoint}"
    if "?" in url:
        url += f"&api_key={CONFIG['tmdb_api_key']}"
    else:
        url += f"?api_key={CONFIG['tmdb_api_key']}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def clean_folder_name(folder_name):
    """Izvlači naziv, godinu i sezonu iz imena foldera."""
    clean = folder_name
    year = None
    season = None

    year_match = re.search(r'(19|20)\d{2}', clean)
    if year_match:
        year = year_match.group(0)

    season_match = re.search(r'S(\d{1,2})', clean, re.IGNORECASE)
    if season_match:
        season = int(season_match.group(1))

    clean = clean.replace('.', ' ')
    clean = re.sub(r'\s*(19|20)\d{2}.*$', '', clean)
    clean = re.sub(r'\s+S\d{1,2}.*$', '', clean, flags=re.IGNORECASE)
    clean = clean.strip()

    return clean, year, season


def find_video_file(path):
    """Pronalazi najveći video fajl u folderu."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
        return str(p)

    videos = []
    for ext in VIDEO_EXTENSIONS:
        videos.extend(p.rglob(f"*{ext}"))

    if not videos:
        return None

    return str(max(videos, key=lambda f: f.stat().st_size))


def format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def file_to_base64(filepath):
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. IMDB PRETRAGA (preko TMDB)
# ═══════════════════════════════════════════════════════════════════════════════

def search_imdb(path):
    print_header("KORAK 1: IMDB PRETRAGA")

    folder_name = os.path.basename(os.path.normpath(path))
    clean_name, year, season = clean_folder_name(folder_name)

    print_info(f"Folder:   {folder_name}")
    print_info(f"Pretraga: {clean_name}")
    if year:
        print_info(f"Godina:   {year}")
    if season:
        print_info(f"Sezona:   {season}")
    print()

    # Pretraga TMDB
    print_info("Pretraga TMDB...")
    encoded_query = urllib.parse.quote(clean_name)
    try:
        response = tmdb_request(f"search/multi?query={encoded_query}&include_adult=false")
    except Exception as e:
        print_err(f"TMDB pretraga nije uspela: {e}")
        return None

    results = response.get("results", [])
    if not results:
        print_err("Nema rezultata.")
        print_info(f"Pokušajte ručno: https://www.imdb.com/find?q={encoded_query}")
        return None

    results = results[:5]
    print_info(f"Pronađeno {len(results)} rezultata\n")

    # Prikaz rezultata
    print("  Rezultati:\n")
    for i, item in enumerate(results):
        media_type = item.get("media_type", "?")
        title = item.get("title") or item.get("name") or "Nepoznato"
        date = item.get("release_date") or item.get("first_air_date") or ""
        item_year = date[:4] if len(date) >= 4 else "????"
        print(f"    [{i + 1}] {title} ({item_year}) [{media_type}]")

    print()
    selection = input(f"  Izaberite [1-{len(results)}] ili Enter za [1]: ").strip()
    if not selection:
        selection = "1"

    try:
        idx = int(selection) - 1
        if idx < 0 or idx >= len(results):
            raise ValueError()
    except ValueError:
        print_err("Pogrešan izbor")
        return None

    selected = results[idx]
    search_type = "tv" if selected.get("media_type") == "tv" else "movie"

    # Preuzimanje IMDB ID-a
    print_info("Preuzimanje IMDB ID-a...")
    try:
        details = tmdb_request(f"{search_type}/{selected['id']}/external_ids")
    except Exception as e:
        print_err(f"Nije moguće preuzeti IMDB ID: {e}")
        return None

    imdb_id = details.get("imdb_id")
    if not imdb_id:
        print_err("IMDB ID nije pronađen")
        return None

    imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
    title = selected.get("title") or selected.get("name")

    print_ok(f"Pronađeno: {title}")
    print_ok(f"IMDB URL:  {imdb_url}")

    # Sačuvaj u fajl
    imdb_file = os.path.join(CONFIG["output_dir"], "imdb.txt")
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    with open(imdb_file, "w", encoding="utf-8") as f:
        f.write(imdb_url)
    print_ok(f"Sačuvano u: {imdb_file}")

    return imdb_url


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SCREENSHOTS I MEDIAINFO
# ═══════════════════════════════════════════════════════════════════════════════

def generate_screenshots_and_mediainfo(path):
    print_header("KORAK 2: SCREENSHOTS & MEDIAINFO")

    video_path = find_video_file(path)
    if not video_path:
        print_err("Video fajl nije pronađen")
        return None, None

    # Provera FFmpeg
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print_err("FFmpeg/FFprobe nije pronađen u PATH-u")
        return None, None

    video_name = os.path.basename(video_path)
    screenshots_dir = os.path.join(CONFIG["output_dir"], "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    # Obriši stare screenshots
    for f in Path(screenshots_dir).glob("*.jpg"):
        f.unlink()

    print_info(f"Video: {video_name}")

    # Trajanje i rezolucija
    try:
        duration_out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30
        )
        duration = float(duration_out.stdout.strip())
    except Exception as e:
        print_err(f"Nije moguće dobiti trajanje videa: {e}")
        return None, None

    try:
        res_out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path],
            capture_output=True, text=True, timeout=30
        )
        resolution = res_out.stdout.strip()
    except Exception:
        resolution = "nepoznato"

    print_info(f"Trajanje:   {format_duration(duration)}")
    print_info(f"Rezolucija: {resolution}")

    count = CONFIG["screenshot_count"]
    start_time = duration * (CONFIG["skip_start_percent"] / 100)
    end_time = duration * (1 - CONFIG["skip_end_percent"] / 100)
    interval = (end_time - start_time) / (count + 1)

    print_info(f"Generisanje {count} screenshot-ova...")

    screenshot_files = []
    for i in range(1, count + 1):
        timestamp = start_time + (interval * i)
        output_file = os.path.join(screenshots_dir, f"screenshot_{i:02d}.jpg")

        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path,
             "-vframes", "1", "-q:v", "2", "-update", "1", output_file],
            capture_output=True, timeout=60
        )

        if os.path.exists(output_file):
            size_kb = os.path.getsize(output_file) / 1024
            time_str = format_duration(timestamp)
            print(f"    [{i}/{count}] {time_str} - {size_kb:.0f}KB")
            screenshot_files.append(output_file)

    # MediaInfo
    mediainfo_text = None
    mediainfo_path = CONFIG["mediainfo_path"]
    mediainfo_file = os.path.join(CONFIG["output_dir"], "mediainfo.txt")

    if os.path.exists(mediainfo_path):
        try:
            mi_out = subprocess.run(
                [mediainfo_path, video_path],
                capture_output=True, text=True, timeout=30
            )
            mediainfo_text = mi_out.stdout
            with open(mediainfo_file, "w", encoding="utf-8") as f:
                f.write(mediainfo_text)
            print_ok("MediaInfo sačuvan")
        except Exception as e:
            print_err(f"MediaInfo greška: {e}")
    else:
        print_info("MediaInfo CLI nije pronađen (preskočeno)")

    generated = len(screenshot_files)
    print_ok(f"Završeno! {generated} screenshot-ova sačuvano u: {screenshots_dir}")

    return screenshot_files, mediainfo_text


# ═══════════════════════════════════════════════════════════════════════════════
# 3. KREIRANJE TORRENTA
# ═══════════════════════════════════════════════════════════════════════════════

def create_torrent(path):
    print_header("KORAK 3: KREIRANJE TORRENTA")

    if not shutil.which("torrenttools"):
        print_err("torrenttools nije pronađen u PATH-u")
        print_info("Preuzmi sa: https://github.com/fbdtemme/torrenttools/releases")
        return None

    item_name = os.path.basename(os.path.normpath(path))
    output_file = os.path.join(CONFIG["output_dir"], f"{item_name}.torrent")

    if os.path.exists(output_file):
        os.remove(output_file)

    print_info(f"Kreiranje torrenta za: {item_name}")

    try:
        subprocess.run(
            ["torrenttools", "create", "--announce", CONFIG["announce_url"],
             "--private", "--output", output_file, path],
            timeout=600
        )
    except Exception as e:
        print_err(f"Greška pri kreiranju: {e}")
        return None

    if os.path.exists(output_file):
        size_kb = os.path.getsize(output_file) / 1024
        print_ok(f"Kreirano: {output_file} ({size_kb:.1f} KB)")
        return output_file
    else:
        print_err("Nije uspelo kreiranje torrenta")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. UPLOAD NA CRNA BERZA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_categories():
    """Preuzima dostupne kategorije sa sajta."""
    url = "https://www.crnaberza.com/wp-json/cb/v1/categories"
    req = urllib.request.Request(url)
    req.add_header("X-API-Key", CONFIG["cb_api_key"])
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print_err(f"Greška pri preuzimanju kategorija: {e}")
        return None


def upload_to_crnaberza(torrent_file, imdb_url, screenshot_files, mediainfo_text):
    print_header("KORAK 4: UPLOAD NA CRNA BERZA")

    if not CONFIG["cb_api_key"]:
        print_err("CB API ključ nije podešen u konfiguraciji!")
        print_info("Podesi 'cb_api_key' u CONFIG sekciji.")
        return False

    if not torrent_file or not os.path.exists(torrent_file):
        print_err("Torrent fajl ne postoji")
        return False

    # Preuzmi kategorije
    print_info("Preuzimanje kategorija...")
    categories = fetch_categories()
    if categories:
        print("\n  Dostupne kategorije:\n")
        if isinstance(categories, list):
            for cat in categories:
                cat_id = cat.get("id") or cat.get("term_id", "?")
                cat_name = cat.get("name", "?")
                print(f"    [{cat_id}] {cat_name}")
        elif isinstance(categories, dict):
            for cat_id, cat_name in categories.items():
                print(f"    [{cat_id}] {cat_name}")
        print()

    # Korisničk unos
    category = input("  Unesite ID kategorije: ").strip()
    name = input("  Unesite naziv torrenta: ").strip()

    description = ""
    if mediainfo_text:
        description = f"[code]{mediainfo_text}[/code]"
    custom_desc = input("  Dodatni opis (ili Enter za preskočiti): ").strip()
    if custom_desc:
        description = custom_desc + "\n\n" + description

    anonymous_input = input("  Anonimni upload? (d/n) [n]: ").strip().lower()
    anonymous = anonymous_input in ("d", "da", "y", "yes")

    # Priprema podataka
    data = {
        "torrent_file": file_to_base64(torrent_file),
        "url": imdb_url or "",
        "name": name,
        "description": description,
        "category": category,
        "anonymous": anonymous,
    }

    # Screenshots
    if screenshot_files:
        screenshots_b64 = []
        for sf in screenshot_files[:10]:
            if os.path.exists(sf):
                screenshots_b64.append(file_to_base64(sf))
        if screenshots_b64:
            data["screenshots"] = screenshots_b64
            print_info(f"Priloženo {len(screenshots_b64)} screenshot-ova")

    # NFO fajl (opciono)
    nfo_path = os.path.join(CONFIG["output_dir"], "info.nfo")
    if os.path.exists(nfo_path):
        data["nfo_file"] = file_to_base64(nfo_path)
        print_info("NFO fajl priložen")

    # Slanje
    print_info("Slanje na crnaberza.com...")

    json_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        "https://www.crnaberza.com/wp-json/cb/v1/upload",
        data=json_data,
        method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Key", CONFIG["cb_api_key"])

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print_ok("Upload uspešan!")
            print_ok(f"Odgovor: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print_err(f"HTTP greška {e.code}: {body}")
        return False
    except Exception as e:
        print_err(f"Greška pri uploadu: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# GLAVNI PROGRAM
# ═══════════════════════════════════════════════════════════════════════════════

def run_interactive():
    """Interaktivni mod - pokreće se kad se EXE pokrene duplim klikom."""
    print_header("CRNA BERZA - SVE U JEDNOM")
    print()
    print("  Dobrodošli! Ovaj program automatizuje upload na crnaberza.com")
    print()
    print("  ─────────────────────────────────────────────────────────────")
    print("  MENI:")
    print("  ─────────────────────────────────────────────────────────────")
    print("  [1] Pokreni sve (IMDB + screenshots + torrent + upload)")
    print("  [2] Samo IMDB pretraga")
    print("  [3] Samo screenshots & mediainfo")
    print("  [4] Samo kreiranje torrenta")
    print("  [5] Samo upload (koristi već pripremljene fajlove)")
    print("  [6] Podešavanja")
    print("  [0] Izlaz")
    print()

    choice = input("  Izaberite opciju: ").strip()

    if choice == "0":
        return

    if choice == "6":
        print()
        print(f"  Trenutna podešavanja:")
        print(f"    TMDB API ključ:  {CONFIG['tmdb_api_key']}")
        print(f"    CB API ključ:    {'***postavljeno***' if CONFIG['cb_api_key'] else '(nije postavljeno)'}")
        print(f"    MediaInfo:       {CONFIG['mediainfo_path']}")
        print(f"    Output folder:   {CONFIG['output_dir']}")
        print(f"    Announce URL:    {CONFIG['announce_url']}")
        print(f"    Screenshots:     {CONFIG['screenshot_count']}")
        print()
        new_tmdb = input(f"  TMDB API ključ [{CONFIG['tmdb_api_key']}]: ").strip()
        if new_tmdb:
            CONFIG["tmdb_api_key"] = new_tmdb
        new_cb = input(f"  CB API ključ [Enter za preskočiti]: ").strip()
        if new_cb:
            CONFIG["cb_api_key"] = new_cb
        new_mi = input(f"  MediaInfo putanja [{CONFIG['mediainfo_path']}]: ").strip()
        if new_mi:
            CONFIG["mediainfo_path"] = new_mi
        new_out = input(f"  Output folder [{CONFIG['output_dir']}]: ").strip()
        if new_out:
            CONFIG["output_dir"] = new_out
        new_ss = input(f"  Broj screenshot-ova [{CONFIG['screenshot_count']}]: ").strip()
        if new_ss:
            CONFIG["screenshot_count"] = int(new_ss)
        print_ok("Podešavanja ažurirana (važe do kraja sesije)")
        print()
        run_interactive()
        return

    # Za sve opcije osim podešavanja treba putanja
    print()
    path = input("  Unesite putanju do foldera ili video fajla: ").strip().strip('"')

    if not path:
        print_err("Putanja nije uneta")
        input("\n  Pritisnite Enter za izlaz...")
        return

    path = os.path.abspath(path)

    if not os.path.exists(path):
        print_err(f"Putanja ne postoji: {path}")
        input("\n  Pritisnite Enter za izlaz...")
        return

    os.makedirs(CONFIG["output_dir"], exist_ok=True)

    print_info(f"Putanja: {path}")
    print_info(f"Output:  {CONFIG['output_dir']}")

    if choice == "1":
        imdb_url = search_imdb(path)
        screenshot_files, mediainfo_text = generate_screenshots_and_mediainfo(path)
        torrent_file = create_torrent(path)
        print()
        do_upload = input("  Da li želite da uploadujete na Crna Berza? (d/n): ").strip().lower()
        if do_upload in ("d", "da", "y", "yes"):
            upload_to_crnaberza(torrent_file, imdb_url, screenshot_files or [], mediainfo_text)
        else:
            print_info("Upload preskočen.")
    elif choice == "2":
        search_imdb(path)
    elif choice == "3":
        generate_screenshots_and_mediainfo(path)
    elif choice == "4":
        create_torrent(path)
    elif choice == "5":
        torrent_files = list(Path(CONFIG["output_dir"]).glob("*.torrent"))
        torrent_file = str(torrent_files[0]) if torrent_files else None
        imdb_file = os.path.join(CONFIG["output_dir"], "imdb.txt")
        imdb_url = open(imdb_file).read().strip() if os.path.exists(imdb_file) else None
        ss_dir = os.path.join(CONFIG["output_dir"], "screenshots")
        screenshot_files = sorted(str(f) for f in Path(ss_dir).glob("*.jpg")) if os.path.isdir(ss_dir) else []
        mi_file = os.path.join(CONFIG["output_dir"], "mediainfo.txt")
        mediainfo_text = open(mi_file).read() if os.path.exists(mi_file) else None
        upload_to_crnaberza(torrent_file, imdb_url, screenshot_files, mediainfo_text)
    else:
        print_err("Nepoznata opcija")

    print_header("ZAVRŠENO")
    print_info(f"Svi fajlovi su u: {CONFIG['output_dir']}")
    input("\n  Pritisnite Enter za izlaz...")


def main():
    parser = argparse.ArgumentParser(
        description="Crna Berza - Sve u jednom: IMDB, screenshots, torrent, upload"
    )
    parser.add_argument("path", nargs="?", default=None, help="Putanja do foldera ili video fajla")
    parser.add_argument("--output-dir", help="Output direktorijum", default=None)
    parser.add_argument("--tmdb-key", help="TMDB API ključ", default=None)
    parser.add_argument("--cb-key", help="Crna Berza API ključ", default=None)
    parser.add_argument("--mediainfo", help="Putanja do MediaInfo.exe", default=None)
    parser.add_argument("--screenshots", type=int, help="Broj screenshot-ova", default=None)
    parser.add_argument(
        "--skip-upload", action="store_true",
        help="Preskoči upload (samo pripremi fajlove)"
    )
    parser.add_argument(
        "--only", choices=["imdb", "screenshots", "torrent", "upload"],
        help="Pokreni samo određeni korak"
    )

    args = parser.parse_args()

    # Primeni argumente na konfiguraciju
    if args.output_dir:
        CONFIG["output_dir"] = args.output_dir
    if args.tmdb_key:
        CONFIG["tmdb_api_key"] = args.tmdb_key
    if args.cb_key:
        CONFIG["cb_api_key"] = args.cb_key
    if args.mediainfo:
        CONFIG["mediainfo_path"] = args.mediainfo
    if args.screenshots:
        CONFIG["screenshot_count"] = args.screenshots

    # Ako nema putanje - interaktivni mod (dupli klik na EXE)
    if args.path is None:
        run_interactive()
        return

    path = os.path.abspath(args.path)

    if not os.path.exists(path):
        print_err(f"Putanja ne postoji: {path}")
        input("\n  Pritisnite Enter za izlaz...")
        sys.exit(1)

    os.makedirs(CONFIG["output_dir"], exist_ok=True)

    print_header("CRNA BERZA - SVE U JEDNOM")
    print_info(f"Putanja: {path}")
    print_info(f"Output:  {CONFIG['output_dir']}")

    # Ako je --only, pokreni samo taj korak
    if args.only == "imdb":
        search_imdb(path)
    elif args.only == "screenshots":
        generate_screenshots_and_mediainfo(path)
    elif args.only == "torrent":
        create_torrent(path)
    elif args.only == "upload":
        torrent_files = list(Path(CONFIG["output_dir"]).glob("*.torrent"))
        torrent_file = str(torrent_files[0]) if torrent_files else None
        imdb_file = os.path.join(CONFIG["output_dir"], "imdb.txt")
        imdb_url = open(imdb_file).read().strip() if os.path.exists(imdb_file) else None
        ss_dir = os.path.join(CONFIG["output_dir"], "screenshots")
        screenshot_files = sorted(str(f) for f in Path(ss_dir).glob("*.jpg")) if os.path.isdir(ss_dir) else []
        mi_file = os.path.join(CONFIG["output_dir"], "mediainfo.txt")
        mediainfo_text = open(mi_file).read() if os.path.exists(mi_file) else None
        upload_to_crnaberza(torrent_file, imdb_url, screenshot_files, mediainfo_text)
    else:
        # Puni workflow
        imdb_url = search_imdb(path)
        screenshot_files, mediainfo_text = generate_screenshots_and_mediainfo(path)
        torrent_file = create_torrent(path)

        if not args.skip_upload:
            print()
            do_upload = input("  Da li želite da uploadujete na Crna Berza? (d/n): ").strip().lower()
            if do_upload in ("d", "da", "y", "yes"):
                upload_to_crnaberza(torrent_file, imdb_url, screenshot_files or [], mediainfo_text)
            else:
                print_info("Upload preskočen.")
        else:
            print_info("Upload preskočen (--skip-upload).")

    print_header("ZAVRŠENO")
    print_info(f"Svi fajlovi su u: {CONFIG['output_dir']}")
    input("\n  Pritisnite Enter za izlaz...")


if __name__ == "__main__":
    main()

"""Rad sa video fajlovima, titlovima i slikama."""

import base64
import os
import re
from pathlib import Path

from .constants import VIDEO_EXTENSIONS


def find_video_file(path):
    p = Path(path)
    if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
        return str(p)
    videos = []
    for ext in VIDEO_EXTENSIONS:
        videos.extend(p.rglob(f"*{ext}"))
    return str(max(videos, key=lambda f: f.stat().st_size)) if videos else None


def detect_subtitles_from_mediainfo(mediainfo_text):
    langs = set()
    mi_lower = mediainfo_text.lower()
    if re.search(r"serbian|srpski|srp", mi_lower):
        langs.add("sr")
    if re.search(r"croatian|hrvatski|hrv", mi_lower):
        langs.add("hr")
    if re.search(r"bosnian|bosanski|bos", mi_lower):
        langs.add("ba")
    return sorted(langs)


def scan_srt_subtitles(path):
    langs = set()
    p = Path(path)
    search_dir = p if p.is_dir() else p.parent
    lang_patterns = {
        "sr": re.compile(r"[\._\-](sr|srp|serbian|srpski)[\._\-\s]", re.IGNORECASE),
        "hr": re.compile(r"[\._\-](hr|hrv|croatian|hrvatski)[\._\-\s]", re.IGNORECASE),
        "ba": re.compile(r"[\._\-](ba|bos|bosnian|bosanski)[\._\-\s]", re.IGNORECASE),
    }
    for srt in search_dir.rglob("*.srt"):
        padded = f".{srt.stem.lower()}."
        for lang_code, pattern in lang_patterns.items():
            if pattern.search(padded):
                langs.add(lang_code)
    return sorted(langs)


def format_duration(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def file_to_base64(filepath):
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

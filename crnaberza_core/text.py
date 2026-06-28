"""Tekstualne transformacije i prevod."""

import json
import re
import urllib.parse
import urllib.request

_CYR_TO_LAT = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž", "З": "Z", "И": "I",
    "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N", "Њ": "Nj", "О": "O", "П": "P", "Р": "R",
    "С": "S", "Т": "T", "Ћ": "Ć", "У": "U", "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž", "з": "z", "и": "i",
    "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "ћ": "ć", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}


def cyr_to_lat(text):
    return "".join(_CYR_TO_LAT.get(c, c) for c in text)


def google_translate(text):
    """Prevedi tekst na srpski preko besplatnog Google Translate API-ja."""
    if not text:
        return ""
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=sr&dt=t&q="
            + urllib.parse.quote(text)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = "".join(part[0] for part in data[0] if part[0])
            if result:
                return cyr_to_lat(result)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    return ""


def clean_folder_name(folder_name):
    clean = folder_name
    year = season = None
    clean = re.sub(
        r"\.(mkv|mp4|avi|m2ts|mov|wmv|ts|webm|flv|mpg|mpeg|srt|ass|ssa|sub|idx|vtt)$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    ym = re.search(r"(19|20)\d{2}", clean)
    if ym:
        year = ym.group(0)
    sm = re.search(r"S(\d{1,2})", clean, re.IGNORECASE)
    if sm:
        season = int(sm.group(1))
    clean = re.sub(r"[._\-]+", " ", clean)
    clean = re.sub(r"\s*(19|20)\d{2}.*$", "", clean)
    clean = re.sub(r"\s+S\d{1,2}(E\d{1,3})?.*$", "", clean, flags=re.IGNORECASE)
    clean = re.sub(
        r"\b(720p|1080p|2160p|4k|uhd|hdr|dv|hdr10|web[- ]?dl|web[- ]?rip|bluray|blu[- ]?ray|brrip|bdrip|"
        r"hdtv|dvdrip|hdcam|cam|ts|hdrip|x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts(-?hd)?|ddp?5\.1|"
        r"atmos|truehd|flac|mp3|remux|proper|repack|internal|extended|uncut|directors?|unrated|limited|"
        r"complete|multi|dual|sub|dubbed|subbed)\b.*$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"[\[\(\{].*?[\]\)\}]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean, year, season

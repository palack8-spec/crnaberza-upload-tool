"""TMDB API pomocne funkcije."""

import json
import urllib.request

from .text import cyr_to_lat, google_translate


def tmdb_request(endpoint, api_key):
    url = f"https://api.themoviedb.org/3/{endpoint}"
    sep = "&" if "?" in url else "?"
    url += f"{sep}api_key={api_key}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tmdb_get_local(search_type, tmdb_id, api_key, en_overview=""):
    genres = []
    for lang in ("sr-RS", "hr-HR", "bs-BS"):
        try:
            details = tmdb_request(f"{search_type}/{tmdb_id}?language={lang}", api_key)
            ov = details.get("overview", "")
            g = [cyr_to_lat(g.get("name", "")) for g in details.get("genres", []) if g.get("name")]
            if g:
                genres = g
            if ov:
                return cyr_to_lat(ov), genres
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, TypeError):
            continue
    if en_overview:
        translated = google_translate(en_overview)
        if translated:
            return translated, genres
    return en_overview, genres

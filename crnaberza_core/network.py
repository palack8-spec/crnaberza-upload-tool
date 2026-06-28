"""Mrezne pomocne funkcije."""

import urllib.request


def download_with_progress(url, dest_path, progress_callback=None):
    req = urllib.request.Request(url, headers={"User-Agent": "CrnaBerza/2.0"})
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

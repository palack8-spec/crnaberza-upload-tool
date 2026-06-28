"""Ucitavanje i cuvanje konfiguracije."""

import json
import os

from .constants import DEFAULT_CONFIG

DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CrnaBerza"
)
TOOLS_DIR = os.path.join(DATA_DIR, "tools")
CONFIG_FILE = os.path.join(DATA_DIR, "crnaberza_config.json")
HISTORY_FILE = os.path.join(DATA_DIR, "upload_history.json")


def _default_config():
    cfg = DEFAULT_CONFIG.copy()
    cfg["output_dir"] = os.path.join(os.path.expanduser("~"), "Videos", "Crna Berza")
    cfg["download_path"] = os.path.join(os.path.expanduser("~"), "Downloads", "torrents")
    return cfg


def load_config():
    base = _default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                base.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return base


def save_config(cfg):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

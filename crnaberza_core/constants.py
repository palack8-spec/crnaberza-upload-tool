"""Konstante aplikacije."""

APP_VERSION = "2.0"
GITHUB_REPO = "palack8-spec/crnaberza-upload-tool"

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".m2ts", ".wmv", ".mov")

CATEGORIES = {
    "Film_HD_Domace": 73,
    "Film_HD_Strano": 48,
    "Film_SD_Domace": 29,
    "Film_SD_Strano": 54,
    "TV_HD_Domace": 75,
    "TV_HD_Strano": 77,
    "TV_SD_Domace": 30,
    "TV_SD_Strano": 34,
}

DEFAULT_CONFIG = {
    "tmdb_api_key": "",
    "cb_api_key": "",
    "output_dir": "",
    "download_path": "",
    "announce_url": "http://xbt.crnaberza.com/announce",
    "screenshot_count": 10,
    "skip_start_percent": 5,
    "skip_end_percent": 5,
    "cleanup_after_upload": False,
    "cleanup_delete_screenshots": True,
    "cleanup_delete_mediainfo": True,
    "cleanup_delete_torrent": False,
    "cleanup_delete_nfo": True,
    "cleanup_delete_imdb": True,
    "theme": "dark",
    "sidebar_collapsed": False,
    "ftp_enabled": False,
    "ftp_protocol": "sftp",
    "ftp_host": "",
    "ftp_port": 22,
    "ftp_user": "",
    "ftp_pass": "",
    "ftp_remote_dir": "/watch",
    "auto_download_tools_ffmpeg": True,
    "auto_download_tools_mediainfo": True,
    "auto_download_tools_torrenttools": True,
    "auto_youtube_trailer": True,
}

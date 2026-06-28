"""Unit testovi za crnaberza_core."""

import os
import tempfile
import unittest

from crnaberza_core.text import clean_folder_name, cyr_to_lat
from crnaberza_core.torrent import _bdecode, _bencode, normalize_torrent, validate_torrent_file


class TestCleanFolderName(unittest.TestCase):
    def test_strips_quality_tags(self):
        name, year, season = clean_folder_name("Movie.Name.2020.1080p.BluRay.x264-GROUP")
        self.assertEqual(name, "Movie Name")
        self.assertEqual(year, "2020")
        self.assertIsNone(season)

    def test_detects_season(self):
        _, _, season = clean_folder_name("Show.S02E05.720p.WEB-DL")
        self.assertEqual(season, 2)


class TestCyrToLat(unittest.TestCase):
    def test_cyrillic(self):
        self.assertEqual(cyr_to_lat("Шаблон"), "Šablon")


class TestTorrent(unittest.TestCase):
    def _minimal_torrent_bytes(self):
        meta = {
            b"announce": b"http://example.com/announce",
            b"info": {
                b"name": b"test.txt",
                b"length": 4,
                b"piece length": 32768,
                b"pieces": b"a" * 20,
            },
        }
        return _bencode(meta)

    def test_validate_ok(self):
        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as f:
            f.write(self._minimal_torrent_bytes())
            path = f.name
        try:
            ok, msg = validate_torrent_file(path)
            self.assertTrue(ok, msg)
        finally:
            os.unlink(path)

    def test_roundtrip_bencode(self):
        raw = self._minimal_torrent_bytes()
        meta, _ = _bdecode(raw)
        self.assertIn(b"info", meta)

    def test_normalize_keeps_v1(self):
        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as f:
            f.write(self._minimal_torrent_bytes())
            path = f.name
        try:
            ok, msg = normalize_torrent(path)
            self.assertTrue(ok, msg)
            ok2, _ = validate_torrent_file(path)
            self.assertTrue(ok2)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

"""Validacija i normalizacija .torrent fajlova."""


def _bdecode(data):
    def parse(i):
        c = data[i : i + 1]
        if c == b"d":
            i += 1
            d = {}
            while data[i : i + 1] != b"e":
                key, i = parse(i)
                val, i = parse(i)
                d[key] = val
            return d, i + 1
        if c == b"l":
            i += 1
            lst = []
            while data[i : i + 1] != b"e":
                val, i = parse(i)
                lst.append(val)
            return lst, i + 1
        if c == b"i":
            end = data.index(b"e", i)
            return int(data[i + 1 : end]), end + 1
        if c.isdigit():
            colon = data.index(b":", i)
            length = int(data[i:colon])
            start = colon + 1
            return data[start : start + length], start + length
        raise ValueError(f"Nevalidan bencode token na poziciji {i}: {c!r}")

    return parse(0)


def _bencode(obj):
    out = bytearray()

    def enc(o):
        if isinstance(o, bool):
            raise ValueError("bool nije podrzan u bencode")
        if isinstance(o, int):
            out.extend(b"i")
            out.extend(str(o).encode("ascii"))
            out.extend(b"e")
        elif isinstance(o, bytes):
            out.extend(str(len(o)).encode("ascii"))
            out.extend(b":")
            out.extend(o)
        elif isinstance(o, str):
            b = o.encode("utf-8")
            out.extend(str(len(b)).encode("ascii"))
            out.extend(b":")
            out.extend(b)
        elif isinstance(o, list):
            out.extend(b"l")
            for item in o:
                enc(item)
            out.extend(b"e")
        elif isinstance(o, dict):
            out.extend(b"d")

            def keyb(k):
                return k if isinstance(k, bytes) else str(k).encode("utf-8")

            for k in sorted(o.keys(), key=keyb):
                enc(keyb(k))
                enc(o[k])
            out.extend(b"e")
        else:
            raise ValueError(f"Nepodrzan tip za bencode: {type(o)}")

    enc(obj)
    return bytes(out)


def validate_torrent_file(filepath):
    try:
        import os

        if not os.path.exists(filepath):
            return False, "Fajl ne postoji"
        size = os.path.getsize(filepath)
        if size == 0:
            return False, "Torrent fajl je prazan (0 bajtova)"
        with open(filepath, "rb") as f:
            raw = f.read()
        if not raw.startswith(b"d"):
            return False, "Ne pocinje sa 'd' - nije validan bencode dictionary"
        meta, _ = _bdecode(raw)
        if not isinstance(meta, dict):
            return False, "Korenski element nije dictionary"
        if b"info" not in meta:
            return False, "Nedostaje 'info' kljuc"
        info = meta[b"info"]
        if not isinstance(info, dict):
            return False, "'info' nije dictionary"
        if b"piece length" not in info:
            return False, "Nedostaje 'piece length' u info"
        if b"pieces" not in info:
            return False, "Nedostaje 'pieces' u info"
        if b"name" not in info:
            return False, "Nedostaje 'name' u info"
        if b"length" not in info and b"files" not in info:
            return False, "Nedostaje 'length' ili 'files' u info"
        pieces = info.get(b"pieces", b"")
        if isinstance(pieces, bytes) and len(pieces) % 20 != 0:
            return False, f"'pieces' duzina ({len(pieces)}) nije deljiva sa 20"
        return True, f"OK ({size} bajtova)"
    except ValueError as e:
        return False, f"Bencode greska: {e}"
    except OSError as e:
        return False, str(e)


def normalize_torrent(filepath, log_cb=None):
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        meta, _ = _bdecode(raw)
        if not isinstance(meta, dict) or b"info" not in meta:
            return False, "Nema info dict"
        info = meta[b"info"]
        if not isinstance(info, dict):
            return False, "info nije dict"

        had_v2 = False
        for k in (b"meta version", b"file tree"):
            if k in info:
                had_v2 = True
                del info[k]
        if b"piece layers" in meta:
            had_v2 = True
            del meta[b"piece layers"]

        if b"pieces" not in info or b"piece length" not in info:
            return False, (
                "Torrent je BitTorrent v2-only (nema v1 'pieces'). "
                "Sajt podrzava samo v1. Koristite mktorrent na serveru."
            )
        if b"name" not in info or (b"length" not in info and b"files" not in info):
            return False, "Nedostaju v1 polja (name/length/files) posle ciscenja v2"

        name = info.get(b"name", b"?")
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        files = info.get(b"files")
        nfiles = len(files) if isinstance(files, list) else 1
        plen = info.get(b"piece length", 0)
        npieces = len(info.get(b"pieces", b"")) // 20
        priv = info.get(b"private", 0)
        announce = meta.get(b"announce", b"")
        if isinstance(announce, bytes):
            announce = announce.decode("utf-8", "replace")
        if log_cb:
            log_cb(f"  Torrent: name='{name}', fajlova={nfiles}, piece={plen}, pieces={npieces}, private={priv}")
            log_cb(f"  Announce: {announce}")
            if had_v2:
                log_cb("  [FIX] Uklonjena BitTorrent v2/hybrid polja -> cist v1 torrent")

        canonical = _bencode(meta)
        _bdecode(canonical)
        with open(filepath, "wb") as f:
            f.write(canonical)
        changed = canonical != raw
        if had_v2:
            return True, "konvertovan u cist v1 (uklonjen v2/hybrid)"
        return True, ("normalizovan" if changed else "vec kanonski")
    except (OSError, ValueError) as e:
        return False, str(e)

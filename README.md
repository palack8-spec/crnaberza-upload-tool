# Crna Berza Tools v1.5 by Vucko

Desktop GUI program za automatski upload torrent fajlova na [CrnaBerza.com](https://www.crnaberza.com/) privatni tracker. Kompletno rjesenje — od IMDB pretrage do uploada, sa ugradjenim alatima za titlove, MKV editovanje, sinhronizaciju i vise.

---

## Download

Preuzmi `CrnaBerzaUploadTool.exe` iz [Releases](https://github.com/palack8-spec/crnaberza-upload-tool/releases/latest) sekcije. Samo pokreni — svi alati se automatski preuzimaju u `%LOCALAPPDATA%\CrnaBerza\tools`.

---

## Tabovi i funkcionalnosti

### Glavni (Main)

Centralni tab za upload pipeline.

- **Izbor foldera** — unesi putanju, koristi file browser ili drag-and-drop
- **Pipeline u 4 koraka:**
  1. **IMDB** — TMDB pretraga filma/serije, automatsko preuzimanje postera, opisa, zanrova, IMDB linka i kategorije
  2. **Screenshots** — generisanje screenshot-ova iz videa pomocu FFmpeg-a (podesiv broj, 1-20)
  3. **Torrent** — kreiranje `.torrent` fajla sa privatnim announce URL-om
  4. **Upload** — slanje na CrnaBerza sajt putem API-ja (torrent, opis, screenshots, mediainfo, NFO)
- **Quick Upload** (`Ctrl+Q`) — pokreni sva 4 koraka automatski
- **Batch Upload** (`Ctrl+B`) — dodaj vise foldera u red i obradi sve sekvencijalno
- **Statistika** — ukupan broj uploada, ukupna velicina, datum zadnjeg uploada
- **Konzola/Log** — filtriraj po tipu (Sve / Info / Greske), kopiraj u clipboard, obrisi
- **Progress bar** — prikazuje napredak trenutne operacije
- **Nastavak rada** — ako si vec obradio neke korake, program automatski detektuje i ucitava prethodne podatke (IMDB, screenshots, mediainfo, torrent)

### Red Cekanja (Queue)

- Dodaj foldere u red za sekvencijalnu obradu
- Pokreni sve, obrisi red, ukloni pojedinacne stavke
- Status indikatori po stavci (cekanje / u toku / zavrseno / greska)

### Istorija (History)

- Tabela svih prosli uploada: ID, ime, kategorija, velicina, datum, link na sajt, opis
- **Brisanje** pojedinacnih unosa
- **Export** kao JSON ili CSV
- Cuva zadnjih 200 unosa

### Alati (Tools)

Upravljanje spoljnim alatima koji su potrebni programu.

- **Tabela alata** sa statusom (pronadjen/nedostaje), putanjom, i per-tool auto-download prekidacem
- **Preuzmi pojedinacno** ili **Preuzmi sve** koji nedostaju
- **Ukloni/deinstaliraj** alat
- **Osvjezi** status svih alata
- **Otvori tools folder** u Explorer-u
- Svaki alat ima **On/Off prekidac** za automatsko preuzimanje pri pokretanju

#### Podrzani alati

| Alat | Verzija | Namjena |
|------|---------|---------|
| **FFmpeg** (+ FFprobe) | v7.1 | Generisanje screenshot-ova, ekstrakcija audio zapisa za sync titlova |
| **MediaInfo CLI** | v24.12 | Detaljna analiza video/audio/subtitle metapodataka |
| **torrenttools** | v0.6.2 | Kreiranje `.torrent` fajlova sa announce URL-om i private flagom |
| **MKVToolNix** (mkvmerge + mkvextract) | v98.0 | Dodavanje/uklanjanje/ekstrakcija titlova iz MKV fajlova |
| **alass** | v2.0.0 | Sinhronizacija titlova (reference-based, brz) |
| **ffsubsync** | pip | Sinhronizacija titlova (audio-based, preporucen) |
| **autosubsync** | pip | Sinhronizacija titlova (ML-based) |

Binarni alati se cuvaju u `%LOCALAPPDATA%\CrnaBerza\tools\<ime>\`, a Python alati u `tools\py\<ime>\`.

### MKV Titlovi (MKV Subtitle Editor)

Editor za subtitle trackove unutar MKV fajlova.

- **Listanje** svih subtitle trackova u MKV-u (ID, jezik, ime, kodek)
- **Dodavanje SRT titla** — izbor jezika (srpski, hrvatski, bosanski, engleski), opciono ime tracka
- **Auto-detekcija encoding-a** — UTF-8, cp1250, cp1251, iso-8859-2, iso-8859-16, latin-1 — automatski konvertuje u UTF-8
- **Uklanjanje** subtitle tracka po ID-u
- **Ekstrakcija** subtitle tracka u zasebni SRT fajl

### Sync Titlova (Subtitle Sync)

Sinhronizacija titlova sa video fajlom.

- Izbor **video fajla** (referenca) i **SRT fajla**
- Tri metode sinhronizacije:
  - **ffsubsync** — audio-based, preporucen za vecinu slucajeva
  - **alass** — reference-based, brzi
  - **autosubsync** — ML-based
- Podesiv sufiks izlaznog fajla (default: `_synced`)
- Prikaz statusa zavisnosti (koji alati nedostaju)

### Podesavanja (Settings)

Sva podesavanja programa.

#### API kljucevi
- **TMDB API kljuc** — [themoviedb.org](https://www.themoviedb.org/) → Profil → API
- **Crna Berza API kljuc** — potreban za upload na sajt

#### Folderi
- **Output folder** — gdje se cuvaju screenshots, mediainfo, torrent fajlovi (default: `~/Videos/Crna Berza`)
- **Watch folder** — folder koji torrent klijent prati za automatski seed (default: `~/Downloads/torrents`)

#### Tracker
- **Announce URL** — tracker announce URL (default: `http://xbt.crnaberza.com/announce`)

#### Screenshots
- **Broj screenshot-ova** — 1 do 20 (default: 10)

#### Ciscenje nakon uploada
- Master prekidac + pojedinacni prekidaci za:
  - Screenshots
  - mediainfo.txt
  - .torrent fajl
  - info.nfo
  - imdb.txt

#### FTP/SFTP Upload
- Automatski upload `.torrent` fajla na remote server nakon uploada
- **Protokol:** SFTP (preporucen, koristi paramiko) ili FTP
- **Podesavanja:** host, port, korisnicko ime, lozinka, remote direktorijum

#### Tema
- **Dark / Light** tema sa kompletnim CSS stilovima

---

## TMDB Integracija

- **Multi-pretraga** — pretrazuje film + TV + multi endpoint, automatski fallback bez godine ako nema rezultata
- **10 rezultata** sortirano po popularnosti
- **Rucna pretraga** — modal za unos custom upita
- **IMDB link** — automatski dohvata external IDs za IMDB link
- **Lokalizovani opis** — pokusava sr-RS → hr-HR → bs-BS, zatim Google Translate (EN→SR), zatim OpenRouter AI
- **Cirilica u Latinicu** — automatska transliteracija svih srpskih tekstova
- **Auto-kategorija** — na osnovu tipa (Film/TV) × kvaliteta (HD/SD) × porijekla (Domace/Strano) → 8 kategorija

---

## Upload Preview

Pre uploada prikazuje se detaljan pregled:

- Poster, kategorija (moze se mijenjati), zanrovi, IMDB link
- Zastavice za jezike titlova (auto-detekcija iz MediaInfo i SRT fajlova)
- MediaInfo pregled (General / Video / Audio / Subtitles)
- Thumbnail-ovi screenshot-ova
- Editor imena torrenta
- YouTube trailer input
- Anonimni upload checkbox
- Opcija za sync titlova prije uploada

---

## Auto-Update

- Pri pokretanju provjerava [GitHub Releases](https://github.com/palack8-spec/crnaberza-upload-tool/releases/latest)
- Poredi verziju sa najnovijim tagom
- Prikazuje modal sa linkom za preuzimanje ako postoji novija verzija

---

## Podrzani formati

**Video:** `.mkv`, `.mp4`, `.avi`, `.m2ts`, `.wmv`, `.mov`

**Titlovi:** `.srt`, `.ass`, `.ssa`, `.sub`, `.idx`, `.vtt`

---

## Ostale funkcionalnosti

- **BBCode opis** — automatski generise upload opis sa naslovom, pregledom, YouTube trailer embedom i BBCode preview rendererom
- **Windows notifikacije** — native toast notifikacija (Windows 10/11) kad se upload zavrsi
- **XBT tracker sync** — 60 sekundi cekanja nakon uploada da tracker registruje torrent prije download-a .torrent fajla
- **Precice na tastaturi:** `Ctrl+Q` (Quick Upload), `Ctrl+B` (Batch Upload), `Ctrl+1/2/3/4` (pipeline koraci)
- **HD/SD auto-detekcija** — iz MediaInfo sirine videa (≥1280px = HD)
- **Detekcija jezika titlova** — iz ugradjenih trackova i imena SRT fajlova (sr/hr/ba pattern)
- **Splash screen** — ekran za ucitavanje dok se program inicijalizuje
- **Svi podaci** se cuvaju u `%LOCALAPPDATA%\CrnaBerza\` (config, alati, istorija)

---

## Konfiguracija

Konfiguracioni fajl: `%LOCALAPPDATA%\CrnaBerza\crnaberza_config.json`

Sadrzi sve postavke programa ukljucujuci API kljuceve, putanje, FTP podesavanja, temu i per-tool auto-download prekidace.

---

## Build

```bash
pip install -r requirements.txt
pyinstaller crnaberza_gui.spec --noconfirm
```

EXE se generise u `dist/CrnaBerzaUploadTool.exe`.

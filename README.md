# Crna Berza Upload Tool V1 by Vucko

Automatski upload program za CrnaBerza — desktop GUI za kreiranje i upload torrent fajlova.


## Download

Samo pokreni exe — alati (FFmpeg, MediaInfo, torrenttools) se automatski preuzimaju u `%LOCALAPPDATA%\CrnaBerza\tools`.

## Mogucnosti

- **IMDB/TMDB pretraga** — automatsko preuzimanje postera, opisa i kategorije
- **Screenshots** — generisanje screenshot-ova iz videa (FFmpeg)
- **MediaInfo** — automatska analiza video fajla
- **Torrent kreiranje** — `.torrent` generisanje sa privatnim trackerom
- **Upload** — direktan upload na CrnaBerza sajt putem API-ja
- **Auto-download alata** — FFmpeg, MediaInfo i torrenttools se automatski preuzimaju i azuriraju pri pokretanju
- **Moderan UI** — dark tema sa pipeline stepper navigacijom


## Podesavanja

Pri prvom pokretanju podesi:

1. **TMDB API kljuc** — [themoviedb.org](https://www.themoviedb.org/) → Profil → API
2. **Crna Berza API kljuc** — Nalog → API → Generisi novi kljuc
3. **Output folder** — gde se cuvaju screenshots, mediainfo, torrent fajlovi
4. **Watch folder** — folder koji torrent klijent prati za automatski seed
5. **Announce URL** — tracker announce URL

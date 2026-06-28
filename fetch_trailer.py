import sys, re, json, urllib.parse, urllib.request

def get_title(imdb_id):
    url = f"https://v3.sg.media-imdb.com/suggestion/t/{imdb_id}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    for item in data.get("d", []):
        if item.get("id") == imdb_id:
            return item.get("l"), str(item.get("y", ""))
    return None, None

def search_youtube(query, original_title):
    req = urllib.request.Request(
        f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=10) as r:
        page = r.read().decode("utf-8", errors="replace")
    
    match = re.search(r'var ytInitialData = ({.*?});</script>', page)
    if match:
        try:
            data = json.loads(match.group(1))
            def find_videos(obj):
                videos = []
                if isinstance(obj, dict):
                    if 'videoId' in obj and 'title' in obj and 'runs' in obj['title']:
                        title = "".join(run.get("text", "") for run in obj['title']['runs'])
                        videos.append((obj['videoId'], title))
                    for k, v in obj.items():
                        videos.extend(find_videos(v))
                elif isinstance(obj, list):
                    for item in obj:
                        videos.extend(find_videos(item))
                return videos
            
            title_words = [w.lower() for w in original_title.split() if len(w) > 2]
            
            for vid, title in find_videos(data):
                t_low = title.lower()
                if "trailer" in t_low or "teaser" in t_low:
                    is_valid = False
                    if title_words:
                        if all(w in t_low for w in title_words):
                            is_valid = True
                    else:
                        if original_title.lower() in t_low:
                            is_valid = True
                            
                    if is_valid:
                        return f"https://www.youtube.com/watch?v={vid}"
        except:
            pass
    return None
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--imdb-id"]
    if not args:
        sys.exit(1)
    title, year = get_title(args[0])
    if not title:
        sys.exit(1)
    url = search_youtube(f"{title} {year} official trailer", title)
    if url:
        print(url)
        try:
            import subprocess
            subprocess.Popen(['clip'], stdin=subprocess.PIPE, shell=True, creationflags=0x08000000).communicate(url.encode())
        except: pass
    else:
        sys.exit(1)

#!/usr/bin/env python3
"""Find photos and video of people, products and events, download them, and keep the credits.

  find_media.py search <work> "<query>" [--kind image|video] [--source commons,openverse,web,youtube,archive,pexels] [--licensed-only] [--limit 6]
  find_media.py fetch  <work> <result-id> --name <stem> [--section <from>-<to>]
  find_media.py fetch  <work> --url <url> --name <stem> [--kind image|video] [--license "<licence>" --author "<who>"] [--section <from>-<to>]
  find_media.py credits <work>

Licensed sources (Commons, Openverse, Internet Archive, Pexels) are searched alongside the open web
(Bing images) and YouTube (via yt-dlp). Web and YouTube results carry no licence; they are marked ⚠ and
flagged in credits.json so the report can name them.

Search results are numbered m1, m2, … across the whole edit and kept in <work>/media/index.json.
Images land in <work>/assets/, video sections in <work>/clips/src/ with a preview sheet beside them.
Every download is appended to <work>/credits.json, which the final report and the video description use.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "voiceover-video-skill/1.0 (https://github.com/Dancan254/voiceover-video-skill)"
BROWSER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
SOURCES = {"image": ["commons", "openverse", "web", "pexels"], "video": ["commons", "youtube", "archive", "pexels"]}
LICENSED_SOURCES = {"commons", "openverse", "archive", "pexels"}
MAX_SECTION = 120
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv", ".ogv", ".m4v")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/avif": ".avif", "image/gif": ".gif"}
# Stock-photo previews are watermarked, and the clean file is paid; they never make a usable shot
STOCK_HOSTS = ("alamy.", "gettyimages.", "shutterstock.", "istockphoto.", "dreamstime.", "depositphotos.",
               "123rf.", "stock.adobe.", "vecteezy.", "freepik.")


def get_json(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def plain(text):
    text = html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()
    # Commons wraps some names in a visible label plus a hidden copy, which strips to "NameName"
    half = len(text) // 2
    return text[:half] if len(text) % 2 == 0 and text[:half] == text[half:] else text


def cc_name(code, version):
    code = (code or "").lower()
    if code == "cc0":
        return "CC0"
    if code == "pdm":
        return "Public Domain Mark"
    return f"CC {code.upper()} {version}".strip() if code else "unknown"


def is_non_commercial(licence):
    return bool(re.search(r"\bNC\b|non-?commercial", licence, re.IGNORECASE))


def search_commons(query, kind, limit):
    filetype = "bitmap" if kind == "image" else "video"
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrlimit": str(limit), "gsrsearch": f"{query} filetype:{filetype}",
        "prop": "imageinfo" if kind == "image" else "videoinfo",
    }
    info_prefix = "ii" if kind == "image" else "vi"
    params[f"{info_prefix}prop"] = "url|size|mime|extmetadata" + ("" if kind == "image" else "|derivatives")
    params[f"{info_prefix}extmetadatafilter"] = "LicenseShortName|Artist|ImageDescription"
    if kind == "image":
        params["iiurlwidth"] = "2000"
    data = get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda page: page.get("index", 0))
    results = []
    for page in pages:
        info = (page.get("imageinfo") or page.get("videoinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        file_url = info.get("thumburl") or info.get("url")
        if kind == "video":
            # A derivative near 1080p is plenty for a frame, and far smaller than a 4K original
            webms = [d for d in info.get("derivatives", []) if "webm" in d.get("type", "") and d.get("width", 0) <= 1920]
            if webms:
                file_url = max(webms, key=lambda d: d["width"])["src"]
        results.append({
            "source": "commons", "kind": kind, "title": page["title"].removeprefix("File:"),
            "author": plain(meta.get("Artist", {}).get("value")) or "unknown",
            "license": meta.get("LicenseShortName", {}).get("value", "unknown"),
            "page_url": info.get("descriptionurl"), "file_url": file_url,
            "width": info.get("width"), "height": info.get("height"), "duration": info.get("duration"),
            "about": plain(meta.get("ImageDescription", {}).get("value"))[:140],
        })
    return results


def search_openverse(query, kind, limit):
    if kind != "image":
        return []
    params = {"q": query, "page_size": str(limit), "license_type": "commercial"}
    data = get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params))
    return [{
        "source": "openverse", "kind": "image", "title": r.get("title") or "untitled",
        "author": r.get("creator") or "unknown", "license": cc_name(r.get("license"), r.get("license_version")),
        "page_url": r.get("foreign_landing_url"), "file_url": r.get("url"),
        "width": r.get("width"), "height": r.get("height"), "duration": None, "about": r.get("provider") or "",
    } for r in data.get("results", [])]


def search_archive(query, kind, limit):
    if kind != "video":
        return []
    # Most Archive uploads carry no licence at all; only items that declare one are usable
    params = [("q", f"({query}) AND mediatype:movies AND licenseurl:*"), ("rows", str(limit)), ("output", "json")]
    params += [("fl[]", field) for field in ("identifier", "title", "creator", "licenseurl")]
    data = get_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params))
    results = []
    for doc in data.get("response", {}).get("docs", []):
        licence_url = doc.get("licenseurl", "")
        match = re.search(r"licenses/([a-z-]+)/([\d.]+)", licence_url)
        licence = cc_name(match.group(1), match.group(2)) if match else ("CC0" if "zero" in licence_url else licence_url)
        creator = doc.get("creator")
        results.append({
            "source": "archive", "kind": "video", "title": doc.get("title") or doc["identifier"],
            "author": ", ".join(creator) if isinstance(creator, list) else (creator or "unknown"),
            "license": licence, "page_url": f"https://archive.org/details/{doc['identifier']}",
            "file_url": None, "identifier": doc["identifier"],
            "width": None, "height": None, "duration": None, "about": "",
        })
    return results


def search_pexels(query, kind, limit):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    endpoint = "https://api.pexels.com/v1/search?" if kind == "image" else "https://api.pexels.com/videos/search?"
    data = get_json(endpoint + urllib.parse.urlencode({"query": query, "per_page": str(limit)}),
                    headers={"Authorization": key})
    results = []
    for r in data.get("photos" if kind == "image" else "videos", []):
        if kind == "image":
            file_url, author, duration = r["src"]["large2x"], r.get("photographer"), None
        else:
            files = [f for f in r.get("video_files", []) if f.get("width") and max(f["width"], f["height"]) <= 1920]
            file_url = max(files, key=lambda f: f["width"])["link"] if files else None
            author, duration = r.get("user", {}).get("name"), r.get("duration")
        results.append({
            "source": "pexels", "kind": kind, "title": r.get("alt") or r.get("url", "").rstrip("/").split("/")[-1],
            "author": author or "unknown", "license": "Pexels License", "page_url": r.get("url"),
            "file_url": file_url, "width": r.get("width"), "height": r.get("height"),
            "duration": duration, "about": "stock",
        })
    return results


def search_web(query, kind, limit):
    if kind != "image":
        return []
    params = {"q": query, "first": "0", "count": str(limit * 3), "qft": "+filterui:imagesize-large", "adlt": "moderate"}
    request = urllib.request.Request("https://www.bing.com/images/async?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": BROWSER_AGENT, "Accept-Language": "en-US"})
    with urllib.request.urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")
    results = []
    for raw in re.findall(r'\bm="([^"]+)"', page):
        try:
            item = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        image_url, page_url = item.get("murl"), item.get("purl") or ""
        if not image_url or any(host in image_url + page_url for host in STOCK_HOSTS):
            continue
        results.append({
            "source": "web", "kind": "image", "title": plain(item.get("t")) or "untitled",
            "author": urllib.parse.urlparse(page_url).netloc.removeprefix("www.") or "unknown",
            "license": "unknown (web image)", "page_url": page_url, "file_url": image_url,
            "width": None, "height": None, "duration": None, "about": "",
        })
    return results[:limit]


def search_youtube(query, kind, limit):
    if kind != "video":
        return []
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is not installed (pipx install yt-dlp)")
    listing = subprocess.run(["yt-dlp", "--flat-playlist", "--no-warnings", "-J", f"ytsearch{limit}:{query}"],
                             capture_output=True, text=True, check=True, timeout=60)
    return [{
        "source": "youtube", "kind": "video", "title": entry.get("title") or entry["id"],
        "author": entry.get("channel") or entry.get("uploader") or "unknown",
        "license": "YouTube (rights reserved unless the channel says otherwise)",
        "page_url": f"https://www.youtube.com/watch?v={entry['id']}",
        "file_url": f"https://www.youtube.com/watch?v={entry['id']}",
        "width": None, "height": None, "duration": entry.get("duration"), "about": "",
    } for entry in json.loads(listing.stdout).get("entries", []) if entry.get("id")]


SEARCHERS = {"commons": search_commons, "openverse": search_openverse, "web": search_web,
             "youtube": search_youtube, "archive": search_archive, "pexels": search_pexels}


def load_index(work):
    path = work / "media" / "index.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"next": 1, "results": {}}


def save_index(work, index):
    (work / "media").mkdir(parents=True, exist_ok=True)
    (work / "media" / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def describe(result_id, r):
    size = f"{r['width']}x{r['height']}" if r.get("width") else "?"
    length = f" {int(r['duration']) // 60}:{int(r['duration']) % 60:02d}" if r.get("duration") else ""
    about = f" — {r['about']}" if r.get("about") else ""
    mark = "⚠ " if r["source"] not in LICENSED_SOURCES else ""
    return f"{result_id:<5} {r['source']:<9} {r['kind']}{length} {size} · {mark}{r['license']} · {r['title']} · by {r['author'][:40]}{about}"


def search(args):
    kinds_sources = args.source.split(",") if args.source else SOURCES[args.kind]
    if args.licensed_only:
        kinds_sources = [s for s in kinds_sources if s in LICENSED_SOURCES]
    unknown = [s for s in kinds_sources if s not in SEARCHERS]
    if unknown:
        print(f"Unknown source: {', '.join(unknown)}", file=sys.stderr)
        print(f"Next: use any of {', '.join(SEARCHERS)}", file=sys.stderr)
        return 1
    index = load_index(args.work)
    found, seen = [], set()
    for source in kinds_sources:
        if source == "pexels" and not os.environ.get("PEXELS_API_KEY"):
            if args.source:
                print("pexels skipped: PEXELS_API_KEY is not set (free key at https://www.pexels.com/api/)", file=sys.stderr)
            continue
        try:
            results = SEARCHERS[source](args.query, args.kind, args.limit)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError,
                subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"{source} search failed: {e}", file=sys.stderr)
            continue
        for r in results:
            if args.licensed_only and is_non_commercial(r["license"]):
                continue
            # Openverse indexes Commons too; the same file under two ids only adds noise
            key = re.sub(r"\.\w{3,4}$", "", r["title"]).strip().lower()
            if key not in seen:
                seen.add(key)
                found.append(r)
    for r in found:
        result_id = f"m{index['next']}"
        index["next"] += 1
        index["results"][result_id] = {**r, "query": args.query}
        print(describe(result_id, r))
    save_index(args.work, index)
    print(f"{len(found)} result(s) for \"{args.query}\" ({args.kind}) → {args.work / 'media' / 'index.json'}")
    if not found:
        print("Next: try a broader query (the person's name alone, or name + event), or the other --kind")
        return 1
    print("Next: fetch the ones that fit with: find_media.py fetch <work> <id> --name <stem>" +
          (" --section <from>-<to>" if args.kind == "video" else ""))
    return 0


def parse_section(text, cap):
    if not text:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", text)
    if not match:
        raise ValueError(f"--section must look like 125.5-140, got {text}")
    start, end = float(match.group(1)), float(match.group(2))
    if end <= start:
        raise ValueError(f"--section {text} is empty")
    if end - start > cap:
        raise ValueError(f"--section {text} is {end - start:.0f}s; the limit here is {cap}s")
    return start, end


def archive_file_url(identifier):
    meta = get_json(f"https://archive.org/metadata/{urllib.parse.quote(identifier)}")
    videos = [f for f in meta.get("files", []) if f.get("name", "").lower().endswith(VIDEO_EXTENSIONS)]
    if not videos:
        return None
    # Prefer the h.264 derivative the Archive makes for every upload; it decodes everywhere
    best = sorted(videos, key=lambda f: (f.get("format") != "h.264", -int(f.get("width") or 0)))[0]
    return f"https://archive.org/download/{urllib.parse.quote(identifier)}/{urllib.parse.quote(best['name'])}"


def download_image(url, stem, referer):
    # Web hosts refuse hotlinks from non-browser clients; Commons asks for an identifying agent instead
    agent = USER_AGENT if "wikimedia.org" in url else BROWSER_AGENT
    headers = {"User-Agent": agent, **({"Referer": referer} if referer else {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        content_type = response.headers.get_content_type()
        if content_type not in IMAGE_TYPES:
            raise RuntimeError(f"{url} served {content_type}, not an image")
        target = stem.with_suffix(IMAGE_TYPES[content_type])
        with open(target, "wb") as out:
            shutil.copyfileobj(response, out)
    return target


def fetch_video_section(url, target, section):
    start, end = section
    agent = ["-user_agent", USER_AGENT] if url.startswith("http") else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", *agent, "-ss", f"{start}", "-i", url,
                    "-t", f"{end - start}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(target)], check=True)


def fetch_with_ytdlp(url, target, section, duration):
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is not installed (pipx install yt-dlp); it fetches YouTube and other page URLs")
    # YouTube refuses byte-range seeks from plain clients, so a section cut stalls on long videos; download
    # the whole video once through yt-dlp's chunked downloader and cut sections from the local copy
    cache = target.parent / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    full = cache / (re.sub(r"[^A-Za-z0-9_-]+", "_", url)[-90:] + ".mp4")
    if not full.is_file():
        height = 1080 if duration and duration <= 900 else 720
        length = f"{int(duration) // 60} min" if duration else "unknown length"
        print(f"downloading the full video once ({length}, ≤{height}p); later sections reuse it", flush=True)
        command = ["yt-dlp", "--quiet", "--no-warnings", "--no-playlist",
                   "-f", f"bv*[height<={height}]+ba/b[height<={height}]/b", "--merge-output-format", "mp4",
                   "-o", str(full), url]
        # YouTube's download challenge needs a JS runtime and yt-dlp's official solver script
        if not shutil.which("deno") and shutil.which("node"):
            command[1:1] = ["--js-runtimes", "node", "--remote-components", "ejs:github"]
        subprocess.run(command, check=True)
    fetch_video_section(str(full), target, section)


def preview_sheet(clip, sheet):
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(clip)], capture_output=True, text=True, check=True).stdout.strip())
    rate = 8 / max(duration, 0.1)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
                    f"fps={rate},scale=320:-2,tile=4x2:padding=4", "-frames:v", "1", str(sheet)], check=True)
    return duration


def append_credit(work, credit):
    path = work / "credits.json"
    credits = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    credits = [c for c in credits if c["file"] != credit["file"]] + [credit]
    path.write_text(json.dumps(credits, indent=2), encoding="utf-8")


def fetch(args):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.name):
        print(f"--name must be lowercase letters, digits and dashes, got {args.name}", file=sys.stderr)
        print("Next: e.g. --name torvalds-keynote", file=sys.stderr)
        return 1

    if args.result:
        record = load_index(args.work)["results"].get(args.result)
        if record is None:
            print(f"No search result {args.result} in {args.work / 'media' / 'index.json'}", file=sys.stderr)
            print("Next: run find_media.py search first and use an id it printed", file=sys.stderr)
            return 1
        unlicensed = record["source"] not in LICENSED_SOURCES
    elif args.url:
        unlicensed = not args.license
        # A page URL (YouTube, X, Vimeo…) is a video yt-dlp can resolve; a bare file URL says what it is
        kind = args.kind or ("image" if urllib.parse.urlparse(args.url).path.lower().endswith(IMAGE_EXTENSIONS) else "video")
        record = {
            "source": "url", "kind": kind, "title": args.url,
            "author": args.author or urllib.parse.urlparse(args.url).netloc.removeprefix("www."),
            "page_url": args.url, "file_url": args.url, "license": args.license or "unknown (supplied URL)",
        }
    else:
        print("fetch needs a result id or --url", file=sys.stderr)
        print("Next: find_media.py fetch <work> m3 --name <stem>", file=sys.stderr)
        return 1

    try:
        if record["kind"] == "image":
            (args.work / "assets").mkdir(parents=True, exist_ok=True)
            target = download_image(record["file_url"], args.work / "assets" / args.name, record.get("page_url"))
            detail = f"{target.stat().st_size // 1024} KB"
        else:
            section = parse_section(args.section, MAX_SECTION)
            if section is None:
                print("A video fetch needs --section <from>-<to> in the source's seconds", file=sys.stderr)
                print("Next: pick the moment from the preview or the source page; a 30–60s window is fine to transcribe", file=sys.stderr)
                return 1
            source_url = record.get("file_url") or archive_file_url(record["identifier"])
            if source_url is None:
                print(f"{record['page_url']} has no downloadable video file", file=sys.stderr)
                print("Next: fetch a different result", file=sys.stderr)
                return 1
            target = args.work / "clips" / "src" / f"{args.name}.mp4"
            target.parent.mkdir(parents=True, exist_ok=True)
            is_page = record["source"] in ("youtube", "url") and not urllib.parse.urlparse(source_url).path.lower().endswith(VIDEO_EXTENSIONS)
            if is_page:
                fetch_with_ytdlp(source_url, target, section, record.get("duration"))
            else:
                fetch_video_section(source_url, target, section)
            sheet = target.with_suffix(".jpg")
            duration = preview_sheet(target, sheet)
            detail = f"{duration:.1f}s from {section[0]}–{section[1]}s · preview {sheet}"
            record = {**record, "section": list(section)}
    except (urllib.error.URLError, TimeoutError, OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        print("Next: check the URL or section, or fetch a different result", file=sys.stderr)
        return 1

    append_credit(args.work, {
        "file": str(target.relative_to(args.work)), "title": record["title"], "author": record["author"],
        "license": record["license"], "source": record["page_url"], "section": record.get("section"),
        "unlicensed": unlicensed,
    })
    print(f"{target} · {detail} · {record['license']}")
    if unlicensed:
        print("⚠ no licence: credit the source in the description; the report must name it")
    if record["kind"] == "image":
        print("Next: look at the file before placing it; search results can be the wrong person or thing")
    else:
        print("Next: look at the preview sheet, then cut it into the edit with extract_clip.sh")
    return 0


def credits(args):
    path = args.work / "credits.json"
    if not path.is_file():
        print(f"No credits in {path}", file=sys.stderr)
        print("Next: nothing was fetched with find_media.py; list hand-sourced credits yourself", file=sys.stderr)
        return 1
    entries = json.loads(path.read_text(encoding="utf-8"))
    # Two sections of one talk are one credit
    entries = list({c["source"]: c for c in entries}.values())
    for c in entries:
        flag = "  ⚠ unlicensed" if c.get("unlicensed") else ""
        print(f"{c['title']} — {c['author']} — {c['license']} — {c['source']}{flag}")
    print(f"{len(entries)} credit(s) · paste the lines above into the video description")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    search_parser = commands.add_parser("search")
    search_parser.add_argument("work", type=Path)
    search_parser.add_argument("query")
    search_parser.add_argument("--kind", choices=SOURCES, default="image")
    search_parser.add_argument("--source", default=None, help="comma-separated: " + ",".join(SEARCHERS))
    search_parser.add_argument("--licensed-only", action="store_true", help="skip web and YouTube, and non-commercial licences")
    search_parser.add_argument("--limit", type=int, default=6)

    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("work", type=Path)
    fetch_parser.add_argument("result", nargs="?", default=None)
    fetch_parser.add_argument("--name", required=True)
    fetch_parser.add_argument("--section", default=None)
    fetch_parser.add_argument("--url", default=None)
    fetch_parser.add_argument("--license", default=None)
    fetch_parser.add_argument("--author", default=None)
    fetch_parser.add_argument("--kind", choices=SOURCES, default=None, help="for --url: override the image/video guess")

    credits_parser = commands.add_parser("credits")
    credits_parser.add_argument("work", type=Path)

    args = parser.parse_args()
    return {"search": search, "fetch": fetch, "credits": credits}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

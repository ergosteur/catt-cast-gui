#!/usr/bin/env python3
"""
piped_best_url.py — get the best *direct* (progressive) stream URL from a Piped instance.
Falls back to HLS (m3u8) or DASH (mpd) if a progressive stream doesn't exist.

Usage:
  ./piped_best_url.py <youtube-url-or-id>
  ./piped_best_url.py --base https://api.piped.example.com <id>
  ./piped_best_url.py --prefer-container mp4 --prefer-codecs h264,av1 <id>

Exit codes:
  0  success (printed a URL)
  1  bad args / network error
  2  no suitable URL found

Notes:
- Prefers progressive (video+audio) direct URLs first.
- If none exist, falls back to HLS (m3u8), then DASH (mpd).
- You can steer selection with --prefer-container and --prefer-codecs.
"""

import sys
import json
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple

PIPED_INSTANCE = "pipedapi.kavin.rocks" # Change to your Piped instance api domain

DEFAULT_BASE = f"https://{PIPED_INSTANCE}"


def extract_video_id(arg: str) -> Optional[str]:
    """Extract YT video ID from full URL or return arg if it looks like an ID."""
    if len(arg) == 11 and all(c.isalnum() or c in "-_" for c in arg):
        return arg
    try:
        u = urllib.parse.urlparse(arg)
        if u.netloc:
            if u.netloc.endswith("youtu.be"):
                vid = u.path.lstrip("/").split("/")[0]
                return vid or None
            if "youtube.com" in u.netloc or "youtube-nocookie.com" in u.netloc or PIPED_INSTANCE in u.netloc:
                qs = urllib.parse.parse_qs(u.query)
                if "v" in qs and qs["v"]:
                    return qs["v"][0]
                parts = [p for p in u.path.split("/") if p]
                if len(parts) >= 2 and parts[0] == "shorts":
                    return parts[1]
    except Exception:
        pass
    return None

def get_streams_json(base_url: str, video_id: str, timeout: int = 15) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/streams/{urllib.parse.quote(video_id)}"
    req = urllib.request.Request(url, headers={"User-Agent": "piped-best-url/1.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8", "replace"))

def ext_from_url(u: str) -> str:
    try:
        path = urllib.parse.urlparse(u).path
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        # m3u8, mpd, mp4, webm, etc.
        return ext
    except Exception:
        return ""

def norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def score_progressive(
    s: Dict[str, Any],
    prefer_container: List[str],
    prefer_codecs: List[str],
) -> Tuple[int, int, int, int]:
    """
    Return a sortable score tuple (bigger is better) for a progressive stream.
    Order:
      1) container preference (earlier in prefer_container = higher)
      2) codec preference     (earlier in prefer_codecs   = higher)
      3) resolution height
      4) bitrate
    """
    container = norm(s.get("container") or s.get("format") or ext_from_url(s.get("url") or ""))
    codec = norm(s.get("codec") or s.get("codecs"))
    height = int(s.get("height") or 0)
    bitrate = int(s.get("bitrate") or 0)

    # Higher is better, so invert the index (earlier = bigger)
    def pref_score(val: str, pref_list: List[str]) -> int:
        val = norm(val)
        # match by exact token; for codec, allow prefix match like "av1", "vp9", "h264"
        for i, p in enumerate(pref_list):
            p = norm(p)
            if not p:
                continue
            if pref_list is prefer_codecs:
                if val.startswith(p):
                    return len(pref_list) - i
            else:
                if val == p:
                    return len(pref_list) - i
        return 0

    return (
        pref_score(container, prefer_container),
        pref_score(codec, prefer_codecs),
        height,
        bitrate,
    )

def pick_best_progressive(
    data: Dict[str, Any],
    prefer_container: List[str],
    prefer_codecs: List[str],
) -> Optional[str]:
    """
    Find the best progressive (video+audio) direct URL in videoStreams.
    Progressive = entries with videoOnly == False and a usable URL.
    """
    streams = data.get("videoStreams") or []
    candidates = []
    for s in streams:
        if s.get("url") and not s.get("videoOnly"):
            candidates.append((score_progressive(s, prefer_container, prefer_codecs), s["url"]))

    if not candidates:
        return None

    # Sort by score descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def get_best_piped_url(
    video_url_or_id: str,
    base_url: str,
    prefer_container: Optional[List[str]] = None,
    prefer_codecs: Optional[List[str]] = None,
    timeout: int = 15,
) -> str:
    """
    Given a YT URL/ID and a Piped API base, returns the best direct stream URL.
    Falls back to HLS/DASH if no progressive stream is found.
    Raises ValueError on failure.
    """
    if prefer_container is None:
        prefer_container = ["mp4", "webm"]
    if prefer_codecs is None:
        prefer_codecs = ["h264", "av1", "vp9"]

    vid = extract_video_id(video_url_or_id)
    if not vid:
        raise ValueError(f"Could not extract video ID from: {video_url_or_id}")

    data = get_streams_json(base_url, vid, timeout=timeout)

    best_direct = pick_best_progressive(data, prefer_container, prefer_codecs)
    if best_direct:
        return best_direct

    if hls := data.get("hls"): return hls
    if dash := data.get("dash"): return dash

    raise ValueError("No suitable stream URL found (no progressive/HLS/DASH available).")

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 1

    base = DEFAULT_BASE
    prefer_container = ["mp4", "webm"]  # default: prioritize compatibility
    prefer_codecs = ["h264", "av1", "vp9"]  # default: broadly compatible first

    args = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--base":
            if i + 1 >= len(argv):
                print("error: --base requires a URL", file=sys.stderr)
                return 1
            base = argv[i + 1]
            i += 2
        elif a == "--prefer-container":
            if i + 1 >= len(argv):
                print("error: --prefer-container requires a comma-separated list", file=sys.stderr)
                return 1
            prefer_container = [x.strip().lower() for x in argv[i + 1].split(",") if x.strip()]
            i += 2
        elif a == "--prefer-codecs":
            if i + 1 >= len(argv):
                print("error: --prefer-codecs requires a comma-separated list", file=sys.stderr)
                return 1
            prefer_codecs = [x.strip().lower() for x in argv[i + 1].split(",") if x.strip()]
            i += 2
        else:
            args.append(a)
            i += 1

    if not args:
        print("error: missing video URL or ID\n\n" + __doc__.strip(), file=sys.stderr)
        return 1

    video_url_or_id = args[0]

    try:
        best_url = get_best_piped_url(video_url_or_id, base, prefer_container, prefer_codecs)
        print(best_url)
        ext = ext_from_url(best_url)
        if ext == "m3u8":
            print("note: no progressive stream; returned HLS (m3u8).", file=sys.stderr)
        elif ext == "mpd":
            print("note: no progressive stream; returned DASH (mpd).", file=sys.stderr)
        return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: request failed: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

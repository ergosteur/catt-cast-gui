#!/usr/bin/env python3
import argparse, os, shutil, socket, subprocess, sys, tempfile, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

class H( SimpleHTTPRequestHandler ):
    extensions_map = { **SimpleHTTPRequestHandler.extensions_map,
        ".m3u8":"application/vnd.apple.mpegurl",".m4s":"video/iso.segment",".ts":"video/mp2t" }
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

def serve(path, host, port):
    os.chdir(path)
    httpd = ThreadingHTTPServer((host, port), H)
    import threading
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd

def need(cmd):
    if shutil.which(cmd) is None:
        print(f"Missing '{cmd}' in PATH", file=sys.stderr); sys.exit(1)

def main():
    ap = argparse.ArgumentParser(description="Stream a YouTube video as live HLS using yt-dlp + ffmpeg")
    ap.add_argument("url")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--seg", type=int, default=6)
    ap.add_argument("--list", type=int, default=10)
    ap.add_argument("--workdir")
    ap.add_argument("--cast", help="Chromecast device name (requires catt)")
    args = ap.parse_args()

    need("yt-dlp"); need("ffmpeg")
    if args.cast: need("catt")

    # get direct video/audio URLs (H.264+AAC preferred)
    fmt = "bestvideo[vcodec^=avc1][height>=?900]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
    cmd = ["yt-dlp","-f",fmt,"--get-url","--no-playlist",args.url]
    urls = subprocess.check_output(cmd, text=True).strip().splitlines()
    if len(urls) == 1:   # single muxed stream fallback
        vurl, aurl = urls[0], urls[0]
        map_args = ["-map","0:v:0","-map","0:a:0"]
    else:
        vurl, aurl = urls[0], urls[1]
        map_args = ["-map","0:v:0","-map","1:a:0"]

    work = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp(prefix="yt_hls_"))
    work.mkdir(parents=True, exist_ok=True)

    httpd = serve(str(work), "0.0.0.0", args.port)
    url = f"http://{local_ip()}:{args.port}/master.m3u8"
    print(f"[i] HLS at: {url}")

    ff = [
        "ffmpeg","-hide_banner","-loglevel","warning",
        "-re","-i", vurl, "-i", aurl, *map_args,
        "-c:v","copy","-c:a","aac","-b:a","128k",
        "-f","hls","-hls_segment_type","fmp4",
        "-hls_time",str(args.seg), "-hls_list_size",str(args.list),
        #"-hls_flags","delete_segments+append_list+omit_endlist+independent_segments",
        "-master_pl_name","master.m3u8",
        "-hls_segment_filename",str(work/"seg_%05d.m4s"),
        str(work/"stream.m3u8")
    ]
    p = subprocess.Popen(ff)

    if args.cast:
        time.sleep(10)
        print(f"[i] Casting to {args.cast} …")
        #subprocess.Popen(["catt","-d",args.cast,"cast",url])
        subprocess.Popen(["cvlc","--sout","#chromecast{ip=10.20.31.232}",url])
    try:
        p.wait()
        while True: time.sleep(1)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

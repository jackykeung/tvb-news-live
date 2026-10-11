#!/usr/bin/env python3
"""
TVB News 83 (無綫新聞台) live-stream HTTP proxy.

Publishes a STABLE single URL that any HLS player (VLC, Safari, IINA) can open:

    http://<host>:8060/news.m3u8

The proxy does the rest internally and transparently:
  - resolves a fresh signed Edgeware HLS URL by POSTing news.tvb.com
  - follows the Edgeware 302 to the per-session edge
  - rewrites the playlists so variants, the audio group, the segments and the
    AES-128 key are all served back through this same port (so the player never
    needs to reach a signed/CDN host, and never sees the hourly-expiring URL)
  - automatically re-resolves a fresh signed URL before the old one expires
  - proxies the live segments + the public AES-128 key

No login, no API key, no DRM. AES-128 HLS. VLC plays it natively.

Design notes
------------
HLS playlists contain RELATIVE URIs (e.g. '3/v1500000/index.m3u8',
'223964760.ts') resolved against the URL of the playlist that referenced them.
Because we proxy on a different host, we REWRITE every reference to be absolute
against this proxy, and we bake the variant path into segment URLs so the proxy
knows exactly where to fetch them:
    /news/pl/<variant>          -> variant/audio playlist (rewritten)
    /news/seg/<variant>/<name>  -> raw segment (.ts) bytes
    /news/key                   -> AES-128 key (public file)

A single cached "source" (session edge base URL + token) is refreshed on
upstream 403/expiry or after a TTL.

Usage:
    python3 tvb_proxy.py [port]      # default 8060
"""
import json
import re
import sys
import ssl
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENDPOINT = "https://news.tvb.com/app/public/live/stream/C"
KEY_URL = "https://ads.cdn.tvb.com/newskeys/live.key"
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) VLC"}
VARIANTS = ("3/v1500000", "3/v1000000", "3/v400000", "3/a128000")

LOCK = threading.Lock()
SRC = {"base": None, "token": "", "resolved_at": 0}
TTL = 60 * 55
REFRESH_MIN = 60


def _ctx():
    c = ssl.create_default_context()
    try:
        import certifi
        c.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return c


_CTX = _ctx()


def _open(req):
    import urllib.request
    return urllib.request.urlopen(req, timeout=20, context=_CTX)


def _req(url, data=None, headers=None):
    import urllib.request
    return urllib.request.Request(url, data=data,
                                  headers=headers or dict(UA))


def _post_stream():
    """POST the public API for a fresh signed stream URL."""
    req = _req(ENDPOINT, data=b"{}",
               headers={"Content-Type": "application/json",
                        "Accept": "application/json", **UA})
    with _open(req) as r:
        d = json.loads(r.read().decode())
    return d["data"]["stream_url"], d["data"].get("refresh_interval", 3600)


def resolve_source(force=False):
    """Return (edge_base, token). edge_base is everything up to and including:
    <scheme>://<session-host>/session/<uuid>/__cl/.../__op/bks  (no __f)."""
    global SRC
    now = time.time()
    with LOCK:
        if (not force and SRC["base"] and now - SRC["resolved_at"] < TTL):
            return SRC["base"], SRC["token"]
        try:
            master, _ = _post_stream()
            req = _req(master)
            with _open(req) as r:
                body = r.read()  # actual master playlist (after 302)
                final = r.geturl()
            q = final.split("?", 1)[1] if "?" in final else ""
            token = dict(p.split("=", 1) for p in q.split("&") if "=" in p) \
                .get("token", "")
            base = final.split("?")[0].rsplit("/", 2)[0]  # drop '^f'/index.m3u8
            SRC.update(base=base, token=token, resolved_at=now)
            return base, token
        except Exception as e:
            print("resolve error:", e, file=sys.stderr)
            if SRC["base"]:
                return SRC["base"], SRC["token"]
            raise


def _upstream(path_within, token):
    """Fetch <edge>/__f/<path_within>?token=... from the session edge."""
    base, tok = resolve_source()
    url = f"{base}/__f/{path_within}?token={tok}&p=3324"
    try:
        with _open(_req(url)) as r:
            return r.read()
    except Exception:
        base, tok = resolve_source(force=True)
        url = f"{base}/__f/{path_within}?token={tok}&p=3324"
        with _open(_req(url)) as r:
            return r.read()


def rewrite_master(text, base_url):
    """Rewrite master variant + audio URIs to point at this proxy.
    base_url is a full origin like 'http://192.168.1.130:8060'."""
    out = []
    for line in text.splitlines():
        m = re.match(r'^(#EXT-X-MEDIA:.*URI=")([^"]+)(".*)$', line)
        if m:
            v = m.group(2)
            out.append(f"{m.group(1)}{base_url}/news/pl/{v}{m.group(3)}")
            continue
        line = line.strip()
        if re.match(r'^3/.*index\.m3u8$', line):
            out.append(f"{base_url}/news/pl/{line}")
            continue
        out.append(line)
    return "\n".join(out)


def rewrite_media(text, base_url, variant):
    """Rewrite a variant/audio media playlist: segments + key point at us."""
    out = []
    for line in text.splitlines():
        m = re.match(r'^(#EXT-X-KEY:.*URI=")([^"]+)(".*)$', line)
        if m:
            out.append(f'{m.group(1)}{base_url}/news/key{m.group(3)}')
            continue
        s = line.strip()
        if re.match(r'^[0-9a-zA-Z._-]+\.ts$', s):
            out.append(f"{base_url}/news/seg/{variant}/{s}")
            continue
        out.append(line)
    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    server_version = "TVBProxy/1.0"

    def _send(self, body, ctype="application/vnd.apple.mpegurl"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # full base URL: scheme + Host. Default http; allow X-Forwarded-Proto (behind a TLS proxy).
        hostport = self.headers.get("Host", "")
        proto = self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() or "http"
        base_url = f"{proto}://{hostport}"
        path = self.path.split("?", 1)[0]
        try:
            resolve_source()
            if path in ("/news.m3u8", "/", "/index.m3u8"):
                body = _upstream("index.m3u8", "")
                out = rewrite_master(body.decode(), base_url)
                self._send(out.encode())
            elif path.startswith("/news/pl/"):
                v = path[len("/news/pl/"):]
                body = _upstream(v, "")
                vdir = v.rsplit("/", 1)[0]  # e.g. '3/v1500000'
                out = rewrite_media(body.decode(), base_url, vdir)
                self._send(out.encode())
            elif path.startswith("/news/seg/"):
                rest = path[len("/news/seg/"):]
                variant, _, seg = rest.rpartition("/")
                body = _upstream(f"{variant}/{seg}", "")
                self._send(body, "video/mp2t")
            elif path == "/news/key":
                body = _key()
                self._send(body, "application/octet-stream")
            elif path == "/health":
                self._send(b'{"ok":true}\n', "application/json")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"not found")
        except Exception as e:
            print("GET err:", path, repr(e), file=sys.stderr)
            try:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(str(e).encode())
            except Exception:
                pass

    def log_message(self, fmt, *args):
        pass


def _key():
    with _open(_req(KEY_URL)) as r:
        return r.read()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8060
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"TVB News 83 proxy on :{port}")
    print(f"  VLC URL: http://localhost:{port}/news.m3u8")
    srv.serve_forever()


if __name__ == "__main__":
    main()
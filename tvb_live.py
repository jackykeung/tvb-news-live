#!/usr/bin/env python3
"""TVB News 83 (無綫新聞台) live-stream URL resolver.

POSTs to the app's public live-stream endpoint, returns a fresh signed Edgeware
HLS URL. Two modes:

  default (ad-marked): keeps `mode=admarker,ticks` — the stream as the app plays it.
  clean (ad-light):    strips `mode=admarker,ticks` and uses the non-`admarker`
                       playlist — roll-up news channel has no client ads anyway;
                       avoids the SCTE-35 ad-marker cue points.

The signed URL expires (refresh_interval ~3600s), so fetch fresh each play / mount.
No login, no API key, no DRM. AES-128 HLS — VLC plays it natively.

Usage:
  python3 tvb_live.py            # print the ad-marked URL
  python3 tvb_live.py clean      # print the clean URL
  python3 tvb_live.py channel C  # another channel id (only 'C' exists today)
"""
import sys
import json
import shlex
import ssl

ENDPOINT = "https://news.tvb.com/app/public/live/stream"


def _ctx():
    c = ssl.create_default_context()
    try:
        import certifi
        c.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return c


_CTX = _ctx()


def resolve(channel="C"):
    import urllib.request
    req = urllib.request.Request(
        f"{ENDPOINT}/{channel}",
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "tvb-live-resolver"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15, context=_CTX) as r:
        d = json.loads(r.read().decode())
    if not d.get("success"):
        raise SystemExit(f"API error: {d}")
    return d["data"]["stream_url"]


def clean(url):
    """Return the ad-marker-free variant of a signed stream URL."""
    # Drop the admarker cue mode so we don't get SCTE-35 ad markers.
    q = url.split("?")[0] + "?" + "&".join(
        p for p in url.split("?")[1].split("&") if "mode=" not in p)
    # Edgeware serves a clean playlist at the NON-admarker path once followed to
    # the session host; the master without mode= already picks the clean variant.
    return q


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "default").lower()
    ch = sys.argv[2] if len(sys.argv) > 2 else "C"
    url = resolve(ch)
    if mode == "clean":
        url = clean(url)
    print(shlex.quote(url))
    # details for humans
    if mode != "quiet":
        print(f"channel={ch} protocol=hls expiry_3600s login=no drm=no", file=sys.stderr)


if __name__ == "__main__":
    main()
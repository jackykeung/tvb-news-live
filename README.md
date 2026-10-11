# TVB News 83 — Live Stream Analysis

Reverse-engineered analysis of the **TVB News 83 (無綫新聞台)** public live stream,
recovered from the Android app (`com.tvb.iNews` v4.1.2, Flutter).

## What's here

| File | Purpose |
|------|---------|
| `report.html` (and `proxy-report.html`) | **Self-contained analysis report + live player** — open in any browser. Covers the endpoint contract, the ad mechanism, and a built-in HLS player (hls.js inlined, no CDN). |
| `tvb_live.py` | Resolver script — prints a fresh signed stream URL (clean or ad-marked) for direct VLC use. |
| `deploy/tvb_proxy.py` | **Stable HLS proxy** — publishes one fixed URL any player can open, transparently re-minting the hourly-signed stream. |
| `deploy/tvb-proxy.service` | systemd unit for running the proxy as a service. |
| `assets/tvb-news-83-frame.png` | A decoded frame from the live stream (proof of real broadcast content). |

## Live stream in one line

The public endpoint (no login, no API key, no DRM):

```
POST https://news.tvb.com/app/public/live/stream/C
Content-Type: application/json
Body: {}
```

```json
{
  "success": true,
  "data": {
    "stream_url": "https://edgeware-live2.edgeware.tvb.com/.../index.m3u8?sig=...&mode=admarker,ticks",
    "protocol": "hls",
    "quality": "hd",
    "refresh_interval": 3600,
    "geo_blocked": false
  }
}
```

The signed URL expires after ~1 hour, so re-POST to refresh. Only live channel is `C` (Channel 83 news).

## Play in VLC

```bash
vlc "$(python3 tvb_live.py)"
```

or manually:

```bash
vlc "$(curl -s -X POST -H "Content-Type: application/json" -d '{}' \
  https://news.tvb.com/app/public/live/stream/C \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['stream_url'])")"
```

## Stable proxy (recommended for players)

Because the signed URL expires hourly, a media player (e.g. VLC) that fetches the URL once will hit a
stale link. Point the player at the proxy's **stable URL** instead — the proxy re-mints the signed
URL transparently before it expires:

```
http://<proxy-host>:8060/news.m3u8
```

Deploy `deploy/tvb_proxy.py` on a box on your LAN (e.g. a Pi) and run it as a systemd service:

```bash
sudo install -d /opt/tvb-proxy && sudo cp deploy/tvb_proxy.py /opt/tvb-proxy/
sudo cp deploy/tvb-proxy.service /etc/systemd/system/
sudo systemctl enable --now tvb-proxy
```

The player (VLC / IINA / Safari / PotPlayer) and the proxy must be on the **same network**.
Verified end-to-end: a segment fetched through the proxy decrypts to **H.264 1280×720 @ 25 fps**.

## Key facts

- **Transport:** Edgeware HLS (.m3u8), AES-128 encrypted, 720p/576p/270p + audio, ~8s segments.
- **Decryption key:** public file `https://ads.cdn.tvb.com/newskeys/live.key` — no auth.
- **Login required:** **No** — fully anonymous.
- **DRM:** **None** — only AES-128 content encryption (not Widevine).
- **Ads:** client-side insertion (Google IMA + SCTE-35 markers). The stream itself is ad-free;
  to get the marker-free variant drop `mode=admarker,ticks` and use `index.m3u8` (report player does this).
- **Browser playback:** works via hls.js (stream hosts send `Access-Control-Allow-Origin: *`).

> Not affiliated with TVB. Content and copyright remain with Television Broadcasts Limited.
> This is a technical interoperability study of the public live-stream URL.
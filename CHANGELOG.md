# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-10-11

### Added
- `deploy/tvb_proxy.py` — standalone HLS proxy that publishes a **stable single URL** for the live stream.
  - Resolves a fresh signed Edgeware URL internally, follows the 302 to the per-session edge.
  - Rewrites the HLS playlists so variants, the audio group, segments, and the AES-128 key are all
    served back through the same proxy — a media player never sees the hourly-expiring signed URL.
  - Auto re-resolves a fresh signed URL before the previous one expires (~55 min TTL).
  - No login, no API key, no DRM (AES-128 content encryption only).
- `deploy/tvb-proxy.service` — systemd unit for running the proxy as a service.
- `proxy-report.html` — self-contained report + usage guide for the stable proxy URL.

### Fixed
- Playlist rewrite emitted URLs **without the `http://` scheme**, which strict HLS players (e.g. VLC)
  rejected. All rewritten URIs now carry the full `http://<host>:<port>/` origin (scheme-aware via
  `X-Forwarded-Proto`, defaulting to `http`).

### Notes
- The proxy is LAN-scoped by design: the player and the proxy box must share the same network.
- Verified end-to-end: master → variant → segment → key, with a decrypted segment probing as
  **H.264 1280×720 @ 25 fps**.

## [1.0.0] - 2026-10-11

### Added
- Reverse-engineered the TVB News 83 live stream from the Android app (`com.tvb.iNews` v4.1.2).
- Discovered the public live-stream endpoint: `POST /app/public/live/stream/{channel_id}` (channel `C`).
- `tvb_live.py` — resolver that prints a fresh signed stream URL (`default` or `clean` variant).
- `report.html` — full endpoint analysis + self-contained browser player (hls.js inlined).
- `assets/tvb-news-83-frame.png` — a decoded frame from the live feed.
- README, MIT LICENSE, .gitignore.

### Key findings
- Transport: Edgeware HLS (.m3u8), AES-128, 720p/576p/270p + audio, ~8s segments.
- Decryption key is a public file (`ads.cdn.tvb.com/newskeys/live.key`).
- No login required; no Widevine DRM (AES-128 only).
- Ads are client-side (SCTE-35 + Google IMA overlay); the stream itself is ad-free.
  Dropping `mode=admarker,ticks` yields an ad-marker-free variant.
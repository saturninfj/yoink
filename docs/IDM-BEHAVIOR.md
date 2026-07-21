# IDM Behavior Recon — Spec Document

> Status: **PENDING CAPTURE** — fill from empirical VM/Wine tests.
> Source: Internet Download Manager v6.42 (latest as of 2026-07-21).

## Goal

Empirically capture IDM's runtime behavior to inform `yoink` engine design.
We behavior-clone the good parts, document why we deviate where we do.

## Test environment

- Host: Pandai PC (Fedora 44, kernel 6.19.10, 16GB RAM, 867GB disk free)
- IDM via: Wine 9.x (or full Windows 11 ARM VM via UTM if Wine fails)
- Sniffer: `mitmproxy` (HTTPS interception), `Wireshark` (TCP-level)
- Trust: mitmproxy CA imported into Wine cert store / Windows cert store

## Test scenarios

| # | Scenario | Goal |
|---|---|---|
| S1 | Direct HTTPS download 500MB from Hetzner speed test | Capture default conn count, Range header pattern |
| S2 | Resume after kill at 50% | Capture segment re-allocation strategy |
| S3 | Server without Range support (HTTP 200 OK only) | Fallback behavior |
| S4 | Google Drive large file | CDN behavior, cookie handling |
| S5 | Cloudflare-protected site | TLS fingerprint, anti-bot behavior |
| S6 | Server returning HTTP 429 | Retry interval, backoff |
| S7 | Site with login (HTTP basic) | Cookie persistence per segment |
| S8 | Embedded `<video>` page | Media URL detection mechanism |

## Capture data points

### Per scenario, fill in:

| Metric | Value | How measured |
|---|---|---|
| Default connections | TBD (expected: 8 or 16) | Wireshark SYN count to dst port 443 |
| Max connections setting | TBD | IDM Options → Connection |
| Initial segment size | TBD | mitmproxy Range header |
| Segment size strategy | TBD | even-split / adaptive / unknown |
| Adaptive split trigger | TBD | slow segment after N seconds? |
| User-Agent | TBD | mitmproxy request header |
| Referer handling | TBD | auto-detect Origin? blank? |
| Cookie persistence | TBD | per-segment? per-download? |
| Retry interval (backoff) | TBD | kill segment, measure reconnect delay |
| Max retries | TBD | IDM config |
| Connection reuse | TBD | TCP keepalive flag in Wireshark |
| HTTP/2 or HTTP/1.1 | TBD | ALPN negotiation in Wireshark |
| TLS fingerprint | TBD | JA3 hash via Wireshark |

## Results

### S1 — Direct HTTPS large file

- URL: `https://speed.hetzner.de/500MB.bin`
- Server: nginx, supports Range
- **Default connections observed:** TBD
- **Initial Range header:** TBD
- **UA:** TBD
- **Speed:** TBD MB/s
- **Notes:** TBD

### S2 — Resume after kill

- Kill IDM via `taskkill` / `kill -9` at ~50%
- Restart IDM, click Resume
- **Behavior:** TBD (re-use existing segments? re-split from scratch?)
- **Validation:** does IDM send `If-Range` / `If-Match` with ETag?

### S3 — Server without Range

- Test server: TBD (set up local nginx without `accept_ranges`)
- **Behavior:** TBD (single connection fallback? error?)

### S4 — Google Drive

- **Cookie handling:** TBD
- **Conn count:** TBD
- **Notes:** TBD

### S5 — Cloudflare

- **TLS fingerprint (JA3):** TBD
- **Behavior:** does IDM pass Cloudflare's anti-bot? TBD

### S6 — HTTP 429

- **Retry interval:** TBD
- **Backoff pattern:** TBD

### S7 — Authenticated site

- **Cookie persistence:** TBD
- **Per-segment cookie:** TBD

### S8 — Media capture

- Test page: TBD (Twitter video, news site, YouTube)
- **Mechanism:** TBD (`<video>` tag hook / network sniff / browser API hook)
- **Button appears on:** TBD
- **URL extraction:** TBD (direct .mp4? m3u8? both?)

## Findings → yoink design decisions

Document how each finding maps to a yoink implementation choice:

| Finding | yoink decision |
|---|---|
| Default N connections | Use same N as our default |
| Adaptive split after T seconds | Implement in `splitter.py` |
| UA string X | Use as default (config-overridable) |
| Retry interval 5s ± jitter | Match in `retry.py` |
| ... | ... |

## Capture artifacts

Save raw capture data to `scripts/recon/captures/`:
- `S1.pcap`, `S1.har`, `S1.mitm.log`
- `S2.pcap`, etc.

Commit to git for reproducibility (small files only, <50MB total).

## Recon host setup log

Track setup steps taken on Pandai PC:

- [ ] Install Wine: `sudo dnf install wine`
- [ ] Download IDM installer from `https://www.internetdownloadmanager.com/`
- [ ] Install IDM via Wine: `wine idman642.exe`
- [ ] Verify IDM launches: `wine ~/.wine/drive_c/Program Files/Internet Download Manager/IDMan.exe`
- [ ] Install mitmproxy: `pip install --user mitmproxy`
- [ ] Generate mitmproxy CA: `mitmproxy` first run → `~/.mitmproxy/mitmproxy-ca-cert.pem`
- [ ] Import CA into Wine cert store: `wine certmgr -add -c ~/.mitmproxy/mitmproxy-ca-cert.pem -r localMachine -s Root`
- [ ] Configure IDM proxy: `127.0.0.1:8082`
- [ ] Verify HTTPS intercept works (test S1)
- [ ] Install Wireshark: `sudo dnf install wireshark`
- [ ] Capture S1-S8

## Recon date

Started: TBD
Completed: TBD

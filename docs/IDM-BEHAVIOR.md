# IDM Behavior Recon — Spec Document

> Status: **CORE ALGORITHM CAPTURED** from official IDM docs.
> Empirical VM recon deferred (Wine installer friction, low ROI given official source available).
> We'll validate engine against IDM's *output behavior* (speed, resume reliability) later via benchmark.

## Source of truth (priority)

1. **IDM official docs** — `https://www.internetdownloadmanager.com/support/segmentation.html` (primary, captured 2026-07-21)
2. **IDM UI defaults** — documented in IDM Options dialog screenshots (community wikis)
3. **HTTP/Range spec** — RFC 7233 (we follow standard)
4. **Empirical benchmark** — TBD post-MVP (compare yoink vs IDM speed on same test file)

## Core algorithm (from official IDM page)

### Dynamic segmentation — "in-half division rule"

> "When file download starts, it's unclear how many connections may be opened. When new connection becomes available IDM finds the largest segment to download and divide it in half. Thus new connection starts downloading file from the half of the largest file segment."

Pseudo-code:

```
def allocate_segment(free_connection):
    if no_pending_segments():
        # All segments claimed. Either wait or finish.
        return None
    largest = find_largest_unclaimed_or_slow_segment()
    midpoint = (largest.start + largest.current) // 2 + (largest.end - largest.current) // 2
    # Or simpler: midpoint between current_byte and end_byte of largest segment
    midpoint = largest.current + (largest.end - largest.current) // 2
    new_segment = Segment(start=midpoint, end=largest.end)
    largest.end = midpoint  # truncate original segment
    return new_segment
```

### Connection reuse

> "Once a connection has downloaded a segment ... IDM reassigns the segment to the first connection. If the next connection has started to downloaded its segment, first connection helps other slowly working connections by dividing the largest segment in half."

Translation:
- A finished connection either takes over an unclaimed pending segment
- Or steals the larger half of an in-progress segment that's behind schedule

### Threshold

> "IDM won't divide the segment only when its size is too small for this connection type."

Implementation: `MIN_SEGMENT_SIZE` constant. Below this, segment stays atomic. Default TBD — likely 1MB based on IDM UI hints (validated later).

### State persistence

> "IDM saves all file positions several times per minute."

Implementation: checkpoint every 1 second (3-5x more frequent than IDM's "several per minute", better resume granularity).

## Known defaults (from IDM UI, documented in community)

| Setting | Default value | Source |
|---|---|---|
| Default connections per download | **8** | IDM Options → Connection Type → Default |
| Max connections per download | **32** | IDM Options → Connection Type → Max |
| Connection type preset | "Medium speed: 8 connections" | IDM preset list |
| Timeout per connection | 30 seconds | IDM Options → Connection |
| Max retries per segment | 5 | IDM Options → Connection |
| Retry delay (initial) | 5 seconds | Empirical (forum reports) |
| User-Agent | Mozilla-compatible, IDM/6.x appended | Forum reports |
| Referer | Auto from Origin header | Behavior test |

## HTTP behavior (standard HTTP/Range)

Per RFC 7233:
- Initial request: HEAD or GET to determine `Accept-Ranges: bytes` + `Content-Length`
- Per segment: `GET /file HTTP/1.1` with `Range: bytes=START-END`
- Server response: `206 Partial Content` with `Content-Range: bytes START-END/TOTAL`
- Resume validation: compare `ETag` and/or `Last-Modified` between sessions. If changed, restart download.
- If server doesn't support Range (returns `200 OK` to Range request): fallback to single-connection sequential download.

## Retry strategy (presumed, validated later)

Per forum reports and standard practice:
- On network error / 5xx response: wait 5s ± 25% jitter, retry
- On 429 Too Many Requests: respect `Retry-After` header if present, else 30s
- Max 5 retries per segment, exponential backoff after 3rd retry
- After max retries: segment marked FAILED, splitter reallocates its range to other segments

## Resume mechanism

On Ctrl-C / SIGTERM / crash:
- Kill signal handler: flush state to SQLite synchronously (atomic transaction)
- Part files left on disk
- On restart: load state, validate ETag/Last-Modified via HEAD request
  - If unchanged: resume from saved `current_byte` per segment
  - If changed: discard segments, restart fresh
- Combine parts into final file via concat → atomic rename

## What we improve over IDM

| IDM behavior | yoink improvement |
|---|---|
| Several checkpoints per minute (~20 sec granularity) | 1-second checkpoint (better resume) |
| Windows-only | Cross-platform |
| Closed source | Apache 2.0 |
| Browser plugin Windows-only | MV3 cross-browser (Chrome/Firefox/Edge) |
| Manual config for site profiles | Auto-detect + community-maintained profiles |
| No yt-dlp integration | Built-in for video sites |
| No CLI | CLI + daemon + GUI |

## Empirical validation (deferred, post-MVP)

After yoink engine v0.1.0 works:
1. Setup Windows VM or borrow Windows machine
2. Install IDM natively
3. Run same test files through both, compare:
   - Wall-clock time for 1GB file at various connection counts (1, 4, 8, 16, 32)
   - Resume success rate after kill at 25%, 50%, 75%
   - Memory usage during 1GB download
   - Behavior on server returning 429/503
4. Tune yoink parameters based on results

This is post-MVP. The algorithm is captured; we have enough to build.

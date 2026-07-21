# yoink Architecture

## High-level system

```
┌──────────────────┐  native msg   ┌─────────────────┐  HTTP/2   ┌────────┐
│ Chrome Extension │ ────────────► │ yoink-daemon    │ ────────► │ Server │
│ (MV3 + Firefox)  │ ◄───────────  │ (Python, stdio) │ ◄────────  │ (file) │
└──────────────────┘   progress     └─────────────────┘           └────────┘
        ▲                              │
        │ intercept                     │ SQLite state
        │ chrome.downloads              ▼
        ▼                          ~/.yoink/state.db
┌──────────────────┐
│ Browser (user)   │
└──────────────────┘

┌──────────────────┐
│ yoink CLI        │ ── direct ─► DownloadEngine (same code as daemon)
│ (typer + rich)   │
└──────────────────┘
```

The `DownloadEngine` is shared by both the CLI and the daemon. No duplicate logic.

## Module map

```
yoink/
├── cli/
│   ├── main.py             # Typer entrypoint, command registration
│   ├── commands.py         # download, resume, queue, list, config commands
│   └── tui.py              # Rich progress per segment, optional Textual dashboard
├── core/
│   ├── engine.py           # DownloadEngine: orchestrates segments per download
│   ├── segment.py          # Segment: state machine (PENDING/DOWNLOADING/...)
│   ├── http_client.py      # httpx AsyncClient wrapper, conn pool, HTTP/2
│   ├── state.py            # SQLite state store + checkpoint loop
│   ├── resume.py           # Resume validator (ETag/Last-Modified check)
│   ├── retry.py            # Exponential backoff with jitter
│   ├── splitter.py         # Adaptive segment size logic
│   └── queue.py            # QueueManager (named queues, parallel count)
├── auth/
│   ├── cookies.py          # Mozilla cookies.sqlite + Netscape cookie file
│   ├── basic.py            # HTTP Basic auth
│   └── bearer.py           # Bearer token
├── media/
│   ├── ytdlp.py            # yt-dlp wrapper, URL detection + format selection
│   ├── hls.py              # m3u8 parser + HLS segment downloader + AES-128
│   ├── dash.py             # MPD parser + DASH segment downloader
│   └── sniffer.py          # URL pattern matcher (is this a video page?)
├── browser/
│   ├── native_host.py      # stdio JSON-RPC daemon
│   └── protocol.py         # RPC schema (pydantic models)
├── config.py               # TOML loader, defaults
├── paths.py                # XDG dirs, part files location
└── exceptions.py
```

## State machine (per segment)

```
PENDING ─► DOWNLOADING ─► COMPLETED
   │           │
   │           ├─► FAILED ─► (retry w/ backoff) ─► DOWNLOADING
   │           │
   │           └─► PAUSED ─► (resume) ─► DOWNLOADING
   │
   └─► CANCELLED
```

## SQLite schema

See [`yoink/core/state.py`](../yoink/core/state.py) for the canonical DDL.

Three tables:
- `downloads` — top-level download record (url, output_path, status, total_size)
- `segments` — one row per byte-range segment
- `queue` / `queue_items` — named queues for batch scheduling

Checkpoint loop: write `current_byte` per segment every 1 second, atomic transaction.

## Part-file layout

```
~/Downloads/
├── big-file.zip                 ← final output (atomic rename on completion)
└── .big-file.zip.yoink/         ← part dir, hidden
    ├── state.db                 ← SQLite checkpoint
    ├── 0.part                   ← segment 0 bytes [0, 1048576)
    ├── 1.part                   ← segment 1 bytes [1048576, 2097152)
    ├── ...
    └── 7.part
```

On completion: concat parts → write to final path via atomic rename. On resume: load state.db, re-validate ETag, continue.

## Native messaging protocol

JSON-RPC 2.0 over stdio with 4-byte little-endian length prefix (Chrome spec).

```json
// Chrome → Host
{"jsonrpc":"2.0","method":"download.start","params":{
   "url":"https://...",
   "filename":"file.zip",
   "referer":"...",
   "cookies":[{"name":"sess","value":"abc"}]
},"id":1}

// Host → Chrome: ack
{"jsonrpc":"2.0","result":{"download_id":42,"status":"started"},"id":1}

// Host → Chrome: unsolicited progress event
{"jsonrpc":"2.0","method":"download.progress","params":{
   "download_id":42,
   "downloaded":5242880,
   "total":10485760,
   "speed":2097152
}}
```

## Performance targets

| Metric | Target |
|---|---|
| Speed (1GB file, gigabit) | match aria2c within 10% |
| Memory | < 80MB RAM per active download |
| CPU | < 5% average during download |
| Resume reliability | 100% after SIGINT, SIGKILL, crash |
| Concurrency | 10 parallel downloads without degradation |

## Dependencies

Core:
- `httpx[http2]` — HTTP/2 client, async + sync
- `anyio` — structured concurrency, cross-async-backend
- `typer` — CLI framework
- `rich` — terminal output / progress
- `click` — typer backend

Optional:
- `yt-dlp` — media URL resolution (Phase 4)

Dev:
- `pytest` + `pytest-asyncio` + `respx` (HTTP mock)
- `ruff` + `mypy` (strict)
- `pytest-cov`

## OS support

Tier 1 (CI-tested): macOS arm64, Linux x86_64, Windows x86_64.
Tier 2 (best-effort): macOS x86_64, Linux arm64.

Browser extension:
- Chrome / Brave / Edge / Opera (Chromium MV3)
- Firefox (WebExtension polyfill)

## License

Apache 2.0. Patent grant included, commercial-safe.

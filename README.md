# yoink

> Multi-segment HTTP downloader with browser integration. OSS alternative to Internet Download Manager.

**Status: Alpha — core engine, CLI, native host, browser extension, yt-dlp all working.**

## What

`yoink` is a cross-platform download manager that behavior-clones IDM's best features:

- Multi-segment parallel HTTP downloads (1–32 connections per file)
- Adaptive segment splitting (IDM-style "in-half division rule")
- Sparse-file pre-allocation — no concat at end, instant resume from any byte
- Atomic resume after Ctrl-C, crash, or power off (SQLite checkpoint every 1s)
- ETag / Last-Modified validation before resume — won't silently corrupt if file changed server-side
- Per-segment exponential backoff retry with jitter (network errors, 5xx, timeouts)
- Browser integration via Manifest V3 extension + native messaging host (Chrome/Brave/Edge/Firefox)
- Live progress notifications from native host to extension popup
- yt-dlp integration for video sites (YouTube, Twitter, IG, TikTok, …)
- Cookie jar (Netscape format), HTTP Basic auth, custom headers
- Named state DB at `~/.yoink/state.db` for `list` / `resume` / `cancel` workflows

## Why

IDM is paid, closed-source, Windows-only. `aria2` is CLI-only with no browser plugin. `yt-dlp` covers streaming but not generic files. `yoink` is the missing OSS middle ground.

## Install (dev — not yet on PyPI)

```bash
git clone https://github.com/saturninfj/yoink.git
cd yoink
uv sync --extra dev          # or: pip install -e '.[dev,media]'
yoink --version
```

## Usage

```bash
# Basic download — 8 connections by default
yoink download https://example.com/big-file.zip

# Customise
yoink download URL -o ~/Downloads/ -c 16

# Custom headers / basic auth / cookies
yoink download URL -H "Authorization: Bearer xxx" -b cookies.txt -u user:pass

# Resume after Ctrl-C / crash
yoink list                   # find the id
yoink resume 42

# Cancel / purge
yoink cancel 42
yoink cancel 42 --purge      # also remove file + DB record

# Video via yt-dlp
yoink video https://www.youtube.com/watch?v=...
yoink video URL --list-formats
yoink video URL -f "bestvideo[height<=1080]+bestaudio"
```

## Browser integration

1. **Install the native host**:

   ```bash
   yoink install-browser-host --browser chrome
   ```

   Repeat for `brave`, `edge`, `firefox` as needed. For tighter security, pass
   your extension ID after loading the unpacked extension once:

   ```bash
   yoink install-browser-host --browser chrome --extension-id <id>
   ```

2. **Load the extension**:
   - Chrome → `chrome://extensions` → Developer mode → Load unpacked → select `extension/`

3. **Use**:
   - Click the yoink icon → status dot should be green ("host connected")
   - Paste a URL → "yoink it"
   - Toggle interception in the settings page (`chrome-extension://<id>/options.html`)

See [docs/EXTENSION-BUILD.md](docs/EXTENSION-BUILD.md) for Firefox, troubleshooting, and manifest details.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/IDM-BEHAVIOR.md](docs/IDM-BEHAVIOR.md).

The IDM algorithm is reimplemented from the official spec at
`internetdownloadmanager.com/support/segmentation.html`. Empirical benchmark vs
IDM itself is on the post-MVP TODO.

## Repo layout

```
yoink/
├── yoink/                  # Python package
│   ├── cli/                # typer + rich commands
│   ├── core/               # engine, http_client, segment, state, retry, resume
│   ├── auth/               # cookie jar, basic auth
│   ├── browser/            # native_host, install, protocol
│   └── media/              # yt-dlp wrapper
├── extension/              # Chrome MV3 (manifest, background, popup, options)
├── scripts/recon/          # local range-test server (integration tests)
├── tests/                  # unit + integration
└── docs/                   # ARCHITECTURE, EXTENSION-BUILD, IDM-BEHAVIOR
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format .
uv run mypy yoink
uv run pytest               # 12 tests (5 unit + 7 integration), all green
```

Integration tests spin up a local range-enabled HTTP server, so no external
network is required.

## License

Apache 2.0 — see [LICENSE](LICENSE).

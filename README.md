# yoink

> Multi-segment HTTP downloader with browser integration. OSS alternative to Internet Download Manager.

**Status: Pre-Alpha (Phase 0 — IDM recon in progress)**

## What

`yoink` is a cross-platform download manager that behavior-clones IDM's best features:

- Multi-segment parallel HTTP downloads (default 8, max 32 connections per file)
- Adaptive segment splitting — slow segments get subdivided
- Atomic resume after Ctrl-C, crash, or network drop
- Browser integration via MV3 extension + native messaging host
- Media URL sniffing for embedded video/audio
- yt-dlp integration for streaming sites
- Named queues with parallel-count and priority

## Why

IDM is paid, closed-source, Windows-only. `aria2` is CLI-only with no browser plugin. `yt-dlp` covers streaming but not generic files. `yoink` is the missing OSS middle ground.

## Install

Not yet on PyPI. For development:

```bash
git clone https://github.com/saturninfj/yoink.git
cd yoink
uv sync
uv run yoink --version
```

## Usage (target CLI)

```bash
# Simple download
yoink https://example.com/big-file.zip

# With options
yoink https://example.com/big-file.zip -o ~/Downloads/ -c 16

# Resume by id
yoink resume 42

# Queue
yoink queue create music --parallel 3
yoink queue add music https://example.com/song1.mp3
yoink queue start music

# Video (yt-dlp integration)
yoink video https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## IDM recon

See [docs/IDM-BEHAVIOR.md](docs/IDM-BEHAVIOR.md) for empirical capture of IDM's behavior (connection count, segment strategy, retry pattern).

## License

Apache 2.0 — see [LICENSE](LICENSE).

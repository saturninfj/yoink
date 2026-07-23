# Contributing to yoink

Thanks for considering a contribution. The project is small and the bar is low — open an issue first if you're unsure whether a change fits.

## Setup

```bash
git clone https://github.com/saturninfj/yoink.git
cd yoink
uv sync --extra dev        # or: pip install -e '.[dev,media]'
uv run pytest              # confirm baseline green
```

You need Python 3.12 or newer. `uv` is recommended but not required.

## Code style

- **Lint / format**: `ruff check . && ruff format .` — both must be clean.
- **Types**: `mypy yoink` runs in strict mode. New code must type-check.
- **Tests**: any new behaviour should ship with at least one test. Use
  `tests/unit/` for pure logic, `tests/integration/` for end-to-end flows.
- **Comments**: write them in English. Reserve comments for *why*, not *what*.
  The codebase already follows this — match its tone.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): short summary

optional body explaining why
```

Examples:
- `feat(core): adaptive segment splitter`
- `fix(browser): reconnect native port on disconnect`
- `docs: extend EXTENSION-BUILD for Firefox`
- `chore: bump httpx to 0.28`

## Pull request flow

1. Fork → feature branch (`feat/my-thing`, `fix/bug-x`)
2. Push → open PR against `main`
3. CI runs `ruff`, `mypy`, `pytest` on macOS / Linux / Windows for Python 3.12 + 3.13
4. Address review feedback; squash if you have many WIP commits
5. Maintainer merges

Don't bump the version in your PR — that happens at release time.

## Architecture orientation

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. The short version:

- **DownloadEngine** is the core. It owns segment splitting, parallel async
  I/O via `anyio.create_task_group`, and an optional `StateStore`.
- **HttpClient** is a thin `httpx.AsyncClient` wrapper with HTTP/2 + range
  probe.
- **StateStore** is sync SQLite. Writes are sub-ms so safe to call from async
  without thread-pool ceremony.
- **NativeHost** bridges browser ↔ engine via stdio JSON-RPC.

## Reporting bugs

Open a GitHub issue with:

- `yoink --version`
- OS + Python version
- Exact command you ran
- What you expected vs what happened
- Relevant snippet from `~/.yoink/state.db` if a download got stuck

For browser-extension issues, also include:
- Browser + version
- Whether the host status dot is green ("host connected")
- Screenshot of the popup
- `chrome://extensions` → yoink → "Service worker" → console errors

## Licensing

By contributing you agree your changes will be released under the Apache 2.0
license, same as the rest of the project.

"""CLI commands for yoink."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from yoink.auth.cookies import cookies_to_header, parse_netscape_cookie_file
from yoink.core.engine import DownloadEngine
from yoink.core.retry import RetryPolicy
from yoink.core.state import StateStore
from yoink.exceptions import YoinkError

console = Console()


def download(
    url: str = typer.Argument(..., help="URL to download."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path. Defaults to URL basename or 'index.bin'.",
    ),
    connections: int = typer.Option(
        8,
        "--connections",
        "-c",
        min=1,
        max=32,
        help="Number of parallel connections (1-32).",
    ),
    header: list[str] = typer.Option(
        [],
        "--header",
        "-H",
        help="Extra HTTP header (repeatable). Format: 'Key: Value'.",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        "-u",
        help="HTTP Basic auth: 'user:password'.",
    ),
    cookie_jar: Path | None = typer.Option(
        None,
        "--cookie-jar",
        "-b",
        help="Netscape-format cookies.txt file.",
    ),
    max_retries: int = typer.Option(
        5,
        "--max-retries",
        help="Max retries per segment on transient errors.",
    ),
    ephemeral: bool = typer.Option(
        False,
        "--ephemeral",
        help="Skip state persistence. Resume will be unavailable.",
    ),
) -> None:
    """Download URL with multi-segment parallel connections."""
    try:
        asyncio.run(
            _download_async(
                url=url,
                output=output,
                connections=connections,
                headers=_parse_headers(header),
                user=user,
                cookie_jar=cookie_jar,
                max_retries=max_retries,
                ephemeral=ephemeral,
            )
        )
    except YoinkError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted — state saved; use 'yoink resume <id>'[/yellow]")
        raise typer.Exit(code=130) from None


def _parse_headers(raw: list[str]) -> dict[str, str]:
    """Parse repeated --header args into a dict."""
    out: dict[str, str] = {}
    for item in raw:
        if ":" not in item:
            raise typer.BadParameter(f"header must be 'Key: Value', got {item!r}")
        key, value = item.split(":", 1)
        out[key.strip()] = value.strip()
    return out


async def _download_async(
    *,
    url: str,
    output: Path | None,
    connections: int,
    headers: dict[str, str],
    user: str | None,
    cookie_jar: Path | None,
    max_retries: int,
    ephemeral: bool,
) -> None:
    extra_headers = dict(headers)

    if user:
        if ":" not in user:
            raise typer.BadParameter("--user must be 'user:password'")
        token = base64.b64encode(user.encode()).decode()
        extra_headers["Authorization"] = f"Basic {token}"

    if cookie_jar:
        cookies = parse_netscape_cookie_file(cookie_jar)
        if cookies:
            host = urlparse(url).hostname or ""
            cookie_header = cookies_to_header(cookies, host)
            if cookie_header:
                extra_headers["Cookie"] = cookie_header

    state: StateStore | None = None if ephemeral else StateStore()
    engine = DownloadEngine(
        connections=connections,
        state_store=state,
        extra_headers=extra_headers,
        retry_policy=RetryPolicy(max_retries=max_retries),
    )

    info = await engine.head(url)
    if output is None:
        output = Path(info.suggested_filename)
    output = output.expanduser().resolve()

    total = info.total_size or 0
    console.print(f"[cyan]yoink[/cyan] {url}")
    console.print(f"       → {output}  ({total / 1_000_000:.1f} MB, {connections} conns)")

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("downloading", total=total or None)
        async for tick in engine.stream(url, output):
            progress.update(task_id, completed=tick.downloaded)

    console.print(f"[green]done[/green] {output}")


def resume(
    download_id: int = typer.Argument(..., help="ID from 'yoink list'."),
    connections: int | None = typer.Option(
        None,
        "--connections",
        "-c",
        min=1,
        max=32,
        help="Override original connection count.",
    ),
) -> None:
    """Resume a previously paused or failed download by ID."""
    try:
        asyncio.run(_resume_async(download_id, connections))
    except YoinkError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted — state saved[/yellow]")
        raise typer.Exit(code=130) from None


async def _resume_async(download_id: int, connections: int | None) -> None:
    with StateStore() as state:
        record = state.get_download(download_id)
        if record is None:
            console.print(f"[red]error:[/red] no download with id={download_id}")
            raise typer.Exit(code=1)

        n_conns = connections or record.connections
        engine = DownloadEngine(connections=n_conns, state_store=state)

        console.print(
            f"[cyan]resume[/cyan] #{download_id}  "
            f"({record.downloaded_size}/{record.total_size or '?'} bytes)"
        )
        console.print(f"        → {record.output_path}")

        total = record.total_size or 0
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "resuming", total=total or None, completed=record.downloaded_size
            )
            async for tick in engine.resume(download_id):
                progress.update(task_id, completed=tick.downloaded)

        console.print(f"[green]done[/green] {record.output_path}")


def list_downloads(
    status: str | None = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: downloading, paused, completed, failed, cancelled.",
    ),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=200),
) -> None:
    """List recorded downloads."""
    with StateStore() as state:
        records = list(state.list_downloads(status=status, limit=limit))

    if not records:
        console.print("[dim]no downloads yet[/dim]")
        return

    table = Table(title="yoink downloads", show_lines=False)
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")
    table.add_column("Progress", justify="right")
    table.add_column("Output")
    table.add_column("URL", overflow="fold")

    for r in records:
        if r.total_size:
            pct = f"{r.progress_pct * 100:.1f}%"
        else:
            pct = "?"
        url_display = _truncate(r.url, 60)
        table.add_row(
            str(r.id),
            r.status,
            pct,
            Path(r.output_path).name,
            url_display,
        )

    console.print(table)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters, appending ellipsis if cut."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def cancel(
    download_id: int = typer.Argument(..., help="ID to cancel."),
    purge: bool = typer.Option(False, "--purge", help="Also delete the part file and DB record."),
) -> None:
    """Cancel a download and optionally purge its files."""
    with StateStore() as state:
        record = state.get_download(download_id)
        if record is None:
            console.print(f"[red]error:[/red] no download with id={download_id}")
            raise typer.Exit(code=1)

        if purge:
            output = Path(record.output_path)
            if output.exists():
                output.unlink()
            state.delete(download_id)
            console.print(f"[yellow]purged[/yellow] #{download_id} ({output.name})")
        else:
            ok = state.cancel(download_id)
            if ok:
                console.print(f"[yellow]cancelled[/yellow] #{download_id}")
            else:
                console.print(f"[red]error:[/red] #{download_id} not in a cancellable state")
                raise typer.Exit(code=1)


def daemon() -> None:
    """Run the native messaging host (stdio JSON-RPC). Invoked by browsers."""
    from yoink.browser.native_host import main as host_main  # noqa: PLC0415

    host_main()


def install_browser_host(
    browser: str = typer.Option(
        "chrome", "--browser", "-b", help="chrome, brave, edge, firefox, chromium."
    ),
    extension_id: list[str] = typer.Option(
        [],
        "--extension-id",
        help="Browser extension ID allowed to talk to host (repeatable).",
    ),
    python_bin: Path = typer.Option(
        Path("/usr/bin/env python3"),
        "--python",
        help="Python interpreter to invoke from the host wrapper.",
    ),
) -> None:
    """Install the native messaging host manifest for browser integration."""
    from yoink.browser.install import install_host  # noqa: PLC0415

    if not extension_id:
        console.print(
            "[yellow]hint:[/yellow] no --extension-id given; manifest will allow any "
            "extension origin (dev mode only)."
        )

    try:
        written = install_host(
            python_bin=python_bin,
            browser=browser,
            extension_ids=extension_id,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] install failed: {exc}")
        raise typer.Exit(code=1) from exc

    console.print("[green]installed native host:[/green]")
    for path in written:
        console.print(f"  • {path}")
    console.print(
        f"\n[cyan]next:[/cyan] load the extension in {browser} (unpacked), then test via the popup."
    )


def uninstall_browser_host(
    browser: str = typer.Option(
        "chrome", "--browser", "-b", help="chrome, brave, edge, firefox, chromium."
    ),
) -> None:
    """Remove the native messaging host manifest(s)."""
    from yoink.browser.install import uninstall_host  # noqa: PLC0415

    removed = uninstall_host(browser=browser)
    if not removed:
        console.print("[dim]no manifest files found[/dim]")
        return
    console.print("[yellow]removed:[/yellow]")
    for path in removed:
        console.print(f"  • {path}")

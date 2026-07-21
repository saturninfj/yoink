"""CLI commands for yoink."""

from __future__ import annotations

import asyncio
from pathlib import Path

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

from yoink.core.engine import DownloadEngine
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
) -> None:
    """Download URL with multi-segment parallel connections."""
    try:
        asyncio.run(_download_async(url, output, connections))
    except YoinkError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        raise typer.Exit(code=130) from None


async def _download_async(
    url: str,
    output: Path | None,
    connections: int,
) -> None:
    engine = DownloadEngine(connections=connections)
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

    console.print(f"[green]done[/green] {output} ({info.total_size or 0} bytes)")

"""CLI entrypoint via typer."""

from __future__ import annotations

import typer
from rich.console import Console

from yoink import __version__

app = typer.Typer(
    name="yoink",
    help="Multi-segment HTTP downloader with browser integration.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version_flag: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print yoink version and exit.",
        is_eager=True,
    ),
) -> None:
    if version_flag or ctx.invoked_subcommand is None:
        console.print(f"yoink {__version__}")
        raise typer.Exit()


# Register commands (side-effect imports).
from yoink.cli.commands import (  # noqa: E402
    cancel,
    download,
    list_downloads,
    resume,
)

app.command(name="list")(list_downloads)
app.command()(download)
app.command()(resume)
app.command()(cancel)

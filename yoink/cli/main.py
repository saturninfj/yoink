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


@app.command()
def version() -> None:
    """Print yoink version."""
    console.print(f"yoink {__version__}")


if __name__ == "__main__":
    app()

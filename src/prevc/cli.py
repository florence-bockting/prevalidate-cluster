"""Console script for prevalidate-cluster."""

import typer
from rich.console import Console

from prevc import utils

app = typer.Typer()
console = Console()


@app.command()
def main() -> None:
    """Console script for prevalidate-cluster."""
    console.print(
        "Replace this message by putting your code into prevc.cli.main"
    )
    console.print("See Typer documentation at https://typer.tiangolo.com/")
    utils.do_something_useful()


if __name__ == "__main__":
    app()

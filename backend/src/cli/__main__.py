"""SabiScore backend CLI entrypoint."""

from __future__ import annotations

import click

from .backfill import backfill_cli
from .ingest import ingest_cli
from .providers import providers_cli


@click.group()
def main() -> None:
    """SabiScore operational CLI."""


main.add_command(providers_cli, "providers")
main.add_command(backfill_cli, "backfill")
main.add_command(ingest_cli, "ingest")


@main.command(
    "data",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def data_cli_proxy(ctx: click.Context) -> None:
    """Forward to the legacy data pipeline CLI."""

    from .data_pipeline import cli as data_cli

    data_cli.main(args=list(ctx.args), prog_name="python -m src.cli data", standalone_mode=True)


if __name__ == "__main__":
    main()

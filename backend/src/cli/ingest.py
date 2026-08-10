"""Operator-only validated manifest ingestion CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click


@click.group("ingest")
def ingest_cli() -> None:
    """Ingest trusted batch evidence; never exposes a public HTTP endpoint."""


@ingest_cli.command("manifest")
@click.argument("manifest_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--data-root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Root containing the manifest and every referenced local artifact.",
)
@click.option("--commit", is_flag=True, help="Commit validated rows. Omit for a rollback-only dry run.")
def ingest_manifest_command(manifest_path: Path, data_root: Path, commit: bool) -> None:
    """Validate hashes and ingest one completed manifest transactionally."""

    async def _run() -> dict[str, object]:
        from ..db.session import AsyncSessionLocal, close_db, init_db
        from ..services.canonical_manifest_ingestion import ingest_manifest

        await init_db()
        if AsyncSessionLocal is None:
            raise click.ClickException("database is unavailable")
        try:
            async with AsyncSessionLocal() as session:
                report = await ingest_manifest(
                    session,
                    manifest_path=manifest_path,
                    data_root=data_root,
                    commit=commit,
                )
                return report.as_dict()
        finally:
            await close_db()

    click.echo(json.dumps(asyncio.run(_run()), indent=2, sort_keys=True))

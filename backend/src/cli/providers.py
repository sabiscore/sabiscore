"""Provider gateway CLI commands."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from ..providers import build_provider_registry
from ..providers.base import ProviderHealth


def _print_json(payload: Any) -> None:
    click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


@click.group()
def providers_cli() -> None:
    """Inspect provider configuration, capabilities, and quotas."""


ProviderCliStatus = str
ProviderLiveValidation = str
ALLOWED_PROVIDER_CLI_STATUSES: tuple[ProviderCliStatus, ...] = (
    "configured",
    "missing",
    "invalid",
    "quota_exhausted",
    "temporarily_unavailable",
)
ALLOWED_LIVE_VALIDATION_STATES: tuple[ProviderLiveValidation, ...] = (
    "not_run",
    "passed",
    "failed",
)


def _provider_cli_status(health: ProviderHealth) -> ProviderCliStatus:
    """Map internal provider health to the public five-state CLI contract."""

    status = health.status.value
    if status == "RATE_LIMITED" or health.quota.remaining == 0:
        return "quota_exhausted"
    if status == "INVALID":
        return "invalid"
    if not health.enabled or not health.configured or status == "UNCONFIGURED":
        return "missing"
    if status in {"CIRCUIT_OPEN", "UNAVAILABLE", "PARTIAL", "CONFLICTING"}:
        return "temporarily_unavailable"
    return "configured"


def _live_validation_state(
    health: ProviderHealth,
    *,
    validate_live: bool,
) -> ProviderLiveValidation:
    if not validate_live:
        return "not_run"
    return "passed" if health.status.value == "VERIFIED" else "failed"


async def _provider_status_report(
    provider_id: str | None = None,
    *,
    validate_live: bool = False,
    include_live_validation: bool = False,
) -> dict[str, list[dict[str, str]]]:
    registry = build_provider_registry()
    providers = [registry.get(provider_id)] if provider_id else registry.list()
    if validate_live:
        for provider in providers:
            provider.live_tests = True
    healths = await asyncio.gather(*(provider.health() for provider in providers))
    rows = []
    for health in healths:
        row = {"provider": health.provider, "status": _provider_cli_status(health)}
        if include_live_validation:
            row["live_validation"] = _live_validation_state(
                health,
                validate_live=validate_live,
            )
        rows.append(row)
    return {"providers": rows}


@providers_cli.command("doctor")
@click.option("--provider", "provider_id", default=None, help="Provider id to inspect")
@click.option(
    "--validate-live",
    is_flag=True,
    default=False,
    help="Run the provider's cheapest explicit live validation probe.",
)
def doctor(provider_id: str | None, validate_live: bool) -> None:
    """Report provider status using the public five-state taxonomy only."""

    async def run() -> None:
        _print_json(
            await _provider_status_report(
                provider_id,
                validate_live=validate_live,
                include_live_validation=True,
            )
        )

    asyncio.run(run())


@providers_cli.command("capabilities")
@click.option("--provider", "provider_id", default=None, help="Provider id to inspect")
def capabilities(provider_id: str | None) -> None:
    async def run() -> None:
        registry = build_provider_registry()
        rows = await registry.get(provider_id).capabilities() if provider_id else await registry.capabilities()
        _print_json({"capabilities": [row.model_dump(mode="json") for row in rows]})

    asyncio.run(run())


@providers_cli.command("quota")
@click.option("--provider", "provider_id", default=None, help="Provider id to inspect")
def quota(provider_id: str | None) -> None:
    async def run() -> None:
        registry = build_provider_registry()
        if provider_id:
            values = {provider_id: await registry.get(provider_id).quota()}
        else:
            values = await registry.quota()
        _print_json({"quota": {name: value.model_dump(mode="json") for name, value in values.items()}})

    asyncio.run(run())


@providers_cli.command("status")
@click.option("--provider", "provider_id", default=None, help="Provider id to inspect")
def status(provider_id: str | None) -> None:
    """Report configured | missing | invalid | quota_exhausted | temporarily_unavailable."""

    async def run() -> None:
        _print_json(await _provider_status_report(provider_id, validate_live=False))

    asyncio.run(run())


if __name__ == "__main__":
    providers_cli()

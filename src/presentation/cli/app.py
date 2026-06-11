import asyncio
import json
from uuid import UUID

import click
from pydantic import ValidationError

from application.app import App, get_app
from domain.exceptions import BaseError
from infrastructure.config import get_settings
from presentation.contracts import (
    IngestRequest,
    RetrieveRequest,
    RetrieveResponse,
    validation_message,
)


@click.group()
def cli() -> None:
    """Parser command line interface."""


@cli.command()
def version() -> None:
    """Print the application version."""
    click.echo(get_settings().app.app_version)


@cli.command("ingest")
@click.option("--name", required=True, help="Document name.")
@click.option("--body", required=True, help="Document body.")
@click.option("--source-key", default=None, help="Optional source idempotency key.")
def ingest(name: str, body: str, source_key: str | None) -> None:
    """Ingest one document through the application boundary."""
    app: App = get_app()
    try:
        payload = IngestRequest(name=name, body=body, source_key=source_key)
        id = asyncio.run(app.ingest(payload.doc()))
    except ValidationError as exc:
        raise click.ClickException(validation_message(exc)) from exc
    except BaseError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(str(id))


@cli.command("retrieve")
@click.argument("query")
@click.option("--limit", default=10, type=int, show_default=True, help="Maximum hits.")
def retrieve(query: str, limit: int) -> None:
    """Retrieve documents through the application boundary."""
    app: App = get_app()
    try:
        payload = RetrieveRequest(query=query, limit=limit)
        hits = asyncio.run(app.retrieve(payload.query, limit=payload.limit))
    except ValidationError as exc:
        raise click.ClickException(validation_message(exc)) from exc
    except BaseError as exc:
        raise click.ClickException(str(exc)) from exc

    response = RetrieveResponse.from_hits(hits).model_dump(mode="json")
    click.echo(json.dumps(response, sort_keys=True))


@cli.command("refs")
@click.argument("node_id")
def build_refs(node_id: str) -> None:
    """Build semantic refs for one node."""
    app: App = get_app()
    try:
        id = UUID(node_id)
    except ValueError as exc:
        raise click.ClickException(f"invalid node id: {node_id}") from exc

    try:
        asyncio.run(app.refs(id))
    except BaseError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"built refs for {id}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

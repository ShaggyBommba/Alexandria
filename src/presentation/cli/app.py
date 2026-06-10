import asyncio
from contextlib import contextmanager
import json
from typing import Generator
from uuid import UUID

import click
from pydantic import ValidationError

from application.app import App, get_app
from application.exceptions import AppError
from presentation.contracts import (
    IngestRequest,
    RetrieveRequest,
    RetrieveResponse,
    validation_message,
)


@contextmanager
def lifecycle() -> Generator[App, None, None]:
    """Handles the setup and potential teardown hooks of the App singleton."""
    yield get_app()


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Parser command line interface."""
    # Registers the lifecycle context manager with Click.
    ctx.obj = ctx.with_resource(lifecycle())


@cli.command()
@click.pass_obj
def version(app: App) -> None:
    """Print the application version."""
    click.echo(app.version)


@cli.command("ingest")
@click.option("--name", required=True, help="Document name.")
@click.option("--body", required=True, help="Document body.")
@click.option("--source-key", default=None, help="Optional source idempotency key.")
@click.pass_obj
def ingest(app: App, name: str, body: str, source_key: str | None) -> None:
    """Ingest one document through the application boundary."""
    try:
        payload = IngestRequest(name=name, body=body, source_key=source_key)
        id = asyncio.run(app.ingest(payload.doc()))
    except ValidationError as exc:
        raise click.ClickException(validation_message(exc)) from exc
    except AppError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(str(id))


@cli.command("retrieve")
@click.argument("query")
@click.option("--limit", default=10, type=int, show_default=True, help="Maximum hits.")
@click.pass_obj
def retrieve(app: App, query: str, limit: int) -> None:
    """Retrieve documents through the application boundary."""
    try:
        payload = RetrieveRequest(query=query, limit=limit)
        hits = asyncio.run(app.retrieve(payload.query, limit=payload.limit))
    except ValidationError as exc:
        raise click.ClickException(validation_message(exc)) from exc
    except AppError as exc:
        raise click.ClickException(str(exc)) from exc

    response = RetrieveResponse.from_hits(hits).model_dump(mode="json")
    click.echo(json.dumps(response, sort_keys=True))


@cli.command("refs")
@click.argument("node_id")
@click.pass_obj
def build_refs(app: App, node_id: str) -> None:
    """Build semantic refs for one node."""
    try:
        id = UUID(node_id)
    except ValueError as exc:
        raise click.ClickException(f"invalid node id: {node_id}") from exc

    try:
        asyncio.run(app.refs(id))
    except AppError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"built refs for {id}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

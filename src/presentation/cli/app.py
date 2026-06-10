import asyncio
from contextlib import contextmanager
from typing import Generator
from uuid import UUID

import click

from application.app import App, get_app
from application.exceptions import AppError
from application.ports import DocIn


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
        id = asyncio.run(app.ingest(DocIn(name=name, body=body, source_key=source_key)))
    except AppError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(str(id))


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

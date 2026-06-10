from multiprocessing import Process

import click

from presentation.api.app import main as api
from presentation.cli.app import main as cli
from presentation.mcp.app import main as mcp
from presentation.worker.app import main as worker

SERVICES = {"api": api, "cli": cli, "mcp": mcp, "worker": worker}


@click.command()
@click.argument("targets", type=click.Choice(SERVICES.keys()), nargs=-1)
def main(targets: tuple[str, ...]) -> None:
    """Launch alexandria services. If none specified, all will start."""
    chosen = list(targets) or list(SERVICES.keys())

    if len(chosen) == 1:
        return SERVICES[chosen[0]]()

    processes = [Process(target=SERVICES[name]) for name in chosen]

    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\nStopping all services...")
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join()


if __name__ == "__main__":
    main()

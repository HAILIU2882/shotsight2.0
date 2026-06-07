"""Command-line entrypoint for the independent analysis worker."""

from __future__ import annotations

import argparse
import importlib
import logging
import signal
import socket
import threading
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import cast

from shotsight2.adapters.persistence import SQLiteDatabase
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
from shotsight2.config import settings
from shotsight2.domain.jobs import QueueMessage
from shotsight2.worker.process import PollingBackoff, WorkerProcess


def _database_path(value: str) -> Path:
    prefix = "sqlite:///"
    return Path(value.removeprefix(prefix)) if value.startswith(prefix) else Path(value)


def _missing_handler(message: QueueMessage) -> None:
    raise RuntimeError(f"No analysis handler configured for job {message.job_id}")


def _load_handler(import_path: str | None) -> Callable[[QueueMessage], None]:
    if import_path is None:
        return _missing_handler
    module_name, separator, attribute = import_path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("Handler must use the form module:attribute")
    candidate = getattr(importlib.import_module(module_name), attribute)
    if not callable(candidate):
        raise TypeError("Configured worker handler is not callable")
    return cast(Callable[[QueueMessage], None], candidate)


def build_parser() -> argparse.ArgumentParser:
    """Build the independently testable worker CLI parser."""
    parser = argparse.ArgumentParser(prog="shotsight-worker")
    parser.add_argument("--database", default=settings.database_url)
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{threading.get_native_id()}")
    parser.add_argument("--handler", help="Analysis callable as module:attribute")
    parser.add_argument("--once", action="store_true", help="Attempt one claim and exit")
    parser.add_argument("--poll-initial", type=float, default=0.1)
    parser.add_argument("--poll-maximum", type=float, default=2.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    parser.add_argument("--stale-seconds", type=float, default=30.0)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate the database and run the worker without importing FastAPI."""
    arguments = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(arguments.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = SQLiteDatabase(_database_path(str(arguments.database)))
    database.migrate()
    queue = SQLiteWorkerQueue(database)
    worker = WorkerProcess(
        queue,
        _load_handler(cast(str | None, arguments.handler)),
        worker_id=str(arguments.worker_id),
        stale_after=timedelta(seconds=float(arguments.stale_seconds)),
        heartbeat_interval=timedelta(seconds=float(arguments.heartbeat_seconds)),
        backoff=PollingBackoff(
            initial_seconds=float(arguments.poll_initial),
            maximum_seconds=float(arguments.poll_maximum),
        ),
    )
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    worker.run(stop_event=stop_event, once=bool(arguments.once))
    return 0

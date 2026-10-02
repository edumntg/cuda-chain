"""`python -m plasmon.coordinator.worker`: the scheduler as its own process.

Use it with `run_worker: false` on the API containers so several API replicas share one
scheduler.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

from . import config
from .app import State
from .engine import Scheduler


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = config.load(Path(argv[0]) if argv else None)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    state = State(cfg)
    scheduler = Scheduler(state.engine, state.session_factory, cfg.tick_interval_s)
    scheduler.start()
    logging.getLogger("plasmon.worker").info("scheduler running, tick %.1fs", cfg.tick_interval_s)
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not stop["flag"]:
        time.sleep(0.5)
    scheduler.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

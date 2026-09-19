"""Seed continuously on this machine: ``python -m api.run_continuously``.

The local stand-in for the Azure timer in function_app.py, so no Functions runtime
or storage account is needed to fill a local dashboard. A sched scheduler re-arms
itself after each run instead of looping on a clock, which gives the same
one-at-a-time cadence the timer does: the next run starts ``interval_seconds``
after the previous one *finishes*, never on top of it.
"""

from __future__ import annotations

import logging
import sched
import time

from api.seed_once import seed_once
from load_config import CORE_URL, INTERVAL_SECONDS

logger = logging.getLogger(__name__)


def run_continuously() -> None:
    """Seed until interrupted. Only returns if the scheduler is emptied."""
    scheduler = sched.scheduler(time.monotonic, time.sleep)

    def tick() -> None:
        seed_once()  # logs its own outcome
        scheduler.enter(INTERVAL_SECONDS, 1, tick)  # re-arm for the next run

    logger.info(
        "seeding continuously -> %s, %ss between runs (Ctrl-C to stop)", CORE_URL, INTERVAL_SECONDS
    )
    scheduler.enter(0, 1, tick)  # first run now
    scheduler.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run_continuously()
    except KeyboardInterrupt:
        pass

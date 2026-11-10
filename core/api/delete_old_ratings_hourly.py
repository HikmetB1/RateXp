"""Delete what config.yaml retention no longer keeps: once now, then once an hour.

The local stand-in for the retention Function (retention_function/function_app.py), which
does the same on Azure; docker-compose.yml runs this under the opt-in `retention` profile:

    python -m api.delete_old_ratings_hourly
"""

from __future__ import annotations

import logging
import time

from modules.write.dispatch_to_adapters import delete_old_ratings_everywhere

INTERVAL_SECONDS = 3600


def delete_old_ratings_hourly() -> None:
    while True:
        delete_old_ratings_everywhere()  # logs each destination that fails
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    delete_old_ratings_hourly()

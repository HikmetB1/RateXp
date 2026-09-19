"""The Azure entry point: a timer that seeds one run per tick.

The Functions runtime only looks for a file of this name at the root it runs from,
so the Dockerfile flattens this folder into that root while the rest of the seeder
keeps its own paths. Cadence comes from the SEED_SCHEDULE app setting - NCRONTAB
with seconds, so "*/30 * * * * *" is every 30s. Timer triggers are singleton, so a
tick never overlaps the run before it.

There is no Functions runtime locally; api/run_continuously.py does the same job.
"""

from __future__ import annotations

import azure.functions as func
from api.seed_once import seed_once

app = func.FunctionApp()


@app.timer_trigger(schedule="%SEED_SCHEDULE%", arg_name="timer", run_on_startup=True)
def seed(timer: func.TimerRequest) -> None:
    seed_once()  # logs its own outcome

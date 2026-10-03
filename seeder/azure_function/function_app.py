"""The Azure entry point: two timers, one seeding a skill run and one a session run.

The Functions runtime only looks for a file of this name at the root it runs from,
so the Dockerfile flattens this folder into that root while the rest of the seeder
keeps its own paths. Both timers share the SEED_SCHEDULE app setting - NCRONTAB
with seconds, so "0 * * * * *" is once a minute - and each is its own function, so
a failing or slow skill run never holds up the session run. Timer triggers are
singleton, so a tick never overlaps the run before it of the same kind.

There is no Functions runtime locally; api/run_continuously.py does the same job.
"""

from __future__ import annotations

import azure.functions as func
from api.seed_once import seed_session_once, seed_skill_once

app = func.FunctionApp()


@app.timer_trigger(schedule="%SEED_SCHEDULE%", arg_name="timer", run_on_startup=True)
def seed_skill(timer: func.TimerRequest) -> None:
    seed_skill_once()  # logs its own outcome


@app.timer_trigger(schedule="%SEED_SCHEDULE%", arg_name="timer", run_on_startup=True)
def seed_session(timer: func.TimerRequest) -> None:
    seed_session_once()  # logs its own outcome

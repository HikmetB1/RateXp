"""The Azure entry point: one timer that deletes what config.yaml retention no longer keeps.

The Functions runtime only looks for a file of this name at the root it runs from, so
Dockerfile.retention flattens this folder into that root while the rest of core keeps its
own paths. The timer fires at the top of every hour (NCRONTAB with seconds) and not on
startup, so a restart or deploy never adds a run. Timer triggers are singleton, so a run
never overlaps the one before it. core's web app never deletes; locally,
api/delete_old_ratings_hourly.py does the same job.
"""

from __future__ import annotations

import azure.functions as func
from modules.write.dispatch_to_adapters import delete_old_ratings_everywhere

app = func.FunctionApp()


@app.timer_trigger(schedule="0 0 * * * *", arg_name="timer", run_on_startup=False)
def delete_old_ratings(timer: func.TimerRequest) -> None:
    delete_old_ratings_everywhere()  # logs each destination that fails

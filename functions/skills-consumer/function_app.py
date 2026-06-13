import logging

import azure.functions as func

import seeder

app = func.FunctionApp()


# Cadence comes from the SEED_SCHEDULE app setting - NCRONTAB with seconds, so
# "*/3 * * * * *" = every 3s. Timer triggers are singleton, so a new run never overlaps
# the previous one: the next tick fires once the current run ends.
@app.timer_trigger(schedule="%SEED_SCHEDULE%", arg_name="timer", run_on_startup=True)
def seed(timer: func.TimerRequest) -> None:
    result = seeder.seed_once()
    if result.get("error"):
        logging.error("seed run failed (%s): %s", result.get("skill"), result["error"])
    else:
        logging.info("seeded skill=%s feedback=%s transcript=%s", result["skill"],
                     result["feedback_sent"], result["transcript_stored"])

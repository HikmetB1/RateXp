"""One seeded run end to end: pick a skill, have the agent use it, submit both records.

This is the entire job. The two entry points only decide *when* it happens -
function_app.py on the Azure timer, api/run_continuously.py in a local loop - so
both of them are one call to here.

Nothing raises out of this module and the outcome is logged before it is returned:
one bad skill, a model outage or a core that is down must never stop the next run.
"""

from __future__ import annotations

import logging
import random
import uuid

from api.record_schemas import SeededRun
from modules.agent.load_skill_pool import load_skill_pool
from modules.agent.open_chat_model import FRAMEWORK, model_name
from modules.agent.run_skill_task import run_skill_task
from modules.submit.post_to_core import post_feedback, post_transcript

logger = logging.getLogger(__name__)


def seed_once() -> dict:
    """Run one random bundled skill, submit it to core, and log how it went.

    Returns ``{"skill", "feedback_sent", "transcript_stored"}``, plus an ``"error"``
    key when the run itself failed before anything could be submitted.
    """
    pool = load_skill_pool()
    if not pool:
        return _logged(
            {
                "skill": None,
                "feedback_sent": False,
                "transcript_stored": False,
                "error": "no skills found under skills/*/SKILL.md",
            }
        )

    skill = random.choice(pool)
    run = SeededRun(
        skill_name=skill["name"],
        agent=f"{FRAMEWORK} {model_name()}",
        session_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
    )
    try:
        rating, messages = run_skill_task(skill)
    except Exception as exc:  # noqa: BLE001 - a failed run must not stop the next one
        return _logged(
            {
                "skill": run.skill_name,
                "feedback_sent": False,
                "transcript_stored": False,
                "error": str(exc),
            }
        )

    if rating is None:
        logger.warning("agent finished without a rating (skill=%s)", run.skill_name)
    # The trajectory ships either way: a run the agent rated badly is exactly the
    # kind worth having on the dashboard.
    return _logged(
        {
            "skill": run.skill_name,
            "feedback_sent": rating is not None and post_feedback(run, rating),
            "transcript_stored": post_transcript(run, messages),
        }
    )


def _logged(result: dict) -> dict:
    """Log one run's outcome and hand the result straight back."""
    if result.get("error"):
        logger.error("seed run failed (%s): %s", result["skill"], result["error"])
    else:
        logger.info(
            "seeded skill=%s feedback=%s transcript=%s",
            result["skill"],
            result["feedback_sent"],
            result["transcript_stored"],
        )
    return result

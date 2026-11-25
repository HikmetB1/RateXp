"""One seeded run end to end: have the agent do a task, rate it, submit both records.

There are two kinds of run, each its own call: ``seed_skill_once`` uses a bundled
skill and rates the skill, ``seed_session_once`` does a plain coding task and rates
the whole session (core stores it with no skill name). Each run also picks a random
comment focus, so over many runs the comments cover every praise and complaint that
core labels (see comment_focuses in config.yaml). The two entry points only
decide *when* they happen - function_app.py on the Azure timers,
api/run_continuously.py in a local loop.

Nothing raises out of this module and the outcome is logged before it is returned:
one bad skill, a model outage or a core that is down must never stop the next run.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Callable

from api.record_schemas import Rating, SeededRun
from load_config import COMMENT_FOCUSES, SESSION_TASKS
from modules.agent.load_skill_pool import load_skill_pool
from modules.agent.open_chat_model import FRAMEWORK, model_name
from modules.agent.run_agent_task import run_session_task, run_skill_task
from modules.submit.post_to_core import post_feedback, post_transcript

logger = logging.getLogger(__name__)


def seed_skill_once() -> dict:
    """Run one random bundled skill, submit it to core, and log how it went.

    Returns ``{"skill", "focus", "feedback_sent", "transcript_stored"}``, plus an
    ``"error"`` key when the run itself failed before anything could be submitted.
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
    return _run_and_submit(
        {"skill": skill["name"]}, skill["name"], lambda focus: run_skill_task(skill, focus)
    )


def seed_session_once() -> dict:
    """Run one random coding task with no skill, submit it to core, and log how it went.

    Returns ``{"session", "focus", "feedback_sent", "transcript_stored"}`` -
    ``"session"`` is the task - plus an ``"error"`` key when the run failed before
    anything was submitted.
    """
    task = random.choice(SESSION_TASKS)
    return _run_and_submit({"session": task}, None, lambda focus: run_session_task(task, focus))


def _run_and_submit(
    label: dict, skill_name: str | None, run_task: Callable[[str], tuple[Rating | None, list]]
) -> dict:
    """Run the task under fresh ids and a random comment focus, then post the rating and
    the trajectory as one run."""
    label = {**label, "focus": random.choice(COMMENT_FOCUSES)}
    run = SeededRun(
        skill_name=skill_name,
        agent=f"{FRAMEWORK} {model_name()}",
        session_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
    )
    try:
        rating, messages = run_task(label["focus"])
    except Exception as exc:  # noqa: BLE001 - a failed run must not stop the next one
        return _logged(
            {**label, "feedback_sent": False, "transcript_stored": False, "error": str(exc)}
        )

    if rating is None:
        logger.warning("agent finished without a rating (%s)", label)
    # The trajectory ships either way: a run the agent rated badly is exactly the
    # kind worth having on the dashboard.
    return _logged(
        {
            **label,
            "feedback_sent": rating is not None and post_feedback(run, rating),
            "transcript_stored": post_transcript(run, messages, rating),
        }
    )


def _logged(result: dict) -> dict:
    """Log one run's outcome and hand the result straight back."""
    if result.get("error"):
        logger.error("seed run failed: %s", result)
    else:
        logger.info("seeded %s", result)
    return result

"""Submit a finished run to core's public API: the rating, then the trajectory.

Both go out as JSON, which core accepts alongside the form bodies the real hook
posts. Neither call raises - core being unreachable must not kill a seeding run -
so each answers only whether the record was accepted.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import TYPE_CHECKING

from load_config import CORE_URL
from modules.submit.build_trajectory import messages_to_atif

if TYPE_CHECKING:
    from api.record_schemas import Rating, SeededRun

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 30


def post_feedback(run: SeededRun, rating: Rating) -> bool:
    """Send the agent's rating to core's /feedback. True if core accepted it."""
    return _post(
        "/feedback", {**run.model_dump(), "score": int(rating.score), "comment": rating.comment}
    )


def post_transcript(run: SeededRun, messages: list) -> bool:
    """Send the run's ATIF trajectory to core's /transcript. True if core accepted it."""
    return _post("/transcript", {**run.model_dump(), "atif": messages_to_atif(run, messages)})


def _post(path: str, payload: dict) -> bool:
    """POST a JSON body to core; True on any 2xx, False on anything else."""
    request = urllib.request.Request(
        f"{CORE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except Exception as exc:  # noqa: BLE001 - HTTPError, URLError and timeouts alike
        logger.warning("POST %s failed: %s", path, exc)
        return False

"""app_be_dynatrace - read back RateXp's own Dynatrace tenant, with DQL.

See read_from_dynatrace.py for the shared DQL read logic.
"""

from __future__ import annotations

from modules.read.adapters.read_from_dynatrace import DynatraceReadAdapter


class AppBeDynatraceReadAdapter(DynatraceReadAdapter):
    def __init__(self, query_url: str, token: str) -> None:
        super().__init__("app_be_dynatrace", query_url, token)

"""Clone dashboard_base.yaml into one destination's dashboard.

dashboard_base.yaml holds only what every dashboard shows: a panel id with its title
and kind. dashboard_for_<destination>.yaml carries every one of those ids and adds how
that destination draws it (a DQL or SQL query), and may add panels of its own, each
with a title and a kind. Panels come back in the order of the destination file, which
is their order on the dashboard.

The YAML files sit beside this file.

core and the app each keep this file (core/modules/dashboard/ and app/ratexp/modules/read/), so
each service builds on its own. Their code must stay the same - change both in one
commit; app/ratexp/tests/test_clone_dashboard_from_base.py fails when they differ.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DASHBOARD_DIR = Path(__file__).resolve().parent
KINDS = ("number", "line", "bar", "table")


def _load(file_name: str) -> dict:
    return yaml.safe_load((DASHBOARD_DIR / file_name).read_text(encoding="utf-8")) or {}


def clone_dashboard(destination: str) -> dict:
    """The dashboard for `destination` ("dynatrace" or "app"): its name, filters and
    download as the destination file gives them (None when absent), and panels as a
    list of {"id", "title", "kind", ...destination fields}.

    Some keys only one service reads - name only core, download only the app - but
    both get every key, so the two copies stay one function.

    Raises ValueError naming the panel when the destination file lacks a base panel, or
    adds one without a title or a kind.
    """
    own_file = f"dashboard_for_{destination}.yaml"
    base_panels = _load("dashboard_base.yaml")["panels"]
    own = _load(own_file)
    own_panels = own.get("panels") or {}
    for panel_id in base_panels:
        if panel_id not in own_panels:
            raise ValueError(f"{own_file} lacks base panel {panel_id!r}")
    panels = []
    for panel_id, fields in own_panels.items():
        panel = {"id": panel_id, **base_panels.get(panel_id, {}), **(fields or {})}
        if not panel.get("title") or panel.get("kind") not in KINDS:
            raise ValueError(
                f"{own_file} panel {panel_id!r} needs a title and a kind in {', '.join(KINDS)}"
            )
        panels.append(panel)
    return {
        "name": own.get("name"),
        "filters": own.get("filters"),
        "download": own.get("download"),
        "panels": panels,
    }

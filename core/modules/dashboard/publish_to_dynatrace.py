"""Publish the RateXp dashboard to a Dynatrace tenant.

Builds a dashboard document from dashboard_for_dynatrace.yaml (see
clone_dashboard_from_base.py) - a header, one tile per panel, a query variable for each
filter (type, skill, agent, eval and each label group), a 30-day default timeframe - and
stores it under a fixed document id: created when absent, its name and content replaced
when present, so running this again after editing the YAML updates the dashboard in
place. The DQL's {list_view_limit} is filled in from the RateXp app's config.yaml, and the
label filters and panels come from core's config.yaml labeling.groups, so publish again
after changing either.

The dashboard shows the records of one environment, which the DQL's {environment} names.
prod (the default) is stored as "ratexp", named as the YAML's name; dev is stored beside it
as "ratexp-dev", named "<name> (dev)".

Env, exported (e.g. ``set -a; . ./.env; set +a``):
- DT_QUERY_URL - the apps host, as in https://xxxxxxxx.apps.dynatrace.com
- DT_DASHBOARD_TOKEN, or else DT_ACCESS_TOKEN - a platform token with the scopes
  document:documents:read and document:documents:write

Run from core/:  uv run python -m modules.dashboard.publish_to_dynatrace [prod|dev]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import yaml
from modules.dashboard.clone_dashboard_from_base import clone_dashboard

DOCUMENT_ID = "ratexp"
ENVIRONMENTS = ("prod", "dev")
# The row limits are the RateXp app's settings, so every dashboard shows as many ratings.
# Publishing runs from a checkout of the repo, so the app's config.yaml is beside core/.
APP_CONFIG = Path(__file__).resolve().parents[3] / "app" / "ratexp" / "config.yaml"
APP_LIMITS = ("list_view_limit", "list_max_limit")
_DOCUMENTS_PATH = "/platform/document/v1/documents"
_VISUALIZATIONS = {
    "number": "singleValue",
    "line": "lineChart",
    "bar": "categoricalBarChart",
    "count": "categoricalBarChart",
    "table": "table",
}
# (w, h) on Dynatrace's 24-column grid: four numbers or three bars to a row, a chart
# or a table across the whole row. A bar tile is sized for about 5 rows; with more,
# Dynatrace decides whether the chart scrolls or squeezes. Count tiles come in pairs.
_TILE_SIZES = {
    "number": (6, 3),
    "line": (24, 8),
    "bar": (8, 8),
    "count": (12, 8),
    "table": (24, 10),
}
# The columns a chart plots - left unset, Dynatrace picks among all the numbers. Every
# line panel returns day, good and bad, every bar panel name and percent_good, every count
# panel name and total (pinned in core/tests/test_clone_dashboard_from_base.py); the key
# shapes are the ones Dynatrace's own dashboards store.
_CHART_SETTINGS = {
    "line": {"fieldMapping": {"timestamp": "day", "leftAxisValues": ["good", "bad"]}},
    "bar": {
        "categoricalBarChartSettings": {"categoryAxis": ["name"], "valueAxis": ["percent_good"]}
    },
    "count": {"categoricalBarChartSettings": {"categoryAxis": ["name"], "valueAxis": ["total"]}},
}
_GRID_COLUMNS = 24
_HEADER_HEIGHT = 2
# The colors of the RateXp Dynatrace app (Dynatrace's design tokens), so both Dynatrace views
# agree: a neutral value blue, a good side green and a bad side red, as text in the table
# and as bars in the count charts.
_NEUTRAL_COLOR = "var(--dt-colors-text-primary-default, #0b56e5)"
_SIDE_TEXT_COLORS = {
    "good": "var(--dt-colors-text-success-default, #007242)",
    "bad": "var(--dt-colors-text-critical-default, #c80026)",
}
_SIDE_BAR_COLORS = {
    "good": "var(--dt-colors-charts-status-ideal-default, #00bb7b)",
    "bad": "var(--dt-colors-charts-status-critical-default, #d40036)",
}
# The feedback table's neutral columns and its score column, as its DQL names them (pinned
# in core/tests/test_publish_to_dynatrace.py); the label columns come from the label groups.
_NEUTRAL_COLUMNS = ("Type", "Name", "Agent", "Model", "Eval", "Comment", "Session")
_SCORE_COLUMN = "Score"


def _variable(key: str, values_dql: str) -> dict:
    return {
        "version": 2,
        "key": key,
        "type": "query",
        "visible": True,
        "editable": True,
        "multiple": False,
        "input": values_dql,
        "defaultValue": "*",
    }


def read_app_limits() -> dict[str, int]:
    """The RateXp app's row limits from its config.yaml, keyed by their DQL placeholder."""
    config = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))
    return {f"{{{key}}}": int(config[key]) for key in APP_LIMITS}


def fill_app_limits(dql: str, limits: dict[str, int]) -> str:
    """`dql` with each {list_view_limit} and {list_max_limit} replaced by its value."""
    for placeholder, value in limits.items():
        dql = dql.replace(placeholder, str(value))
    return dql


def label_column(group: str) -> str:
    """The feedback table's column of a label group: "Labels: Business case". A dashboard
    table cannot put columns under one shared header, so each name carries it."""
    words = group.replace("_", " ")
    return f"Labels: {words[0].upper()}{words[1:]}"


def _rename_label_columns(groups: list[str]) -> str:
    """The DQL that gives each label group's column its label_column name."""
    if not groups:
        return ""
    return " | fieldsRename " + ", ".join(f"`{label_column(g)}`={g}" for g in groups)


def _color_rule(field: str, comparator: str, value: str, color: str) -> dict:
    """A color rule: the text of `field`, or its bar, in `color` where the value compares."""
    return {
        "field": field,
        "comparator": comparator,
        "value": value,
        "colorMode": "custom-color",
        "customColor": {"Default": color},
    }


def _table_color_rules(groups: list[str], sides: dict[str, dict[str, str]]) -> list[dict]:
    """The feedback table's colors: every value of a neutral column and of a label group
    that does not split its values blue; a good score and each when_good value green, a
    bad score and each when_bad value red."""
    neutral = [*_NEUTRAL_COLUMNS, *(label_column(g) for g in groups if g not in sides)]
    rules = [_color_rule(column, "!=", "", _NEUTRAL_COLOR) for column in neutral]
    rules += [
        _color_rule(_SCORE_COLUMN, "=", side, color) for side, color in _SIDE_TEXT_COLORS.items()
    ]
    for group in groups:
        for value, side in sides.get(group, {}).items():
            rules.append(_color_rule(label_column(group), "=", value, _SIDE_TEXT_COLORS[side]))
    return rules


def _bar_color_rules(sides: dict[str, str]) -> list[dict]:
    """A count chart's colors: the bar of each when_good value green, of each when_bad red."""
    return [
        _color_rule("name", "=", value, _SIDE_BAR_COLORS[side]) for value, side in sides.items()
    ]


def name_and_document_id(name: str, environment: str) -> tuple[str, str]:
    """The dashboard's name and document id for `environment`: prod keeps the YAML's name
    and DOCUMENT_ID, another environment gets its own document beside it."""
    if environment == "prod":
        return name, DOCUMENT_ID
    return f"{name} ({environment})", f"{DOCUMENT_ID}-{environment}"


def build_dashboard_document(dashboard: dict, environment: str) -> dict:
    """The dashboard as the Dynatrace document API stores it, showing the records of
    `environment`: tiles and layouts share keys "0", "1", ...; "0" is the header, then one
    data tile per panel, placed left to right and wrapped to the next row when a tile
    would cross the grid's right edge. A table panel's hidden_columns, when the YAML gives
    them, stay out of its table.

    The colors follow the RateXp Dynatrace app: the table's label columns are renamed to
    "Labels: <group>" and colored blue, green or red, and each count chart's bars green
    (praise) or red (complaints)."""
    filters_dql = dashboard["filters"]["dql"].replace("{environment}", environment)
    values = {
        key: dql.replace("{environment}", environment)
        for key, dql in dashboard["filters"]["values"].items()
    }
    limits = read_app_limits()
    groups = dashboard.get("label_groups") or []
    sides = dashboard.get("label_sides") or {}
    tiles = {
        "0": {
            "type": "markdown",
            "title": "",
            "content": (
                f"## {dashboard['name']}\n\nThe type, skill, agent, eval and label pickers and "
                "the time picker apply to every tile; ratings in the last 24h keep their own "
                "window."
            ),
        }
    }
    layouts = {"0": {"x": 0, "y": 0, "w": _GRID_COLUMNS, "h": _HEADER_HEIGHT}}
    x, y, row_height = 0, _HEADER_HEIGHT, 0
    for index, panel in enumerate(dashboard["panels"], start=1):
        width, height = _TILE_SIZES[panel["kind"]]
        if x + width > _GRID_COLUMNS:
            x, y, row_height = 0, y + row_height, 0
        settings = {}
        if panel["kind"] in _CHART_SETTINGS:
            settings["chartSettings"] = _CHART_SETTINGS[panel["kind"]]
        if "hidden_columns" in panel:
            # A column id is the path to its field, so a top-level field is a list of one.
            settings["table"] = {"hiddenColumns": [[c] for c in panel["hidden_columns"]]}
        query = fill_app_limits(panel["dql"].replace("{filters}", filters_dql), limits)
        if panel["kind"] == "table":
            query += _rename_label_columns(groups)
            settings["coloring"] = {"colorRules": _table_color_rules(groups, sides)}
        if panel["kind"] == "count":
            # A count panel counts the values of one label group, which its id ends in.
            group = next((g for g in sides if panel["id"].endswith(f"_by_{g}")), None)
            if group:
                settings["coloring"] = {"colorRules": _bar_color_rules(sides[group])}
        tiles[str(index)] = {
            "type": "data",
            "title": panel["title"],
            "query": query,
            "visualization": _VISUALIZATIONS[panel["kind"]],
            "visualizationSettings": settings,
        }
        layouts[str(index)] = {"x": x, "y": y, "w": width, "h": height}
        x, row_height = x + width, max(row_height, height)
    return {
        "version": 21,
        "variables": [_variable(key, dql) for key, dql in values.items()],
        "tiles": tiles,
        "layouts": layouts,
        "settings": {
            "defaultTimeframe": {"enabled": True, "value": {"from": "now()-30d", "to": "now()"}}
        },
        "annotations": [],
    }


def build_multipart(fields: dict[str, str], document: dict) -> tuple[bytes, str]:
    """A multipart/form-data body: one text part per field, then the document as the
    "content" part. Returns (body, Content-Type header value).

    The content part carries its own Content-Type - the document API refuses a part
    without one - and a filename, which marks it as the file part.
    """
    boundary = uuid.uuid4().hex
    lines: list[str] = []
    for name, value in fields.items():
        lines += [f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", value]
    lines += [
        f"--{boundary}",
        'Content-Disposition: form-data; name="content"; filename="dashboard.json"',
        "Content-Type: application/json",
        "",
        json.dumps(document, ensure_ascii=False),
        f"--{boundary}--",
        "",
    ]
    return "\r\n".join(lines).encode(), f"multipart/form-data; boundary={boundary}"


def _send(method: str, url: str, token: str, body: bytes | None = None, content_type="") -> dict:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode() or "{}")


def publish_dashboard(document: dict, name: str, document_id: str, host: str, token: str) -> str:
    """Create the document `document_id` on `host` named `name`, or replace its name and
    content when it exists. Returns "created" or "updated"."""
    documents = host.rstrip("/") + _DOCUMENTS_PATH
    try:
        version = _send("GET", f"{documents}/{document_id}/metadata", token)["version"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        body, content_type = build_multipart(
            {
                "id": document_id,
                "name": name,
                "type": "dashboard",
                "description": "RateXp ratings and trajectories (ratexp.* log attributes)",
                "isPrivate": "false",
            },
            document,
        )
        _send("POST", documents, token, body, content_type)
        return "created"
    body, content_type = build_multipart({"name": name}, document)
    _send(
        "PATCH",
        f"{documents}/{document_id}?optimistic-locking-version={version}",
        token,
        body,
        content_type,
    )
    return "updated"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Publish the RateXp dashboard to Dynatrace.")
    parser.add_argument("environment", nargs="?", default="prod", choices=ENVIRONMENTS)
    environment = parser.parse_args(argv).environment
    host = os.environ.get("DT_QUERY_URL")
    token = os.environ.get("DT_DASHBOARD_TOKEN") or os.environ.get("DT_ACCESS_TOKEN")
    if not host or not token:
        sys.exit("export DT_QUERY_URL and DT_DASHBOARD_TOKEN (or DT_ACCESS_TOKEN) first")
    dashboard = clone_dashboard("dynatrace")
    name, document_id = name_and_document_id(dashboard["name"], environment)
    document = build_dashboard_document({**dashboard, "name": name}, environment)
    outcome = publish_dashboard(document, name, document_id, host, token)
    print(f"{outcome}: {host.rstrip('/')}/ui/apps/dynatrace.dashboards/dashboard/{document_id}")


if __name__ == "__main__":
    main()

"""Publish the RateXp dashboard to a Dynatrace tenant.

Builds a dashboard document from dashboard_for_dynatrace.yaml (see
clone_dashboard_from_base.py) - a header, one tile per panel, a query variable for each
of the skill, agent and eval filters, a 30-day default timeframe - and stores it under
the fixed document id "ratexp", named as the YAML's name: created when absent, its name
and content replaced when present, so running this again after editing the YAML updates
the dashboard in place.

Env, exported (e.g. ``set -a; . ./.env; set +a``):
- DT_QUERY_URL - the apps host, as in https://xxxxxxxx.apps.dynatrace.com
- DT_DASHBOARD_TOKEN, or else DT_ACCESS_TOKEN - a platform token with the scopes
  document:documents:read and document:documents:write

Run from core/:  uv run python -m modules.dashboard.publish_to_dynatrace
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

from modules.dashboard.clone_dashboard_from_base import clone_dashboard

DOCUMENT_ID = "ratexp"
_DOCUMENTS_PATH = "/platform/document/v1/documents"
_FILTER_KEYS = ("skill", "agent", "eval")
_VISUALIZATIONS = {
    "number": "singleValue",
    "line": "lineChart",
    "bar": "categoricalBarChart",
    "table": "table",
}
# (w, h) on Dynatrace's 24-column grid: four numbers or three bars to a row, a chart
# or a table across the whole row.
_TILE_SIZES = {"number": (6, 3), "line": (24, 8), "bar": (8, 8), "table": (24, 10)}
# The columns a chart plots - left unset, Dynatrace picks among all the numbers. Every
# line panel returns day, good and bad, every bar panel name and percent_good (pinned in
# core/tests/test_clone_dashboard_from_base.py); the key shapes are the ones Dynatrace's
# own dashboards store.
_CHART_SETTINGS = {
    "line": {"fieldMapping": {"timestamp": "day", "leftAxisValues": ["good", "bad"]}},
    "bar": {
        "categoricalBarChartSettings": {"categoryAxis": ["name"], "valueAxis": ["percent_good"]}
    },
}
_GRID_COLUMNS = 24
_HEADER_HEIGHT = 2


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


def build_dashboard_document(dashboard: dict) -> dict:
    """The dashboard as the Dynatrace document API stores it: tiles and layouts share
    keys "0", "1", ...; "0" is the header, then one data tile per panel, placed left to
    right and wrapped to the next row when a tile would cross the grid's right edge. A
    panel's max_result_megabytes, when the YAML gives one, raises its tile's 1 MB default
    result limit."""
    filters = dashboard["filters"]
    tiles = {
        "0": {
            "type": "markdown",
            "title": "",
            "content": (
                f"## {dashboard['name']}\n\nThe skill, agent and eval pickers and the time "
                "picker apply to every tile; ratings in the last 24h keep their own window."
            ),
        }
    }
    layouts = {"0": {"x": 0, "y": 0, "w": _GRID_COLUMNS, "h": _HEADER_HEIGHT}}
    x, y, row_height = 0, _HEADER_HEIGHT, 0
    for index, panel in enumerate(dashboard["panels"], start=1):
        width, height = _TILE_SIZES[panel["kind"]]
        if x + width > _GRID_COLUMNS:
            x, y, row_height = 0, y + row_height, 0
        tile = {
            "type": "data",
            "title": panel["title"],
            "query": panel["dql"].replace("{filters}", filters["dql"]),
            "visualization": _VISUALIZATIONS[panel["kind"]],
            "visualizationSettings": (
                {"chartSettings": _CHART_SETTINGS[panel["kind"]]}
                if panel["kind"] in _CHART_SETTINGS
                else {}
            ),
        }
        if "max_result_megabytes" in panel:
            # Dynatrace's defaults for the rest, in the shape its own tiles store.
            tile["querySettings"] = {
                "maxResultRecords": 1000,
                "defaultScanLimitGbytes": 500,
                "maxResultMegaBytes": panel["max_result_megabytes"],
                "defaultSamplingRatio": 10,
                "enableSampling": False,
            }
        tiles[str(index)] = tile
        layouts[str(index)] = {"x": x, "y": y, "w": width, "h": height}
        x, row_height = x + width, max(row_height, height)
    return {
        "version": 21,
        "variables": [_variable(key, filters["values"][key]) for key in _FILTER_KEYS],
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


def publish_dashboard(document: dict, name: str, host: str, token: str) -> str:
    """Create the "ratexp" document on `host` named `name`, or replace its name and content
    when it exists. Returns "created" or "updated"."""
    documents = host.rstrip("/") + _DOCUMENTS_PATH
    try:
        version = _send("GET", f"{documents}/{DOCUMENT_ID}/metadata", token)["version"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        body, content_type = build_multipart(
            {
                "id": DOCUMENT_ID,
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
        f"{documents}/{DOCUMENT_ID}?optimistic-locking-version={version}",
        token,
        body,
        content_type,
    )
    return "updated"


def main() -> None:
    host = os.environ.get("DT_QUERY_URL")
    token = os.environ.get("DT_DASHBOARD_TOKEN") or os.environ.get("DT_ACCESS_TOKEN")
    if not host or not token:
        sys.exit("export DT_QUERY_URL and DT_DASHBOARD_TOKEN (or DT_ACCESS_TOKEN) first")
    dashboard = clone_dashboard("dynatrace")
    outcome = publish_dashboard(build_dashboard_document(dashboard), dashboard["name"], host, token)
    print(f"{outcome}: {host.rstrip('/')}/ui/apps/dynatrace.dashboards/dashboard/{DOCUMENT_ID}")


if __name__ == "__main__":
    main()

"""The Dynatrace dashboard document, the multipart body that carries it, and the
create-or-update choice. Nothing here reaches a tenant."""

from __future__ import annotations

import email
import email.policy
import io
import json
import urllib.error

import pytest
import yaml
from modules.dashboard import publish_to_dynatrace
from modules.dashboard.clone_dashboard_from_base import clone_dashboard
from modules.dashboard.publish_to_dynatrace import (
    APP_CONFIG,
    DOCUMENT_ID,
    build_dashboard_document,
    build_multipart,
    publish_dashboard,
)

HOST = "https://abc123.apps.dynatrace.com"
DOCUMENTS = f"{HOST}/platform/document/v1/documents"
FILTER_VARIABLES = (
    "$type",
    "$skill",
    "$agent",
    "$eval",
    "$business_case",
    "$language",
    "$task_type",
)


@pytest.fixture
def document() -> dict:
    return build_dashboard_document(clone_dashboard("dynatrace"))


def _data_tiles(document: dict) -> list[dict]:
    return [tile for tile in document["tiles"].values() if tile["type"] == "data"]


def test_the_document_has_a_header_and_one_tile_per_panel_with_matching_layouts(document):
    panels = clone_dashboard("dynatrace")["panels"]
    assert document["version"] == 21
    assert document["annotations"] == []
    assert document["tiles"]["0"]["type"] == "markdown"
    assert "RateXp" in document["tiles"]["0"]["content"]
    assert len(_data_tiles(document)) == len(panels)
    assert set(document["tiles"]) == set(document["layouts"])
    assert [tile["title"] for tile in _data_tiles(document)] == [p["title"] for p in panels]


def test_every_tile_fits_the_24_column_grid(document):
    for layout in document["layouts"].values():
        assert layout["x"] >= 0 and layout["w"] > 0 and layout["h"] > 0
        assert layout["x"] + layout["w"] <= 24
    # Four numbers share the first row under the header, then the line chart wraps.
    numbers = [document["layouts"][key] for key in ("1", "2", "3", "4")]
    assert [n["x"] for n in numbers] == [0, 6, 12, 18]
    assert len({n["y"] for n in numbers}) == 1
    assert document["layouts"]["5"]["x"] == 0
    assert document["layouts"]["5"]["y"] > numbers[0]["y"]


def test_each_kind_gets_its_visualization_and_size(document):
    panels = clone_dashboard("dynatrace")["panels"]
    expected = {"number": "singleValue", "line": "lineChart", "bar": "categoricalBarChart"}
    expected["table"] = "table"
    sizes = {"number": (6, 3), "line": (24, 8), "bar": (8, 8), "table": (24, 10)}
    for index, panel in enumerate(panels, start=1):
        tile, layout = document["tiles"][str(index)], document["layouts"][str(index)]
        assert tile["visualization"] == expected[panel["kind"]]
        assert (layout["w"], layout["h"]) == sizes[panel["kind"]]


def test_charts_name_the_columns_they_plot_and_the_feedback_table_hides_its_request_id(document):
    panels = clone_dashboard("dynatrace")["panels"]
    for index, panel in enumerate(panels, start=1):
        settings = document["tiles"][str(index)]["visualizationSettings"]
        if panel["kind"] == "bar":
            assert settings == {
                "chartSettings": {
                    "categoricalBarChartSettings": {
                        "categoryAxis": ["name"],
                        "valueAxis": ["percent_good"],
                    }
                }
            }
        elif panel["kind"] == "line":
            assert settings == {
                "chartSettings": {
                    "fieldMapping": {"timestamp": "day", "leftAxisValues": ["good", "bad"]}
                }
            }
        elif panel["id"] == "feedback":
            # The Dynatrace app opens a rating's conversation by it; the dashboard cannot.
            assert settings == {"table": {"hiddenColumns": [["request_id"]]}}
        else:
            assert settings == {}, panel["id"]


def test_every_query_has_the_filter_filled_in_and_only_ratings_24h_pins_a_timeframe(document):
    for tile in _data_tiles(document):
        assert "{filters}" not in tile["query"]
        for variable in FILTER_VARIABLES:
            assert variable in tile["query"], tile["title"]
        pinned = tile["title"] == "Ratings in the last 24h"
        assert ("from:now()-24h" in tile["query"]) == pinned, tile["title"]
        assert ("from:" in tile["query"]) == pinned, tile["title"]


def test_the_feedback_tile_shows_as_many_ratings_as_the_ratexp_app(document):
    list_view_limit = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))["list_view_limit"]
    for tile in _data_tiles(document):
        assert "{list_" not in tile["query"], tile["title"]
    (feedback,) = [t for t in _data_tiles(document) if t["title"] == "Feedback"]
    assert f"| sort timestamp desc | limit {list_view_limit} |" in feedback["query"]


def test_the_seven_filter_variables_default_to_all_and_type_narrows_the_rest(document):
    variables = {variable["key"]: variable for variable in document["variables"]}
    # Type first: a variable can only read one defined above it.
    assert tuple(f"${key}" for key in variables) == FILTER_VARIABLES
    for key, variable in variables.items():
        assert variable["type"] == "query" and variable["version"] == 2
        assert variable["multiple"] is False and variable["defaultValue"] == "*"
        assert variable["input"].startswith(f'data record({key}="*")')
        assert ("$type" in variable["input"]) == (key != "type"), key
    assert document["settings"]["defaultTimeframe"]["value"] == {
        "from": "now()-30d",
        "to": "now()",
    }


def _parts(body: bytes, content_type: str) -> dict:
    message = email.message_from_bytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body, policy=email.policy.default
    )
    assert message.is_multipart()
    return {
        part.get_param("name", header="content-disposition"): part for part in message.iter_parts()
    }


def test_the_multipart_body_parses_back_into_its_parts():
    body, content_type = build_multipart({"name": "RateXp", "type": "dashboard"}, {"version": 21})
    parts = _parts(body, content_type)
    assert set(parts) == {"name", "type", "content"}
    assert parts["name"].get_content() == "RateXp"
    assert parts["content"].get_content_type() == "application/json"
    assert parts["content"].get_filename() == "dashboard.json"
    assert json.loads(parts["content"].get_content()) == {"version": 21}


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._body


def _documents_api(monkeypatch, metadata) -> list:
    """A fake tenant: the metadata GET gets `metadata` back (a dict, or an HTTPError to
    raise); every other call succeeds. Returns the requests it saw."""
    seen: list = []

    def _urlopen(request, timeout=None):
        seen.append(request)
        if request.get_method() == "GET":
            if isinstance(metadata, Exception):
                raise metadata
            return _FakeResponse(metadata)
        return _FakeResponse({"id": DOCUMENT_ID, "version": 1})

    monkeypatch.setattr(publish_to_dynatrace.urllib.request, "urlopen", _urlopen)
    return seen


def test_an_absent_document_is_created_with_its_name_type_and_id(monkeypatch):
    not_found = urllib.error.HTTPError(DOCUMENTS, 404, "Not Found", {}, io.BytesIO(b""))
    seen = _documents_api(monkeypatch, not_found)
    assert publish_dashboard({"version": 21}, "Team ratings", HOST, "tok") == "created"
    assert [r.get_method() for r in seen] == ["GET", "POST"]
    assert seen[0].full_url == f"{DOCUMENTS}/{DOCUMENT_ID}/metadata"
    assert seen[1].full_url == DOCUMENTS
    assert seen[1].get_header("Authorization") == "Bearer tok"
    parts = _parts(seen[1].data, seen[1].get_header("Content-type"))
    assert parts["id"].get_content() == DOCUMENT_ID
    assert parts["name"].get_content() == "Team ratings"
    assert parts["type"].get_content() == "dashboard"
    assert parts["isPrivate"].get_content() == "false"
    assert json.loads(parts["content"].get_content()) == {"version": 21}


def test_an_existing_document_gets_its_name_and_content_replaced_at_its_version(monkeypatch):
    seen = _documents_api(monkeypatch, {"id": DOCUMENT_ID, "version": 7})
    assert publish_dashboard({"version": 21}, "Team ratings", HOST + "/", "tok") == "updated"
    assert [r.get_method() for r in seen] == ["GET", "PATCH"]
    assert seen[1].full_url == f"{DOCUMENTS}/{DOCUMENT_ID}?optimistic-locking-version=7"
    parts = _parts(seen[1].data, seen[1].get_header("Content-type"))
    assert set(parts) == {"name", "content"}
    assert parts["name"].get_content() == "Team ratings"
    assert json.loads(parts["content"].get_content()) == {"version": 21}


def test_any_other_refusal_of_the_metadata_is_raised(monkeypatch):
    forbidden = urllib.error.HTTPError(DOCUMENTS, 403, "Forbidden", {}, io.BytesIO(b""))
    _documents_api(monkeypatch, forbidden)
    with pytest.raises(urllib.error.HTTPError):
        publish_dashboard({"version": 21}, "RateXp", HOST, "tok")


def test_main_names_the_dashboard_as_the_yaml_does_and_prints_its_url(monkeypatch, capsys):
    monkeypatch.setenv("DT_QUERY_URL", HOST)
    monkeypatch.setenv("DT_DASHBOARD_TOKEN", "tok")
    seen = _documents_api(monkeypatch, {"version": 1})
    publish_to_dynatrace.main()
    parts = _parts(seen[1].data, seen[1].get_header("Content-type"))
    assert parts["name"].get_content() == clone_dashboard("dynatrace")["name"]
    assert capsys.readouterr().out.strip() == (
        f"updated: {HOST}/ui/apps/dynatrace.dashboards/dashboard/{DOCUMENT_ID}"
    )


def test_main_without_a_host_or_token_stops_with_a_hint(monkeypatch):
    monkeypatch.delenv("DT_QUERY_URL", raising=False)
    monkeypatch.delenv("DT_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("DT_ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="DT_QUERY_URL"):
        publish_to_dynatrace.main()

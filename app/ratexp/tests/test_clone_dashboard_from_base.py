"""clone_dashboard: the base panels merged with one destination file, in that file's order,
and the code of this copy kept the same as core's."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml
from api.record_schemas import PanelFilters
from modules.read import clone_dashboard_from_base
from modules.read.clone_dashboard_from_base import DASHBOARD_DIR, clone_dashboard

BASE = {
    "panels": {
        "good_bad_over_time": {"title": "Good vs bad per day", "kind": "line"},
        "feedback": {"title": "Feedback", "kind": "table"},
    }
}


def _write(tmp_path, monkeypatch, destination: dict, base: dict = BASE) -> None:
    # sort_keys=False: the panel order in the file is the order on the dashboard.
    (tmp_path / "dashboard_base.yaml").write_text(yaml.safe_dump(base, sort_keys=False))
    (tmp_path / "dashboard_for_app.yaml").write_text(yaml.safe_dump(destination, sort_keys=False))
    monkeypatch.setattr(clone_dashboard_from_base, "DASHBOARD_DIR", tmp_path)


def test_base_panels_take_the_destination_fields_in_its_order(tmp_path, monkeypatch):
    _write(
        tmp_path,
        monkeypatch,
        {
            "name": "RateXp",
            "filters": {"sql": "1 = 1"},
            "download": {"sql": "SELECT 1"},
            "panels": {
                "total_ratings": {"title": "Total ratings", "kind": "number", "sql": "SELECT 1"},
                "feedback": {"sql": "SELECT 3"},
                "good_bad_over_time": {"sql": "SELECT 2"},
            },
        },
    )
    dashboard = clone_dashboard("app")
    assert dashboard["name"] == "RateXp"
    assert dashboard["filters"] == {"sql": "1 = 1"}
    assert dashboard["download"] == {"sql": "SELECT 1"}
    assert [p["id"] for p in dashboard["panels"]] == [
        "total_ratings",
        "feedback",
        "good_bad_over_time",
    ]
    assert dashboard["panels"][1] == {
        "id": "feedback",
        "title": "Feedback",
        "kind": "table",
        "sql": "SELECT 3",
    }


def test_a_missing_base_panel_is_named(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"panels": {"good_bad_over_time": {"sql": "SELECT 2"}}})
    with pytest.raises(ValueError, match="feedback"):
        clone_dashboard("app")


@pytest.mark.parametrize(
    "extra",
    [{"title": "Last 24h"}, {"title": "", "kind": "number"}, {"title": "Last 24h", "kind": "pie"}],
)
def test_an_extra_panel_needs_a_title_and_a_known_kind(tmp_path, monkeypatch, extra):
    _write(
        tmp_path,
        monkeypatch,
        {
            "panels": {
                "good_bad_over_time": {"sql": "SELECT 2"},
                "feedback": {"sql": "SELECT 3"},
                "ratings_24h": {**extra, "sql": "SELECT 4"},
            }
        },
    )
    with pytest.raises(ValueError, match="ratings_24h"):
        clone_dashboard("app")


def test_the_real_app_dashboard_gives_every_panel_its_sql():
    if not (DASHBOARD_DIR / "dashboard_for_app.yaml").is_file():
        pytest.skip(f"{DASHBOARD_DIR} holds no dashboard_for_app.yaml yet")
    dashboard = clone_dashboard("app")
    # One dropdown per filter the panel API takes, the time range aside.
    assert dashboard["filters"]["sql"] and set(dashboard["filters"]["values"]) == (
        set(PanelFilters.model_fields) - {"since"}
    )
    assert (
        "{filters}" in dashboard["download"]["sql"] and "%(limit)s" in dashboard["download"]["sql"]
    )
    for panel in dashboard["panels"]:
        assert panel["kind"] in ("number", "line", "bar", "table"), panel["id"]
        assert "{filters}" in panel["sql"], panel["id"]


def _code_but_docstring_and_dashboard_dir(source: str) -> list[str]:
    """Each top-level statement after the module docstring, as an AST dump (comments and
    layout drop out), skipping DASHBOARD_DIR - the two places the copies may differ."""
    return [
        ast.dump(node)
        for node in ast.parse(source).body[1:]
        if not (isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "DASHBOARD_DIR")
    ]


def test_the_code_is_the_same_as_cores_copy():
    core_copy = DASHBOARD_DIR / "clone_dashboard_from_base.py"
    if not core_copy.is_file():
        pytest.skip(f"{DASHBOARD_DIR} holds no core copy of the clone")
    app_copy = Path(clone_dashboard_from_base.__file__)
    assert _code_but_docstring_and_dashboard_dir(
        app_copy.read_text(encoding="utf-8")
    ) == _code_but_docstring_and_dashboard_dir(core_copy.read_text(encoding="utf-8"))

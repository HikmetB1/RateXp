"""The clone rule, and that the shipped dashboard files obey it: every destination carries
every base panel, the app and Dynatrace draw the same panels in the same order, and
each query fits its destination's filter contract."""

from __future__ import annotations

import re

import pytest
from modules.dashboard import clone_dashboard_from_base
from modules.dashboard.clone_dashboard_from_base import clone_dashboard

PANEL_ORDER = [
    "total_ratings",
    "percent_good",
    "ratings_24h",
    "skills_rated",
    "good_bad_over_time",
    "percent_good_by_skill",
    "percent_good_by_agent",
    "percent_good_by_eval",
    "feedback",
]
# The columns each panel's query returns, named the same in SQL and DQL - but the feedback
# table's, which FEEDBACK_COLUMNS names per destination.
PANEL_COLUMNS = {
    "total_ratings": ["value"],
    "percent_good": ["value"],
    "ratings_24h": ["value"],
    "skills_rated": ["value"],
    "good_bad_over_time": ["day", "good", "bad"],
    "percent_good_by_skill": ["name", "total", "good", "bad", "percent_good"],
    "percent_good_by_agent": ["name", "total", "good", "bad", "percent_good"],
    "percent_good_by_eval": ["name", "total", "good", "bad", "percent_good"],
}
FEEDBACK_COLUMNS = {
    # The Query & table view's rows (GET /feedback), their labels and their conversation:
    # the app draws them in that view's Feedback table.
    "app": [
        "created_at",
        "session_id",
        "skill_name",
        "name",
        "agent",
        "eval_name",
        "score",
        "comment",
        "request_id",
        "business_case",
        "language",
        "task_type",
        "atif",
    ],
    # The web app's Feedback table columns but Trajectory, and the stored conversation's
    # request_id the Dynatrace app opens it by.
    "dynatrace": [
        "When",
        "Type",
        "Name",
        "Agent",
        "Model",
        "Labels",
        "Eval",
        "Score",
        "Comment",
        "Session",
        "request_id",
    ],
}
LABELS = {"business_case", "language", "task_type"}
FILTER_KEYS = {"type", "skill", "agent", "eval"} | LABELS
SQL_PARAMS = FILTER_KEYS | {"since"}
# What a rating's type is: a session rating is one that has no skill.
SQL_TYPE = "CASE WHEN skill_name IS NULL THEN 'session' ELSE 'skill' END = %(type)s"
DQL_TYPE = 'matchesValue(if(isNull(ratexp.skill_name), "session", else:"skill"), $type)'


def _write_dashboards(tmp_path, monkeypatch, destination_yaml: str) -> None:
    """Point the clone at a folder holding the real base and a made-up destination."""
    base = clone_dashboard_from_base.DASHBOARD_DIR / "dashboard_base.yaml"
    (tmp_path / "dashboard_base.yaml").write_text(base.read_text(encoding="utf-8"))
    (tmp_path / "dashboard_for_fake.yaml").write_text(destination_yaml)
    monkeypatch.setattr(clone_dashboard_from_base, "DASHBOARD_DIR", tmp_path)


def _by_id(dashboard: dict) -> dict:
    return {panel["id"]: panel for panel in dashboard["panels"]}


@pytest.mark.parametrize("destination", ["dynatrace", "app"])
def test_every_destination_carries_every_base_panel_with_its_title_and_kind(destination):
    panels = _by_id(clone_dashboard(destination))
    assert panels["good_bad_over_time"]["title"] == "Good vs bad per day"
    assert panels["good_bad_over_time"]["kind"] == "line"
    assert panels["feedback"]["title"] == "Feedback"
    assert panels["feedback"]["kind"] == "table"


def test_base_fields_and_destination_fields_merge_into_one_panel():
    panel = _by_id(clone_dashboard("dynatrace"))["good_bad_over_time"]
    assert set(panel) == {"id", "title", "kind", "dql"}
    assert "bin(timestamp, 1d)" in panel["dql"]


def test_a_missing_base_panel_is_refused_by_name(tmp_path, monkeypatch):
    _write_dashboards(
        tmp_path,
        monkeypatch,
        "panels:\n  good_bad_over_time:\n    dql: fetch logs\n",
    )
    with pytest.raises(ValueError, match="feedback"):
        clone_dashboard("fake")


@pytest.mark.parametrize("extra", ["title: Extra", "kind: number", "kind: pie\n    title: Extra"])
def test_an_extra_panel_without_a_title_and_a_known_kind_is_refused(tmp_path, monkeypatch, extra):
    _write_dashboards(
        tmp_path,
        monkeypatch,
        f"panels:\n  good_bad_over_time: {{}}\n  feedback: {{}}\n  extra:\n    {extra}\n",
    )
    with pytest.raises(ValueError, match="'extra'"):
        clone_dashboard("fake")


def test_panels_keep_the_order_of_the_destination_file(tmp_path, monkeypatch):
    _write_dashboards(
        tmp_path,
        monkeypatch,
        "panels:\n  feedback: {}\n  first:\n    title: First\n    kind: number\n"
        "  good_bad_over_time: {}\n",
    )
    assert [p["id"] for p in clone_dashboard("fake")["panels"]] == [
        "feedback",
        "first",
        "good_bad_over_time",
    ]


def test_absent_sections_come_back_as_none(tmp_path, monkeypatch):
    _write_dashboards(
        tmp_path,
        monkeypatch,
        "panels:\n  good_bad_over_time: {}\n  feedback: {}\n",
    )
    fake = clone_dashboard("fake")
    assert fake["name"] is None
    assert fake["filters"] is None
    assert fake["download"] is None


def test_app_and_dynatrace_draw_the_same_panels_in_the_same_order():
    app, dynatrace = clone_dashboard("app"), clone_dashboard("dynatrace")
    assert [p["id"] for p in app["panels"]] == PANEL_ORDER
    assert [p["id"] for p in dynatrace["panels"]] == PANEL_ORDER
    app_panels, dt_panels = _by_id(app), _by_id(dynatrace)
    for panel_id in app_panels:
        assert app_panels[panel_id]["title"] == dt_panels[panel_id]["title"]
        assert app_panels[panel_id]["kind"] == dt_panels[panel_id]["kind"]


def test_every_app_panel_names_its_columns_and_takes_the_shared_filter_once():
    app = clone_dashboard("app")
    for panel in app["panels"]:
        assert panel["sql"].count("{filters}") == 1, panel["id"]
        # Besides the filter fragment a panel may only take limit, the app's list_view_limit.
        assert set(re.findall(r"%\((\w+)\)s", panel["sql"])) <= {"limit"}, panel["id"]
        for column in PANEL_COLUMNS.get(panel["id"], FEEDBACK_COLUMNS["app"]):
            assert re.search(rf"\b{column}\b", panel["sql"]), (panel["id"], column)
    fragment = app["filters"]["sql"]
    assert set(re.findall(r"%\((\w+)\)s", fragment)) == SQL_PARAMS
    assert SQL_TYPE in fragment
    assert "split_part(agent, ' ', 1)" in fragment
    assert "COALESCE(skill_name, '(none)') = %(skill)s" in fragment
    assert "COALESCE(eval_name, '(none)') = %(eval)s" in fragment
    for label in LABELS:
        assert f"COALESCE({label}, '(none)') = %({label})s" in fragment, label


def test_every_rating_panel_reads_the_labels_of_its_conversation():
    # A label sits on the transcript, so a rating panel that read the bare feedback table
    # would have no label column for the shared filter to narrow.
    app = clone_dashboard("app")
    queries = [app["download"]["sql"], *(panel["sql"] for panel in app["panels"])]
    assert not [sql for sql in queries if re.search(r"FROM feedback\b(?!_)", sql)]


def test_the_feedback_panels_show_the_newest_ratings():
    sql = _by_id(clone_dashboard("app"))["feedback"]["sql"]
    dql = _by_id(clone_dashboard("dynatrace"))["feedback"]["dql"]
    # The app caps it with its list_view_limit; Dynatrace cannot read the app's config.
    assert sql.endswith("ORDER BY created_at DESC LIMIT %(limit)s")
    # A rating's conversation is the transcript with its request_id, or none.
    assert "LEFT JOIN transcript t ON t.request_id = f.request_id" in sql
    assert "| sort timestamp desc | limit 10" in dql
    fields = dql.split("| fields ", 1)[1]
    assert re.findall(r"(?:^|, )(\w+)=(?!=)", fields) == FEEDBACK_COLUMNS["dynatrace"]
    assert "request_id=transcript.request_id" in fields


def test_the_bars_list_every_row_worst_first():
    for destination, language in (("app", "sql"), ("dynatrace", "dql")):
        for panel in clone_dashboard(destination)["panels"]:
            if panel["kind"] == "bar":
                query = panel[language]
                assert "limit" not in query.lower(), (destination, panel["id"])
                assert re.search(r"(?i)(order by|sort) percent_good asc, total desc$", query)


def test_the_app_download_and_dropdown_queries_take_only_their_own_parameters():
    app = clone_dashboard("app")
    download = app["download"]["sql"].replace("{filters}", app["filters"]["sql"])
    assert set(re.findall(r"%\((\w+)\)s", download)) == SQL_PARAMS | {"limit"}
    values = app["filters"]["values"]
    assert list(values)[0] == "type" and set(values) == FILTER_KEYS
    assert values["type"] == "SELECT type FROM (VALUES ('skill'), ('session')) AS types (type)"
    for key, sql in values.items():
        assert "{filters}" not in sql
        if key != "type":
            # Each takes the picked type, and only it, to narrow its values to that type's.
            assert set(re.findall(r"%\((\w+)\)s", sql)) == {"type"}, key
            assert sql.startswith("SELECT DISTINCT") and SQL_TYPE in sql, key


def test_every_dynatrace_panel_takes_the_shared_filter_and_only_ratings_24h_pins_a_timeframe():
    dynatrace = clone_dashboard("dynatrace")
    for panel in dynatrace["panels"]:
        assert panel["dql"].count("{filters}") == 1, panel["id"]
        assert ("from:" in panel["dql"]) == (panel["id"] == "ratings_24h"), panel["id"]
        for column in PANEL_COLUMNS.get(panel["id"], FEEDBACK_COLUMNS["dynatrace"]):
            assert re.search(rf"\b{column}\b", panel["dql"]), (panel["id"], column)
    fragment = dynatrace["filters"]["dql"]
    # The labels and the model sit on the transcript record, so the fragment looks them up
    # by request_id before it filters.
    assert fragment.startswith('| lookup [fetch logs | filter ratexp.record_type == "transcript"')
    assert 'sourceField:ratexp.request_id, lookupField:request_id, prefix:"transcript."' in fragment
    for key in FILTER_KEYS:
        assert re.search(rf"\${key}\b", fragment), key
    for label in LABELS:
        assert f'matchesValue(coalesce(transcript.{label}, "(none)"), ${label})' in fragment, label
    assert DQL_TYPE in fragment
    assert 'splitString(ratexp.agent, " ")[0]' in fragment
    values = dynatrace["filters"]["values"]
    assert list(values)[0] == "type" and set(values) == FILTER_KEYS
    assert values["type"] == 'data record(type="*"), record(type="skill"), record(type="session")'
    for key, dql in values.items():
        if key != "type":
            assert dql.startswith(f'data record({key}="*") | append ['), key
            # The published dashboard reruns it when $type changes.
            assert f"| filter {DQL_TYPE}" in dql, key


def test_skills_rated_on_dynatrace_says_it_does_not_apply_to_sessions():
    dql = _by_id(clone_dashboard("dynatrace"))["skills_rated"]["dql"]
    assert dql.endswith(
        '| fieldsAdd value=if($type == "session", "n/a: session", else:toString(value))'
    )


def test_the_dynatrace_download_takes_the_shared_filter_and_returns_the_app_download_columns():
    dql = clone_dashboard("dynatrace")["download"]["dql"]
    sql = clone_dashboard("app")["download"]["sql"]
    assert dql.count("{filters}") == 1
    assert "from:" not in dql
    columns = re.match(r"SELECT (.*?) FROM", sql).group(1).split(", ")
    for column in columns:
        assert re.search(rf"\b{column}=", dql), column


@pytest.mark.parametrize(
    ("destination", "language", "stand_in"),
    [
        ("dynatrace", "dql", r'coalesce\(ratexp\.(?:skill_name|eval_name), "([^"]*)"\)'),
        ("app", "sql", r"COALESCE\((?:skill_name|eval_name), '([^']*)'\)"),
    ],
)
def test_a_missing_skill_or_eval_is_shown_and_matched_as_none_everywhere(
    destination, language, stand_in
):
    dashboard = clone_dashboard(destination)
    queries = [
        dashboard["filters"][language],
        *dashboard["filters"]["values"].values(),
        *(panel[language] for panel in dashboard["panels"]),
    ]
    stand_ins = re.findall(stand_in, " ".join(queries))
    # The filter (2), the skill and eval pickers (2) and the by-eval bar (1).
    assert len(stand_ins) == 5
    assert set(stand_ins) == {"(none)"}


@pytest.mark.parametrize(
    ("destination", "language", "stand_in"),
    [
        (
            "dynatrace",
            "dql",
            r'coalesce\((?:transcript|ratexp)\.(?:business_case|language|task_type), "([^"]*)"\)',
        ),
        ("app", "sql", r"COALESCE\((?:business_case|language|task_type), '([^']*)'\)"),
    ],
)
def test_a_missing_label_is_shown_and_matched_as_none_everywhere(destination, language, stand_in):
    # A rating whose conversation was not stored, or not labeled, has no label to match.
    # The Feedback table only shows labels, a missing one as "—" like the web app's.
    dashboard = clone_dashboard(destination)
    queries = [
        dashboard["filters"][language],
        *dashboard["filters"]["values"].values(),
        *(panel[language] for panel in dashboard["panels"] if panel["id"] != "feedback"),
    ]
    stand_ins = re.findall(stand_in, " ".join(queries))
    # The filter (3) and the three label pickers (3).
    assert len(stand_ins) == 6
    assert set(stand_ins) == {"(none)"}

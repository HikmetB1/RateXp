"""Clone dashboard_base.yaml into one destination's dashboard.

dashboard_base.yaml holds only what every dashboard shows: a panel id with its title
and kind. dashboard_for_<destination>.yaml carries every one of those ids and adds how
that destination draws it (a DQL or SQL query), and may add panels of its own, each
with a title and a kind. Panels come back in the order of the destination file, which
is their order on the dashboard.

Every dashboard filters by each label group in core/config.yaml labeling.groups, which
an admin defines, so the destination file writes the label parts once, as templates
that each group fills - {group} becomes its name, {group_words} its name with spaces:

- labels.values: filters.values gets one entry per group, named as the group.
- labels.<any other key>: wherever {labels.<key>} stands, the filled copies stand, one per
  group in config order, run together, so each template starts with its own separator.
- A panel whose id holds {group}: one copy per group that splits its values into
  when_good and when_bad, in that panel's place.

The YAML files sit beside this file.

core and the app each keep this file (core/modules/dashboard/ and app/ratexp/modules/read/), so
each service builds on its own. Their code must stay the same - change both in one
commit; app/ratexp/tests/test_clone_dashboard_from_base.py fails when they differ.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DASHBOARD_DIR = Path(__file__).resolve().parent
# core/config.yaml, two folders up from the YAML files.
CORE_CONFIG_FILE = DASHBOARD_DIR.parents[1] / "config.yaml"
KINDS = ("number", "line", "bar", "count", "table")


def _load(file_name: str) -> dict:
    return yaml.safe_load((DASHBOARD_DIR / file_name).read_text(encoding="utf-8")) or {}


def read_label_groups() -> dict[str, dict[str, str]]:
    """Each group of core/config.yaml labeling.groups, in its order -> the side of each of
    its values: value -> "good" (when_good) or "bad" (when_bad), for a group that splits
    its values; {} for one that does not. core's load_config.py checks them."""
    config = yaml.safe_load(CORE_CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        name: {
            **dict.fromkeys(group.get("when_good") or [], "good"),
            **dict.fromkeys(group.get("when_bad") or [], "bad"),
        }
        for name, group in config["labeling"]["groups"].items()
    }


def _fill(value, group: str):
    """`value` with {group_words} and {group} replaced in every string, keys too."""
    if isinstance(value, str):
        return value.replace("{group_words}", group.replace("_", " ")).replace("{group}", group)
    if isinstance(value, dict):
        return {_fill(key, group): _fill(item, group) for key, item in value.items()}
    return value


def _join_labels(value, templates: dict[str, str], groups: list[str]):
    """`value` with each {labels.<key>} in its strings replaced by labels.<key> filled for
    every group, run together."""
    if isinstance(value, str):
        for key, template in templates.items():
            joined = "".join(_fill(template, group) for group in groups)
            value = value.replace(f"{{labels.{key}}}", joined)
        return value
    if isinstance(value, dict):
        return {key: _join_labels(item, templates, groups) for key, item in value.items()}
    return value


def clone_dashboard(destination: str) -> dict:
    """The dashboard for `destination` ("dynatrace" or "app"): its name, filters and
    download as the destination file gives them (None when absent), panels as a list of
    {"id", "title", "kind", ...destination fields}, label_groups, the names of the label
    groups, and label_sides, the side of each value of a group that splits its values
    (see read_label_groups), all with the label templates filled in.

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
    label_groups = read_label_groups()
    groups = list(label_groups)
    label_sides = {group: sides for group, sides in label_groups.items() if sides}
    split_groups = list(label_sides)
    templates = dict(own.get("labels") or {})
    values_template = templates.pop("values", None)
    filters = own.get("filters")
    if filters is not None and values_template is not None:
        label_values = {group: _fill(values_template, group) for group in groups}
        filters = {**filters, "values": {**(filters.get("values") or {}), **label_values}}
    panels = []
    for panel_id, fields in own_panels.items():
        panel = {"id": panel_id, **base_panels.get(panel_id, {}), **(fields or {})}
        if not panel.get("title") or panel.get("kind") not in KINDS:
            raise ValueError(
                f"{own_file} panel {panel_id!r} needs a title and a kind in {', '.join(KINDS)}"
            )
        copies = [_fill(panel, group) for group in split_groups]
        panels += copies if "{group}" in panel_id else [panel]
    return {
        "name": own.get("name"),
        "filters": _join_labels(filters, templates, groups),
        "download": _join_labels(own.get("download"), templates, groups),
        "panels": [_join_labels(panel, templates, groups) for panel in panels],
        "label_groups": groups,
        "label_sides": label_sides,
    }

"""The evals in evals/ and the label lists in config.yaml: what an admin may write
there, what stops core at startup, and the root README's table that lists the evals.

Each eval is one file, named for the word users type after /ratexp and laid over the
folder's base.yaml. A broken one has to fail when core starts, because a hook baked
with it would ask a survey whose answers cannot be read back.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from load_config import (
    DEFAULT_SURVEY_EVAL,
    EVALS,
    LABEL_GROUPS,
    Eval,
    LabelGroup,
    load_evals,
    load_label_groups,
)

# The repo root, which holds README.md beside core/.
ROOT = Path(__file__).resolve().parents[2]

WORTH_IT = """\
question: Was {subject} worth it?
good:
  label: Worth it
  description: It saved me time.
bad:
  label: Not worth it
  description: It cost me time.
"""


def _evals_folder(tmp_path, **files):
    """A folder holding one <name>.yaml per keyword argument."""
    for name, text in files.items():
        (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_the_default_eval_core_ships_is_one_of_its_evals():
    assert DEFAULT_SURVEY_EVAL in EVALS


def test_the_readme_lists_every_eval_with_its_question():
    """Its "Available human evals" table repeats evals/: an eval changed without it fails here."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\| `([a-z0-9-]+)`(?: \(default\))? \| (.+?) \|$", text, re.M))
    assert table == {name: survey.question for name, survey in EVALS.items()}
    assert f"| `{DEFAULT_SURVEY_EVAL}` (default) |" in text


def test_an_eval_is_named_after_its_file(tmp_path):
    assert load_evals(_evals_folder(tmp_path, **{"worth-it": WORTH_IT})) == {
        "worth-it": Eval(
            "Was {subject} worth it?",
            "Worth it",
            "It saved me time.",
            "Not worth it",
            "It cost me time.",
        )
    }


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        # YAML reads a bare Yes as true, which is no label at all.
        pytest.param(
            WORTH_IT.replace("label: Worth it", "label: Yes"), "must be text", id="bare-yes"
        ),
        pytest.param(
            WORTH_IT.replace("label: Worth it", "label: Worth it, mostly"),
            "comma",
            id="comma-in-label",
        ),
        pytest.param(
            WORTH_IT.replace("label: Not worth it", "label: Worth it"),
            "different labels",
            id="same-labels",
        ),
        pytest.param(
            WORTH_IT.replace("  description: It cost me time.\n", ""),
            "bad.description",
            id="missing-description",
        ),
        pytest.param(
            WORTH_IT.replace("It saved me time.", "x" * 201), "at most 200", id="too-long"
        ),
        pytest.param("just a sentence\n", "must hold", id="not-a-mapping"),
    ],
)
def test_a_broken_eval_stops_core_at_startup(tmp_path, text, complaint):
    with pytest.raises(RuntimeError, match=re.escape(complaint)):
        load_evals(_evals_folder(tmp_path, **{"worth-it": text}))


def test_a_question_need_not_name_what_is_rated(tmp_path):
    # The wording is the admin's; the picker's consent line names the session or skill.
    text = WORTH_IT.replace("Was {subject} worth it?", "Was it worth it?")
    assert load_evals(_evals_folder(tmp_path, **{"worth-it": text}))["worth-it"].question == (
        "Was it worth it?"
    )


def test_an_eval_name_users_could_not_type_as_one_word_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="lowercase"):
        load_evals(_evals_folder(tmp_path, **{"Worth It": WORTH_IT}))


def test_a_folder_without_an_eval_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="holds no eval"):
        load_evals(tmp_path)


TRUE_FALSE_BASE = """\
good:
  label: "True"
bad:
  label: "False"
"""
# An eval giving only what differs from TRUE_FALSE_BASE.
WORDING_ONLY = """\
question: Was {subject} worth it?
good:
  description: It saved me time.
bad:
  description: It cost me time.
"""


def test_an_eval_takes_what_it_leaves_out_from_the_base(tmp_path):
    folder = _evals_folder(tmp_path, base=TRUE_FALSE_BASE, **{"worth-it": WORDING_ONLY})
    assert load_evals(folder) == {
        "worth-it": Eval(
            "Was {subject} worth it?", "True", "It saved me time.", "False", "It cost me time."
        )
    }


def test_a_value_the_eval_gives_wins_over_the_bases(tmp_path):
    own_label = WORDING_ONLY.replace("good:\n", 'good:\n  label: "Yes"\n')
    folder = _evals_folder(tmp_path, base=TRUE_FALSE_BASE, **{"worth-it": own_label})
    survey = load_evals(folder)["worth-it"]
    assert (survey.good_label, survey.bad_label) == ("Yes", "False")


def test_a_field_neither_the_eval_nor_the_base_gives_stops_core_naming_it(tmp_path):
    no_bad_answer = WORDING_ONLY.split("bad:")[0]
    folder = _evals_folder(tmp_path, base=TRUE_FALSE_BASE, **{"worth-it": no_bad_answer})
    with pytest.raises(RuntimeError, match=r"evals/worth-it\.yaml: bad\.description"):
        load_evals(folder)


def test_the_base_is_never_an_eval_itself(tmp_path):
    folder = _evals_folder(tmp_path, base=TRUE_FALSE_BASE, **{"worth-it": WORDING_ONLY})
    assert list(load_evals(folder)) == ["worth-it"]
    assert "base" not in EVALS


def test_a_base_that_is_not_a_mapping_stops_core_at_startup(tmp_path):
    folder = _evals_folder(tmp_path, base="- True\n", **{"worth-it": WORTH_IT})
    with pytest.raises(RuntimeError, match="base.yaml: must hold the fields every eval shares"):
        load_evals(folder)


def test_a_copy_of_the_shipped_base_with_its_fields_filled_in_is_an_eval(tmp_path):
    # base.yaml doubles as the starting point: uncommenting its fields is a whole eval.
    shipped = (ROOT / "core" / "evals" / "base.yaml").read_text(encoding="utf-8")
    filled = re.sub(r"^( *)# (question|description): ", r"\1\2: ", shipped, flags=re.M)
    folder = _evals_folder(tmp_path, base=shipped, **{"did-it-help": filled})
    survey = load_evals(folder)["did-it-help"]
    assert (survey.good_label, survey.bad_label) == ("True", "False")
    assert survey.question.startswith("Did {subject}")


GOOD_GROUPS = {
    "department": {"means": "The team the work is for.", "values": ["finance", "hr", "other"]},
    "tone": {
        "means": "How the user felt.",
        "when_good": {"happy": "Pleased with the result.", "relieved": None},
        "when_bad": ["annoyed", "lost"],
    },
}


def test_the_groups_core_ships_load_with_the_feedback_theme_split_into_pairs():
    assert list(LABEL_GROUPS) == ["business_case", "language", "task_type", "feedback_theme"]
    theme = LABEL_GROUPS["feedback_theme"]
    assert len(theme.when_good) == len(theme.when_bad) == 11
    assert theme.values["Completion is slow"] == "It took too long or kept me waiting."
    assert LABEL_GROUPS["language"].when_good == ()


def test_good_groups_load_in_their_order_with_descriptions_where_given():
    groups = load_label_groups(GOOD_GROUPS)
    assert list(groups) == ["department", "tone"]
    assert groups["department"] == LabelGroup(
        "The team the work is for.", {"finance": "", "hr": "", "other": ""}, (), ()
    )
    tone = groups["tone"]
    assert tone.values == {
        "happy": "Pleased with the result.",
        "relieved": "",
        "annoyed": "",
        "lost": "",
    }
    assert (tone.when_good, tone.when_bad) == (("happy", "relieved"), ("annoyed", "lost"))


def test_a_split_group_offers_one_side_per_score_and_every_value_without_one():
    tone = load_label_groups(GOOD_GROUPS)["tone"]
    assert tone.values_for(1) == ["happy", "relieved"]
    assert tone.values_for(2) == ["annoyed", "lost"]
    assert tone.values_for(None) == ["happy", "relieved", "annoyed", "lost"]
    assert load_label_groups(GOOD_GROUPS)["department"].values_for(2) == ["finance", "hr", "other"]


def _department(**changes) -> dict:
    return {"department": {**GOOD_GROUPS["department"], **changes}}


@pytest.mark.parametrize(
    ("groups", "complaint"),
    [
        ({}, "must hold 1-8 groups"),
        ({f"group_{n}": GOOD_GROUPS["department"] for n in range(9)}, "must hold 1-8 groups"),
        ({"Department": GOOD_GROUPS["department"]}, "a group name is 1-40 lowercase"),
        ({"skill": GOOD_GROUPS["department"]}, "a group name is 1-40 lowercase"),
        ({"model": GOOD_GROUPS["department"]}, "a group name is 1-40 lowercase"),
        (_department(means=""), "department.means must say"),
        (_department(values=[]), "department.values must be a list"),
        (_department(values=["hr", "hr"]), "'hr' is reserved or listed twice"),
        (_department(values=["(none)"]), r"'\(none\)' is reserved or listed twice"),
        (_department(values=["x" * 41]), "is not a value of 1-40 characters"),
        (_department(values={"hr": 3}), "department.values.hr must be a one-line description"),
        (_department(when_good=["hr"]), "needs means and values, or means, when_good and when_bad"),
        (
            {"tone": {**GOOD_GROUPS["tone"], "when_bad": ["happy"]}},
            r"\['happy'\] on both sides",
        ),
        (_department(values=[f"v{n}" for n in range(31)]), "more than 30 values"),
    ],
)
def test_broken_groups_stop_core_at_startup(groups, complaint):
    with pytest.raises(RuntimeError, match=complaint):
        load_label_groups(groups)


@pytest.mark.parametrize(
    "key",
    [
        "enabled",
        "endpoint_env",
        "deployment",
        "api_version",
        "timeout_seconds",
        "max_input_chars",
        "groups",
    ],
)
def test_every_labeling_key_is_required(tmp_path, key):
    # The config is read once at import, so a copy of core with the key deleted is imported
    # in a fresh interpreter.
    core = Path(__file__).resolve().parents[1]
    shutil.copy(core / "load_config.py", tmp_path)
    shutil.copytree(core / "evals", tmp_path / "evals")
    config = yaml.safe_load((core / "config.yaml").read_text(encoding="utf-8"))
    del config["labeling"][key]
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", "import load_config"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert f"missing required key: labeling.{key!r}" in result.stderr


@pytest.mark.parametrize("name", ["app_be_psql", "custom_psql", "phoenix"])
def test_every_destination_that_can_delete_needs_its_own_retention_switch(tmp_path, name):
    core = Path(__file__).resolve().parents[1]
    shutil.copy(core / "load_config.py", tmp_path)
    shutil.copytree(core / "evals", tmp_path / "evals")
    config = yaml.safe_load((core / "config.yaml").read_text(encoding="utf-8"))
    del config["write_adapters"][name]["retention"]
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", "import load_config"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert f"missing required key: write_adapters.{name}.'retention'" in result.stderr

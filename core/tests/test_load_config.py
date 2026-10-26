"""The evals in evals/ and the label lists in config.yaml: what an admin may write
there, what stops core at startup, and the root README's table that lists the evals.

Each eval is one file, named for the word users type after /ratexp. A broken one
has to fail when core starts, because a hook baked with it would ask a survey
whose answers cannot be read back.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from load_config import DEFAULT_SURVEY_EVAL, EVALS, LABELS, Eval, load_evals, load_labels

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
    """Its "Available evals" table repeats evals/, so changing an eval without it fails here."""
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


GOOD_LABELS = {
    "business_case": ["devops", "other"],
    "language": ["go", "none", "other"],
    "task_type": ["feat", "fix", "other"],
}


def test_the_label_lists_core_ships_hold_every_group():
    assert set(LABELS) == {"business_case", "language", "task_type"}
    assert all(LABELS.values())


def test_good_label_lists_load_in_group_order():
    assert list(load_labels(GOOD_LABELS)) == ["business_case", "language", "task_type"]


@pytest.mark.parametrize(
    ("labels", "complaint"),
    [
        ({**GOOD_LABELS, "framework": ["react"]}, "must hold exactly"),
        ({"business_case": ["devops"], "language": ["go"]}, "must hold exactly"),
        ({**GOOD_LABELS, "language": []}, "labels.language must be a list of distinct words"),
        ({**GOOD_LABELS, "task_type": ["fix", "fix"]}, "labels.task_type must be a list"),
        ({**GOOD_LABELS, "language": "go"}, "labels.language must be a list"),
        ({**GOOD_LABELS, "business_case": ["devops", 3]}, "labels.business_case must be a list"),
    ],
)
def test_broken_label_lists_stop_core_at_startup(labels, complaint):
    # Each group is a column and an attribute, so a group may not be added or dropped here.
    with pytest.raises(RuntimeError, match=complaint):
        load_labels(labels)


@pytest.mark.parametrize(
    "key",
    ["enabled", "endpoint_env", "deployment", "api_version", "timeout_seconds", "max_input_chars"],
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

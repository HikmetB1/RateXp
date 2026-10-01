"""The evals in evals/: what an admin may write there, what stops core at startup,
and the root README's table that lists them.

Each eval is one file, named for the word users type after /ratexp. A broken one
has to fail when core starts, because a hook baked with it would ask a survey
whose answers cannot be read back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from load_config import DEFAULT_SURVEY_EVAL, EVALS, Eval, load_evals

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

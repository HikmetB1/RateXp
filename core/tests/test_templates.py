"""Guards the shipped skill templates: hook copies and SKILL.md frontmatter.

A copied template must work as-is, so each one ships its own hook script (generated
from the canonical script by tools/sync_hooks.py) and declares all five hooks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

CORE = Path(__file__).resolve().parents[1]

# Every SKILL.md we ship. Each sits next to its own copy of the hook script.
SKILLS = (
    CORE / "template" / "skill" / "SKILL.md",
    CORE / "examples" / "example_skill_poem_creator" / "SKILL.md",
)

# The five hook events the flow needs; see core/ratexp-skill.sh.
HOOK_EVENTS = frozenset(
    {"UserPromptExpansion", "PreToolUse", "Stop", "PostToolUse", "PostToolUseFailure"}
)

# Pytest ids: the folder each SKILL.md lives in.
_ids = [p.parent.name for p in SKILLS]


def _frontmatter(path: Path) -> dict:
    """The YAML block between the leading `---` lines of a SKILL.md."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    _, block, _body = text.split("---\n", 2)
    return yaml.safe_load(block)


def test_shipped_hook_copies_are_in_sync():
    """Every shipped copy is its original script with a real URL baked in."""
    proc = subprocess.run(
        [sys.executable, str(CORE / "tools" / "sync_hooks.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("path", SKILLS, ids=_ids)
def test_skill_declares_all_five_hooks(path):
    assert set(_frontmatter(path)["hooks"]) == HOOK_EVENTS


@pytest.mark.parametrize("path", SKILLS, ids=_ids)
def test_skill_hook_matchers_and_timeout(path):
    hooks = _frontmatter(path)["hooks"]
    # PreToolUse fires on both the skill launch and the picker.
    assert hooks["PreToolUse"][0]["matcher"] == "Skill|AskUserQuestion"
    post = hooks["PostToolUse"][0]
    assert post["matcher"] == "AskUserQuestion"
    # The picker answer is posted from this hook, so it gets room to finish.
    assert post["hooks"][0]["timeout"] == 60


@pytest.mark.parametrize("path", SKILLS, ids=_ids)
def test_skill_allows_the_picker_tool(path):
    assert "AskUserQuestion" in _frontmatter(path)["allowed-tools"]


@pytest.mark.parametrize("path", SKILLS, ids=_ids)
def test_skill_has_no_once_flag(path):
    # `once: true` would silence the hook after the first run.
    assert "once:" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", SKILLS, ids=_ids)
def test_every_hook_runs_the_sibling_script(path):
    # Each SKILL.md must name the hook copy sitting beside it.
    (script,) = path.parent.glob("ratexp-*.sh")
    assert script.name == "ratexp-skill.sh", script
    front = _frontmatter(path)
    commands = [
        hook["command"]
        for entries in front["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert len(commands) == len(HOOK_EVENTS)
    for command in commands:
        # The path is written against the install location, ending in the skill folder.
        assert command.endswith(f'/{front["name"]}/{script.name}"')


@pytest.mark.parametrize("path", SKILLS, ids=_ids)
def test_hook_commands_do_not_pin_the_survey_frequency(path):
    """How often to ask comes from config.yaml, baked into the script by sync.

    Setting RATEXP_EVERY in the command would win over that, so a template doing
    it would quietly ignore the deployment's setting - and every skill copied
    from it would too.
    """
    front = _frontmatter(path)
    for entries in front["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                assert "RATEXP_EVERY" not in hook["command"], hook["command"]

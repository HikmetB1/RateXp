"""Runs rating-panel.test.tsx, the tests of the Claude Code rating panel
(plugins/claude-code/hooks/rating-panel.tsx), with Claude Code's own mod test kit.

`claude plugin test` runs the tests found in a plugin's folder, and the plugin folder
ships no tests, so the plugin and the test file are copied into a scratch folder
first. The kit needs no session, sign-in or network; it does need the `claude` CLI,
so the test is skipped where that is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from test_hook import CLAUDE_PLUGIN

CLAUDE = shutil.which("claude")


@pytest.mark.skipif(CLAUDE is None, reason="needs the claude CLI for `claude plugin test`")
def test_the_rating_panel_passes_its_mod_tests(tmp_path):
    plugin = tmp_path / "plugin"
    shutil.copytree(CLAUDE_PLUGIN, plugin)
    shutil.copy(Path(__file__).with_name("rating-panel.test.tsx"), plugin / "hooks")
    done = subprocess.run(
        [CLAUDE, "plugin", "test", str(plugin)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr

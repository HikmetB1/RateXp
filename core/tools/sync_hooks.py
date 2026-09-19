#!/usr/bin/env python3
"""Generate shipped hooks; --check reports copies that need regeneration."""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
HOSTED_URL = "https://ratexp-core.azurewebsites.net"
# Every copy of the hook we ship. A new template or example needs a line here,
# or its script silently keeps the placeholders and posts nowhere.
SHIPPED = (
    CORE / "template/skill/ratexp.sh",
    CORE / "template/plugin/skills/my-skill/ratexp.sh",
    CORE / "examples/example_skill_poem_creator/ratexp.sh",
    CORE / "examples/example_plugin_poem_creator/skills/poem-creator/ratexp.sh",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = (CORE / "config.yaml").read_text(encoding="utf-8")
    # Keep this development helper usable with the Python standard library alone.
    match = re.search(r"^default_survey_every:\s*([1-9][0-9]*)\s*$", config, re.M)
    if not match:
        parser.error("config.yaml must set a positive default_survey_every")
    script = (CORE / "ratexp.sh").read_text(encoding="utf-8")
    for placeholder, value in (
        ("'__RATEXP_URL__'", HOSTED_URL),
        ("'__RATEXP_EVERY__'", match[1]),
    ):
        if placeholder not in script:
            parser.error(f"ratexp.sh is missing {placeholder}")
        script = script.replace(placeholder, shlex.quote(value))

    stale = []
    for path in SHIPPED:
        if path.is_file() and path.read_text(encoding="utf-8") == script:
            continue
        stale.append(path)
        print(f"{'stale' if args.check else 'wrote'}: {path.relative_to(CORE)}")
        if not args.check:
            path.write_text(script, encoding="utf-8")
            path.chmod(0o755)
    if args.check and stale:
        print("Run: python3 core/tools/sync_hooks.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

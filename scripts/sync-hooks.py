#!/usr/bin/env python3
"""Generate shipped hooks; --check reports copies that need regeneration."""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTED_URL = "https://ratexp-core.azurewebsites.net"
SHIPPED = (
    ROOT / "template/ratexp.sh",
    ROOT / "template/plugin/skills/my-skill/ratexp.sh",
    ROOT / "examples/poem-creator/ratexp.sh",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = (ROOT / "core/config.yaml").read_text(encoding="utf-8")
    # Keep this development helper usable with the Python standard library alone.
    match = re.search(r"^default_survey_every:\s*([1-9][0-9]*)\s*$", config, re.M)
    if not match:
        parser.error("core/config.yaml must set a positive default_survey_every")
    script = (ROOT / "core/ratexp.sh").read_text(encoding="utf-8")
    for placeholder, value in (
        ("'__RATEXP_URL__'", HOSTED_URL),
        ("'__RATEXP_EVERY__'", match[1]),
    ):
        if placeholder not in script:
            parser.error(f"core/ratexp.sh is missing {placeholder}")
        script = script.replace(placeholder, shlex.quote(value))

    stale = []
    for path in SHIPPED:
        if path.is_file() and path.read_text(encoding="utf-8") == script:
            continue
        stale.append(path)
        print(f"{'stale' if args.check else 'wrote'}: {path.relative_to(ROOT)}")
        if not args.check:
            path.write_text(script, encoding="utf-8")
            path.chmod(0o755)
    if args.check and stale:
        print("Run: python3 scripts/sync-hooks.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

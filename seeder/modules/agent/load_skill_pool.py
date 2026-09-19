"""Read the bundled skills a run picks from: every skills/*/SKILL.md in the image.

A skill's name is its frontmatter ``name:``, falling back to the folder name, and
its prompt is the body with the frontmatter stripped - the same text a coding agent
would be handed. The pool is read once per process, so dropping a skill folder in
needs a restart, not a code change.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# seeder/skills/, two levels up from this package. Resolved from __file__ so the
# working directory doesn't matter.
_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


@lru_cache(maxsize=1)
def load_skill_pool() -> tuple[dict, ...]:
    """Every bundled skill as ``{"name", "prompt"}``, read once and cached for the process."""
    found = []
    for md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        text = md.read_text(encoding="utf-8")
        name, body = md.parent.name, text
        if text.startswith("---") and (end := text.find("\n---", 3)) != -1:
            match = re.search(r'^name:\s*"?([^"\n]+)"?', text[3:end], re.M)
            name = match.group(1).strip() if match else name
            body = text[end + 4 :].lstrip("\n")
        found.append({"name": name, "prompt": body})
    return tuple(found)

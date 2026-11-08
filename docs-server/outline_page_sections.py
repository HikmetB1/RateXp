"""MkDocs hook: wrap each section of a page in its own box.

A section is everything from one `##` heading up to the next; the text above the first one
(the page title and its intro) is a section too. A title with no intro (core) gets no box of
its own: it opens the box of the first section. theme/ratexp.css draws the boxes.
"""

from __future__ import annotations

import re

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

# The start of each `##` heading in the rendered page.
SECTION_START = re.compile(r"(?=<h2[ >])")
# A section that holds the page title and nothing else.
TITLE_ALONE = re.compile(r"\s*<h1[ >].*?</h1>\s*", re.S)


def on_page_content(html: str, page: Page, config: MkDocsConfig, files: Files) -> str:
    sections = [part for part in SECTION_START.split(html) if part.strip()]
    if len(sections) > 1 and TITLE_ALONE.fullmatch(sections[0]):
        sections[:2] = [sections[0] + sections[1]]
    return "".join(f'<section class="page-section">{part}</section>' for part in sections)

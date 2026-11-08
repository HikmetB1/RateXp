"""MkDocs hook: show a section of another page in place of a link to it.

GitHub cannot show one file inside another, so a page that shares a section writes a short
stand-in for it - the section's heading and a "See" link - between two comments that GitHub
hides. The page that holds the section marks it with two comments too:

    <!-- shared ../README.md destinations -->      in the page that shows the section
    ## Destinations: where core writes the feedback

    See [Destinations](../README.md#destinations-where-core-writes-the-feedback) in the README.
    <!-- /shared -->

    <!-- shared:start destinations -->             in README.md, around the section
    ## Destinations: where core writes the feedback
    ...
    <!-- shared:end destinations -->

On the site the stand-in becomes the section, so the text lives in one file only. The
section's links are written for its own page, so each relative link is rebased onto the page
that shows it, and its headings move so the top one gets the stand-in heading's level. This
hook runs before add_repo_pages.py, which then sends the links that leave the site to GitHub.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

STAND_IN_START = re.compile(r"^<!-- shared (?P<path>\S+) (?P<name>[\w-]+) -->$", re.M)
STAND_IN = re.compile(rf"{STAND_IN_START.pattern}\n(?P<body>.*?)^<!-- /shared -->$", re.M | re.S)
HEADING = re.compile(r"^(#{1,6}) ")
FENCE = re.compile(r"^\s*(```|~~~)")
# A relative link target in markdown `](target)` or HTML `href="target"` / `src="target"`,
# split into its path and its #anchor. Full URLs and root-absolute paths never match.
RELATIVE_LINK = re.compile(r'(\]\(|href="|src=")(?![a-z]+:|/)([^)"#\s]*)(#[^)"\s]*)?')


def read_section(source: Path, name: str, page: Page) -> str:
    """The text between the section's shared:start and shared:end comments in `source`."""
    if not source.is_file():
        raise PluginError(f"{page.file.src_uri}: <!-- shared --> names a missing file: {source}")
    marked = re.search(
        rf"^<!-- shared:start {name} -->$(.*?)^<!-- shared:end {name} -->$",
        source.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    if not marked:
        raise PluginError(
            f"{page.file.src_uri}: {source.name} has no <!-- shared:start {name} --> and "
            f"<!-- shared:end {name} --> lines"
        )
    return marked[1].strip()


def change_prose_lines(text: str, change: Callable[[str], str]) -> str:
    """`text` with `change` applied to each line outside a fenced code block."""
    lines, in_code = [], False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code:
            line = change(line)
        lines.append(line)
    return "".join(lines)


def first_heading_level(text: str) -> int | None:
    for line in text.splitlines():
        if match := HEADING.match(line):
            return len(match[1])
    return None


def fit_section(section: str, source_uri: str, page_uri: str, stand_in: str) -> str:
    """The section with its links rebased from `source_uri` onto `page_uri`, and its headings
    moved so the top one has the level of the stand-in's heading."""
    source_dir, page_dir = posixpath.dirname(source_uri), posixpath.dirname(page_uri) or "."
    top, wanted = first_heading_level(section), first_heading_level(stand_in)
    shift = wanted - top if top and wanted else 0

    def rebase(match: re.Match) -> str:
        path, anchor = match[2], match[3] or ""
        target = posixpath.normpath(posixpath.join(source_dir, path)) if path else source_uri
        return f"{match[1]}{posixpath.relpath(target, page_dir)}{anchor}"

    def fit_line(line: str) -> str:
        if (heading := HEADING.match(line)) and shift:
            level = min(max(len(heading[1]) + shift, 1), 6)
            line = "#" * level + line[len(heading[1]) :]
        return RELATIVE_LINK.sub(rebase, line)

    return change_prose_lines(section, fit_line)


def on_page_markdown(markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str:
    if len(STAND_IN_START.findall(markdown)) != len(STAND_IN.findall(markdown)):
        raise PluginError(f"{page.file.src_uri}: a <!-- shared --> line has no <!-- /shared -->")
    page_dir = posixpath.dirname(page.file.src_uri)

    def show_section(match: re.Match) -> str:
        source_uri = posixpath.normpath(posixpath.join(page_dir, match["path"]))
        section = read_section(Path(page.file.src_dir) / source_uri, match["name"], page)
        return f"\n{fit_section(section, source_uri, page.file.src_uri, match['body'])}\n"

    return STAND_IN.sub(show_section, markdown)

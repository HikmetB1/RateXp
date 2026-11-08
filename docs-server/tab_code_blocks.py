"""MkDocs hook: show the code blocks after a `<!-- tabs -->` line as one box with tabs.

GitHub cannot show tabs, so a page writes each tab as a bold label line ("**Claude Code:**")
and its own code block, and puts `<!-- tabs -->`, which GitHub hides, on the line above the
first label. On the site the labelled blocks become one box: the first block's title bar,
a row of tabs under it, and the code of the open tab. theme/ratexp.css draws the box; the
tabs are radio buttons, so they work without JavaScript, and Material's copy button copies
the open tab only.
"""

from __future__ import annotations

import re

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

MARKER = "<!-- tabs -->"
# One tab as rendered: the bold label line, then pymdownx.highlight's box - its title bar
# (when the block has one) and the code.
TAB = re.compile(
    r"\s*<p><strong>(?P<label>[^<]+):</strong></p>\s*"
    r'<div class="(?P<box_class>[^"]*\bhighlight\b[^"]*)">'
    r'(?P<title><span class="filename">[^<]*</span>)?(?P<code><pre>.*?</pre>)</div>',
    re.S,
)


def make_tabbed_box(tabs: list[re.Match], group: int) -> str:
    """One code box holding every tab; tab 1 is open. Each radio button sits right before its
    label and its code, so the stylesheet can show the open one with `:checked +` alone."""
    parts = [f'<div class="{tabs[0]["box_class"]} code-tabs">', tabs[0]["title"] or ""]
    for number, tab in enumerate(tabs, 1):
        tab_id = f"code-tabs-{group}-{number}"
        checked = " checked" if number == 1 else ""
        parts += [
            f'<input type="radio" name="code-tabs-{group}" id="{tab_id}"{checked}>',
            f'<label for="{tab_id}">{tab["label"]}</label>',
            tab["code"],
        ]
    return "".join([*parts, "</div>"])


def on_page_content(html: str, page: Page, config: MkDocsConfig, files: Files) -> str:
    before, *groups = html.split(MARKER)
    out = [before]
    for group, text in enumerate(groups, 1):
        tabs, end = [], 0
        while match := TAB.match(text, end):
            tabs.append(match)
            end = match.end()
        if len(tabs) < 2:
            raise PluginError(
                f"{page.file.src_uri}: {MARKER} must stand right above two or more code "
                "blocks, each after a bold label line such as **Claude Code:**"
            )
        out += [make_tabbed_box(tabs, group), text[end:]]
    return "".join(out)

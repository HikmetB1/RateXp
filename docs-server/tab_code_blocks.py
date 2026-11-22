"""MkDocs hook: show the blocks after a `<!-- tabs -->` line as one box with tabs.

GitHub cannot show tabs, so a page writes each tab as a bold label line ("**Claude Code:**")
and its own block - a code block, or one paragraph or list - and puts `<!-- tabs -->`, which
GitHub hides, on the line above the first label. On the site the labelled blocks become one
box: the first block's title bar (code only), a row of tabs under it, and the block of the
open tab. theme/ratexp.css draws the box; the tabs are radio buttons, so they work without
JavaScript, and Material's copy button copies the open tab only.
"""

from __future__ import annotations

import re

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

MARKER = "<!-- tabs -->"
# One tab as rendered: the bold label line, then either pymdownx.highlight's box - its title
# bar (when the block has one) and the code - or one paragraph or list, for a tab whose text
# is a click in the Cursor CLI's menu rather than a command.
TAB = re.compile(
    r"\s*<p><strong>(?P<label>[^<]+):</strong></p>\s*"
    r'(?:<div class="(?P<box_class>[^"]*\bhighlight\b[^"]*)">'
    r'(?P<title><span class="filename">[^<]*</span>)?(?P<code><pre>.*?</pre>)</div>'
    r"|(?P<steps><(?:ol|ul)>.*?</(?:ol|ul)>|<p>.*?</p>))",
    re.S,
)


def make_tabbed_box(tabs: list[re.Match], group: int) -> str:
    """One box holding every tab; tab 1 is open. Each radio button sits right before its
    label and its block, so the stylesheet can show the open one with `:checked +` alone."""
    first = tabs[0]
    box_class = first["box_class"] if first["box_class"] else "highlight"
    parts = [f'<div class="{box_class} code-tabs">', first["title"] or ""]
    for number, tab in enumerate(tabs, 1):
        tab_id = f"code-tabs-{group}-{number}"
        checked = " checked" if number == 1 else ""
        body = tab["code"] if tab["code"] else tab["steps"]
        parts += [
            f'<input type="radio" name="code-tabs-{group}" id="{tab_id}"{checked}>',
            f'<label for="{tab_id}">{tab["label"]}</label>',
            body,
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
                "blocks, paragraphs or lists, each after a bold label line such as "
                "**Claude Code:**"
            )
        out += [make_tabbed_box(tabs, group), text[end:]]
    return "".join(out)

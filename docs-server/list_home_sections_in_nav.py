"""MkDocs hook: show Home in the sidebar as a group of its own sections.

Every other page is one link in the sidebar. Home, the long front page, becomes a group like
Guides: an "Intro" link to the top of the page, then one link per ## section, so the links
follow README.md's headings without a list to keep in step.

A page's headings are known only once it is rendered, after on_nav has run. So the swap
happens when the first template is drawn: the 404 page (on_template_context), or else the
first page (on_page_context). Both see the one shared nav, so it happens once.
"""

from __future__ import annotations

from typing import Any

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.nav import Link, Navigation, Section
from mkdocs.structure.pages import Page


def nest_home_sections_in_nav(nav: Navigation) -> None:
    """Replace the Home page's nav entry with a Home group of links to its ## sections."""
    for index, item in enumerate(nav.items):
        if isinstance(item, Page) and item.is_homepage:
            # The page's # title holds its ## headings; skip it, as Material's contents do.
            headings = list(item.toc)
            if headings and headings[0].level == 1:
                headings = headings[0].children
            # "./#anchor" is the Home page from wherever the sidebar is drawn. A heading reads
            # "Title: answer"; the link shows only the title, as short as a page's name.
            links = [Link("Intro", "./")]
            links += [Link(h.title.split(":")[0], f"./{h.url}") for h in headings]
            nav.items[index] = Section(item.title, links)
            return


def on_template_context(context: dict[str, Any], template_name: str, config: MkDocsConfig):
    if context.get("nav") is not None:
        nest_home_sections_in_nav(context["nav"])
    return context


def on_page_context(context: dict[str, Any], page: Page, config: MkDocsConfig, nav: Navigation):
    nest_home_sections_in_nav(nav)
    return context

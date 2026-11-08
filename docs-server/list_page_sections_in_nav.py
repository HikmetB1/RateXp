"""MkDocs hook: show some pages in the sidebar as a group of their own sections.

Every other page is one link in the sidebar. A page that `extra.nest_sections` in mkdocs.yml
names becomes a group like app: a link to the top of the page when mkdocs.yml names one
(Home's "Intro"), then one link per ## section, so the links follow the page's headings
without a list to keep in step.

A page's headings are known only once it is rendered, after on_nav has run. So the swap
happens when the first template is drawn: the 404 page (on_template_context), or else the
first page (on_page_context). Both see the one shared nav, so it happens once.
"""

from __future__ import annotations

from typing import Any

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import Files
from mkdocs.structure.nav import Link, Navigation, Section
from mkdocs.structure.pages import Page


def nested_pages(config: MkDocsConfig) -> dict[str, str | None]:
    """Each page to show as a group, mapped to the name of its top link (None: no top link)."""
    return config.extra.get("nest_sections") or {}


def group_page_sections(page: Page, top_link: str | None) -> Section:
    """The page as a nav group of links to its ## sections, after the top link if any."""
    # The page's # title holds its ## headings; skip it, as Material's contents do.
    headings = list(page.toc)
    if headings and headings[0].level == 1:
        headings = headings[0].children
    # Home's URL is empty; "./" is Home from wherever the sidebar is drawn. A heading reads
    # "Title: answer"; the link shows only the title, as short as a page's name.
    page_url = page.url or "./"
    links = [Link(top_link, page_url)] if top_link else []
    links += [Link(h.title.split(":")[0], f"{page_url}{h.url}") for h in headings]
    group = Section(page.title, links)
    group.parent = page.parent
    for link in links:
        link.parent = group
    return group


def nest_page_sections(items: list, nested: dict[str, str | None]) -> None:
    """Replace each nested page in `items`, at any depth, with the group of its sections."""
    for index, item in enumerate(items):
        if isinstance(item, Section):
            nest_page_sections(item.children, nested)
        elif isinstance(item, Page) and item.file.src_uri in nested:
            items[index] = group_page_sections(item, nested[item.file.src_uri])


def on_nav(nav: Navigation, config: MkDocsConfig, files: Files) -> Navigation:
    missing = set(nested_pages(config)) - {page.file.src_uri for page in nav.pages}
    if missing:
        raise PluginError(f"extra.nest_sections names pages that the nav lacks: {sorted(missing)}")
    return nav


def on_template_context(context: dict[str, Any], template_name: str, config: MkDocsConfig):
    if context.get("nav") is not None:
        nest_page_sections(context["nav"].items, nested_pages(config))
    return context


def on_page_context(context: dict[str, Any], page: Page, config: MkDocsConfig, nav: Navigation):
    nest_page_sections(nav.items, nested_pages(config))
    return context

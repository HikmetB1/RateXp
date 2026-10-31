"""MkDocs hook: build the site from the repo's own markdown, read where it lies.

MkDocs reads pages from docs_dir only, and docs_dir cannot be the repo root above
mkdocs.yml. So this hook adds every page that mkdocs.yml's nav names, plus the images
they show, straight from the repo root under their repo paths - the relative links
written for GitHub then work unchanged. A link to any other repo file or folder goes to
it on GitHub instead.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import TYPE_CHECKING

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page

if TYPE_CHECKING:
    # Importing it loads watchdog, which takes an inotify instance even for a plain
    # `mkdocs build` - and fails the build on a machine already at its inotify limit.
    from mkdocs.livereload import LiveReloadServer

# The repo root, one level up from docs-server/.
REPO_DIR = Path(__file__).resolve().parent.parent
# Files the pages show besides the pages: the README images, and the RateXp app's logo
# and favicon (mkdocs.yml names those two by these paths).
MEDIA_DIR = "assets"
APP_ICONS = ("app/ratexp/FE/public/logo-white.png", "app/ratexp/FE/public/favicon.ico")
# Where a link to a repo file or folder that is not on the site goes, on the main branch.
GITHUB_REPO = "https://github.com/HikmetB1/RateXp"
# A relative link target in markdown `](target)` or HTML `href="target"`. Full URLs,
# mailto:, #anchors and root-absolute paths are not repo paths, so they never match.
RELATIVE_LINK = re.compile(r'(\]\(|href=")(?![a-z]+:|#|/)([^)"#\s]+)')


def list_nav_pages(nav: list) -> list[str]:
    """Every repo page the nav names, in nav order; entries that are URLs are skipped."""
    pages = []
    for item in nav:
        target = next(iter(item.values())) if isinstance(item, dict) else item
        if isinstance(target, list):
            pages += list_nav_pages(target)
        elif "://" not in target:
            pages.append(target)
    return pages


def list_site_files(config: MkDocsConfig) -> list[str]:
    """The repo paths the site is built from: the nav's pages, then the media they show."""
    media = sorted(p.relative_to(REPO_DIR).as_posix() for p in (REPO_DIR / MEDIA_DIR).iterdir())
    return [*list_nav_pages(config.nav), *media, *APP_ICONS]


def on_files(files: Files, config: MkDocsConfig) -> Files:
    for path in list_site_files(config):
        files.append(File(path, str(REPO_DIR), config.site_dir, config.use_directory_urls))
    return files


def on_page_markdown(markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str:
    page_dir = posixpath.dirname(page.file.src_uri)

    def point_at_github(match: re.Match) -> str:
        target = posixpath.normpath(posixpath.join(page_dir, match[2]))
        # A site page or image stays a site link; a path missing from the repo stays too,
        # so MkDocs reports it and the strict build fails on it.
        if files.get_file_from_path(target) or not (REPO_DIR / target).exists():
            return match[0]
        kind = "tree" if (REPO_DIR / target).is_dir() else "blob"
        return f"{match[1]}{GITHUB_REPO}/{kind}/main/{target}"

    return RELATIVE_LINK.sub(point_at_github, markdown)


def on_serve(server: LiveReloadServer, config: MkDocsConfig, builder) -> None:
    # `mkdocs serve` only watches docs_dir; the pages live elsewhere in the repo.
    for path in list_site_files(config):
        server.watch(str(REPO_DIR / path), recursive=False)

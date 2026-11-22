# docs-server

docs-server builds the markdown files of the repo into the RateXp docs site. core serves the
docs site at [/guide/](https://ratexp-core.azurewebsites.net/guide/).

- **No copies:** docs-server holds no copy of a page. The hook `add_repo_pages.py` reads each
  page that the nav in `mkdocs.yml` names, from the location of the page in the repo.
- **URLs:** The URL of a page follows the repo path of the page (`core/README.md` ->
  `/guide/core/`).
- **Links to other files:** A link to a repo file that is not a page goes to that file on
  GitHub.

## Layout: what this folder holds

```text
docs-server/
├── mkdocs.yml                    the settings below
├── include_shared_sections.py    the MkDocs hook that shows a section of another page in place of a link
├── add_repo_pages.py             the MkDocs hook that adds the pages and the images from the repo root
├── outline_page_sections.py      the MkDocs hook that puts each ## section of a page in a box
├── list_page_sections_in_nav.py  the MkDocs hook that shows a page in the sidebar as a group of its ## sections
├── tab_code_blocks.py            the MkDocs hook that shows the code blocks below <!-- tabs --> as tabs
└── theme/                        the stylesheet of the site: the colours of the RateXp app and the boxes
```

## Run locally: start docs-server on your machine

To serve the docs site on <http://127.0.0.1:8002/guide/>, run this command:

```bash
uv sync && uv run mkdocs serve
```

- **Reload:** `mkdocs serve` reloads the site after a change to a page, to `mkdocs.yml` or to
  `theme/`.
- **Hooks:** `mkdocs serve` does not reload a hook. After a change to a hook, stop
  `mkdocs serve` and start `mkdocs serve` again.

core serves its own copy of the docs site at `/guide/`:

- **Under `docker compose up --build -d`:** core serves the copy in the core image, on
  <http://localhost:8000/guide/>. A page change shows there only after you build the image
  again.
- **core without compose:** core serves `docs-server/site/`. To make `docs-server/site/`, run
  `uv run mkdocs build`.

## Config: every key in mkdocs.yml

[`mkdocs.yml`](./mkdocs.yml) holds all settings. The site reads no env and no secrets.

- `site_name`: The name in the header and at the end of each browser tab title.
- `site_url`: The public `/guide/` URL of core. The 404 page loads its styles from the path of
  `site_url`. Thus, the path must end in `/guide/`.
- `repo_url` / `repo_name`: The RateXp repo on GitHub. The top bar shows the GitHub icon as a
  link to the repo, on the left of the light/dark toggle. `ratexp.css` hides the name and the
  stars and forks counts that Material shows next to the icon.
- `docs_dir`: `theme/`, which holds only the stylesheet of the site. The pages come from
  `hooks` (the top of `add_repo_pages.py` tells why).
- `dev_addr`: The address that `mkdocs serve` listens on.
- `hooks`: The hooks in the layout above.
  - **Images:** `add_repo_pages.py` puts an image on the site only when the image is in the
    `assets/` folder of the repo.
  - **Exception:** `add_repo_pages.py` adds the logo and the favicon of the RateXp app from
    `app/ratexp/FE/public/`.
  - **Tabs:** `tab_code_blocks.py` shows two or more blocks as one box with tabs. Write each
    tab as a bold label line, for example `**Claude Code:**`, and then the block of the tab.
    Put `<!-- tabs -->` on the line above the first label line. GitHub does not show
    `<!-- tabs -->`. Thus, GitHub shows each label line and the block below the label line.
  - **Tab blocks:** A tab holds one code block, or one paragraph or list for a step that is a
    click and not a command. All tabs of a box can mix the two.
  - **Tabs in a step:** Indent the tabs to the text of a numbered step. The numbered list then
    continues after the box. Tabs that are not indented end the list, and the next step starts
    again at 1.
  - **Shared sections:** `include_shared_sections.py` shows one section on more than one page,
    and the text of the section stays in one file only. Mark the section in its own page:
    `<!-- shared:start destinations -->` above the heading, and
    `<!-- shared:end destinations -->` below the last line. On each other page, write a
    stand-in: the line `<!-- shared ../README.md destinations -->` (the path from the page to
    the file of the section, and the name of the section), the heading of the section, a
    "See" link to the section, and the line `<!-- /shared -->`. GitHub shows the stand-in. The
    site shows the section in place of the stand-in.
  - **Links and headings:** In the section, the hook changes each relative link so that it
    works from the page that shows the section. The top heading of the section gets the level
    of the heading in the stand-in, and the other headings move by the same number of levels.
  - **Order:** `include_shared_sections.py` must come before `add_repo_pages.py`.
    `add_repo_pages.py` then sends the links in the section that are not pages to GitHub.
  - **Groups in the sidebar:** `list_page_sections_in_nav.py` shows each page in
    `extra.nest_sections` as a group in the sidebar, with one link for each `##` section of the
    page. A link shows the part of the heading before the colon.
- `nav`: The pages, in the order of the sidebar. A markdown file is on the site only when the
  nav names the file.
- `theme`: Material, with the logo, the favicon and the fonts of the RateXp app.
  - **Themes:** The light/dark toggle switches between the two themes of the RateXp app. The
    first theme is Sunburst, because the RateXp app opens on Sunburst. The second theme is
    Midnight.
  - **`features`:** Switches on the copy button on code, the group headings in the sidebar, the
    open subgroups in the sidebar (now: app), the previous and next links, and the back-to-top
    button.
  - **`icon`:** Gives Tip a lightbulb and Note an information icon, and gives the repo link
    the GitHub icon.
- `extra`:
  - **`generator`:** `false` removes the "Made with Material for MkDocs" footer.
    [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) holds the credit and the license of
    Material, and the site shows THIRD_PARTY_NOTICES.md under Legal.
  - **`nest_sections`:** The pages that the sidebar shows as a group of their `##` sections.
    Each page has the name of the link to the top of the page. An empty value gives no link to
    the top of the page.
- `extra_css`: `ratexp.css` in `theme/`, with the colours of the RateXp app for both themes.
- `markdown_extensions`: The GitHub rules that the pages use, and two more features:
  - **Heading anchors:** `toc` with `pymdownx.slugs`.
  - **Lists:** The two `mdx_` extensions. A list can nest by 2 spaces, and a list can follow a
    line of text with no blank line between.
  - **Boxes:** `github-callouts`, for `> [!TIP]` and `> [!NOTE]` boxes.
  - **Diagrams:** `pymdownx.superfences`, for mermaid diagrams.
  - **Code:** `pymdownx.highlight`, for code colours and a title bar that names the language.
- `validation`: A link to a missing page or to a missing `#anchor` gives a warning. Thus, a
  strict build fails on the link.

## Tests: how to run them

```bash
uv sync && uv run mkdocs build --strict
```

- **Missing file:** A nav entry without a file always makes the build fail.
- **Strict mode:** Strict mode also makes the build fail on each warning, for example a link to
  a missing page or to a missing `#anchor`.
- **Tabs:** A `<!-- tabs -->` line without two or more labelled blocks below the line makes
  the build fail.
- **Shared sections:** A `<!-- shared -->` line makes the build fail when the line has no
  `<!-- /shared -->` line below it, when the file is missing, or when the file has no
  `shared:start` and `shared:end` lines with the name of the section.
- **Groups in the sidebar:** A page in `extra.nest_sections` that the nav does not name makes
  the build fail.
- **CI:** CI runs the same build.

## Deploy: how the docs site gets to Azure

The core image contains the docs site. Thus, the docs site deploys with core. See
[how the core image builds the docs site](../CONTRIBUTING.md#repository-layout-what-each-folder-holds)
and [Deploy to Azure](../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live).

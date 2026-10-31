# docs-server

docs-server builds the repo's own markdown into the RateXp docs site, which core serves at
[/guide/](https://ratexp-core.azurewebsites.net/guide/). No page is copied here: the hook
`add_repo_pages.py` reads each page that the nav in `mkdocs.yml` names from its place in the
repo. So a page's URL follows its repo path (`core/README.md` -> `/guide/core/`), and a link to
a repo file that is not a page goes to that file on GitHub.

## Layout: what lives in this folder

```text
docs-server/
├── mkdocs.yml           the settings below
├── add_repo_pages.py    the MkDocs hook: adds the pages and images from the repo root
└── theme/               the site's stylesheet: the RateXp app's colours
```

## Running locally: start it on your machine

This serves the site on <http://127.0.0.1:8002/guide/> and reloads it when you save a page:

```bash
uv sync && uv run mkdocs serve
```

core serves its own copy at `/guide/`:

- **Under `docker compose up --build -d`:** the copy built into core's image, on
  <http://localhost:8000/guide/>. A page edit shows there only after a rebuild.
- **core run on its own:** `docs-server/site/`, once `uv run mkdocs build` has made it.

## Config: every key in mkdocs.yml

[`mkdocs.yml`](./mkdocs.yml) holds every setting; the site reads no env and no secrets:

- `site_name`: the name in the header and at the end of every browser tab title
- `site_url`: core's public `/guide/` URL. The 404 page loads its styles from this URL's path,
  so the path must end in `/guide/`
- `docs_dir`: `theme/`, the site's stylesheet only; the pages come from `hooks` (the top of
  `add_repo_pages.py` says why)
- `dev_addr`: where `mkdocs serve` listens
- `hooks`: `add_repo_pages.py`. It puts an image on the site only when the image is in the
  repo's `assets/` folder. The exception: the RateXp app's logo and favicon, which it adds from
  `app/ratexp/FE/public/`
- `nav`: the pages, in the order of the one sidebar. A markdown file is on the site only once
  the nav names it
- `theme`: Material, with the RateXp app's logo, favicon and fonts. Its light/dark toggle is
  the app's two themes, Sunburst first, as the app opens on it, then Midnight
- `extra_css`: `ratexp.css` in `theme/`, the app's colours for both themes
- `markdown_extensions`: GitHub's rules, which the pages are written for: heading anchors
  (`toc` with `pymdownx.slugs`), and lists that nest by 2 spaces or follow a line of text
  without a blank line (the two `mdx_` extensions). Also mermaid diagrams and code colours
- `validation`: makes a link to a missing page or `#anchor` a warning, so a strict build fails
  on it

## Tests: how to run them

```bash
uv sync && uv run mkdocs build --strict
```

A nav entry with no file always fails the build; strict mode also fails it on any warning, such as
a link to a missing page or `#anchor`. CI runs the same build.

## Deploy: how it gets to Azure

The site ships inside core's image, so it deploys with core - see
[how core's image builds it](../CONTRIBUTING.md#repository-layout-what-each-folder-holds) and
[Deploy to Azure](../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live).

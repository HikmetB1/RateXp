# Third-Party Notices

RateXp builds on the third-party software listed below. Projects that state how
they like to be cited are cited that way; the rest are listed with their source,
plus a note only where one matters.

## Citations according to `CITATION.cff` if available

**FastAPI**:

> Ramírez, S. *FastAPI* [Software]. https://github.com/fastapi/fastapi — https://fastapi.tiangolo.com

**LangChain**:

> Chase, H. (2022). *LangChain* [Software]. https://github.com/langchain-ai/langchain

**spaCy** (journal article):

> Honnibal, M., Montani, I., Van Landeghem, S., & Boyd, A. (2020). *spaCy: Industrial-strength Natural Language Processing in Python*. Zenodo. https://doi.org/10.5281/zenodo.1212303
>
> *Note:* spaCy itself is MIT, but downloaded language **models** may carry different licenses (e.g. CC-BY-SA, GPL). Check the license of any model you ship.

**Microsoft Presidio** (presidio-analyzer + presidio-anonymizer):

> Mendels, O., Peled, C., Vaisman Levy, N., Hart, S., Rosenthal, T., Lahiani, L., et al. (2018). *Microsoft Presidio: Context aware, pluggable and customizable PII anonymization service for text and images*. Microsoft. https://microsoft.github.io/presidio

**pytest** (replace *x.y* with the version you use):

> Krekel, H., Oliveira, B., Pfannschmidt, R., Bruynooghe, F., Laugher, B., & Bruhin, F. *pytest x.y* [Software]. https://github.com/pytest-dev/pytest

## Other components

- FastAPI — https://github.com/fastapi/fastapi
- Uvicorn — https://github.com/encode/uvicorn
- HTTPX — https://github.com/encode/httpx
- MCP Python SDK (includes FastMCP) — https://github.com/modelcontextprotocol/python-sdk
- PostgreSQL — https://www.postgresql.org/
- Python (CPython) — https://www.python.org/
- psycopg / psycopg-pool — https://www.psycopg.org/
  *Note:* LGPL-3.0-only (weak copyleft). Used unmodified as a runtime library, which LGPL permits; if you modify psycopg itself, LGPL applies to those changes.
- python-multipart — https://github.com/Kludex/python-multipart
- PyYAML — https://pyyaml.org/
- React / react-dom — https://react.dev/
- Vite / @vitejs/plugin-react — https://vitejs.dev/
- react-markdown — https://github.com/remarkjs/react-markdown
- remark-gfm — https://github.com/remarkjs/remark-gfm
- LangGraph — https://github.com/langchain-ai/langgraph
- langchain-openai — https://github.com/langchain-ai/langchain
- python-dotenv — https://github.com/theskumar/python-dotenv
- requests — https://requests.readthedocs.io/
  *Note:* Apache-2.0. Its NOTICE must travel with any redistribution: `Requests, Copyright 2019 Kenneth Reitz`.
- langdetect — https://github.com/Mimino666/langdetect (Python port of Nakatani Shuyo's language-detection library)
- setuptools — https://github.com/pypa/setuptools
- Ruff — https://docs.astral.sh/ruff/
- uv — https://docs.astral.sh/uv/
- Docker (Engine) — https://github.com/moby/moby
- Terraform — https://www.terraform.io/
  *Note:* BUSL-1.1 (source-available). Deploy-time tool only, never bundled into a RateXp artifact. Its providers `azurerm` and `random` are MPL-2.0.
- Azure Functions (Python library + runtime) — https://github.com/Azure/azure-functions-python-library
- azure-identity / azure-ai-textanalytics — https://github.com/Azure/azure-sdk-for-python
- Microsoft Entra ID — https://www.microsoft.com/security/business/identity-access/microsoft-entra-id

## Skills & data format

- **handoff, to-issues, to-prd skills** — MIT © 2026 Matt Pocock. https://github.com/mattpocock/skills — see [ATTRIBUTION.md](./functions/skills-consumer/skills/ATTRIBUTION.md).
- **ATIF — Agent Trajectory Interchange Format (Harbor)** — the JSON shape RateXp uses to store transcripts. If you have the canonical upstream reference, cite it in the same format above.

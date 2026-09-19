"""The bundled skill pool: frontmatter parsing and what ships in the image."""

from __future__ import annotations

from modules.agent import load_skill_pool as pool_module
from modules.agent.load_skill_pool import load_skill_pool


def test_loads_the_bundled_skills():
    pool = load_skill_pool()
    assert pool, "the image ships with skills/*/SKILL.md"
    assert all(s["name"] and s["prompt"] for s in pool)


def test_name_comes_from_frontmatter_and_body_drops_it(tmp_path, monkeypatch):
    skill = tmp_path / "folder-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        '---\nname: "from-frontmatter"\ndescription: ignored\n---\n\nDo the thing.\n'
    )
    monkeypatch.setattr(pool_module, "_SKILLS_DIR", tmp_path)
    load_skill_pool.cache_clear()

    assert load_skill_pool() == ({"name": "from-frontmatter", "prompt": "Do the thing.\n"},)
    load_skill_pool.cache_clear()


def test_name_falls_back_to_the_folder_when_there_is_no_frontmatter(tmp_path, monkeypatch):
    skill = tmp_path / "folder-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text("Just a body.\n")
    monkeypatch.setattr(pool_module, "_SKILLS_DIR", tmp_path)
    load_skill_pool.cache_clear()

    assert load_skill_pool() == ({"name": "folder-name", "prompt": "Just a body.\n"},)
    load_skill_pool.cache_clear()


def test_pool_is_empty_when_there_are_no_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_module, "_SKILLS_DIR", tmp_path)
    load_skill_pool.cache_clear()

    assert load_skill_pool() == ()
    load_skill_pool.cache_clear()

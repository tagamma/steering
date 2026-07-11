from pathlib import Path

from steering.generators.config import Config
from steering.generators.generator import RuleLoader
from steering.generators.skills import sync_skills, validate_skill_layouts


def _write_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}.\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def _config(root: Path, vendors: list[str] | None = None) -> Config:
    return Config(
        {
            "version": 1.0,
            "vendor_files": {
                "cursor": ".cursor/rules",
                "claude": "CLAUDE.md",
            },
            "default_vendors": vendors or ["codex"],
            "skills_glob": ".agents/skills/*/SKILL.md",
            "skills": {"vendor_destinations": {"claude": ".claude/skills"}},
        },
        root / "steering.yaml",
    )


def test_codex_accepts_regular_skill_manifest(tmp_path: Path) -> None:
    _write_skill(tmp_path / ".agents/skills/agd", "agd")

    skills = RuleLoader(_config(tmp_path), tmp_path).load_skills()

    assert [skill.name for skill in skills] == ["agd"]
    assert validate_skill_layouts(skills, ["codex"]) == []


def test_codex_accepts_symlinked_skill_directory(tmp_path: Path) -> None:
    source = tmp_path / "sources/agd"
    _write_skill(source, "agd")
    installed = tmp_path / ".agents/skills/agd"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(source, target_is_directory=True)

    skills = RuleLoader(_config(tmp_path), tmp_path).load_skills()

    assert [skill.name for skill in skills] == ["agd"]
    assert not skills[0].path.is_symlink()
    assert validate_skill_layouts(skills, ["codex"]) == []


def test_codex_rejects_symlinked_skill_manifest(tmp_path: Path) -> None:
    source = tmp_path / "sources/agd"
    _write_skill(source, "agd")
    installed = tmp_path / ".agents/skills/agd"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").symlink_to(source / "SKILL.md")

    skills = RuleLoader(_config(tmp_path), tmp_path).load_skills()
    errors = validate_skill_layouts(skills, ["codex"])

    assert len(errors) == 1
    assert "symlinked SKILL.md" in errors[0]
    assert validate_skill_layouts(skills, ["claude"]) == []


def test_skill_sync_creates_directory_symlink(tmp_path: Path) -> None:
    source = tmp_path / ".agents/skills/agd"
    _write_skill(source, "agd")
    config = _config(tmp_path, ["claude"])

    files = sync_skills(config, tmp_path, ["claude"])
    installed = tmp_path / ".claude/skills/agd"

    assert files[".claude/skills/agd"].startswith("SYMLINK->")
    assert installed.is_symlink()
    assert (installed / "SKILL.md").is_file()
    assert not (installed / "SKILL.md").is_symlink()

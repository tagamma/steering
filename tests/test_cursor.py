"""Tests for the Cursor adapter's @-reference embeds.

Ground truth (canary probes against Cursor CLI 2026.09.26, 2026-10-03): Cursor
loads root and nested AGENTS.md natively but expands @refs nowhere, so the
adapter must embed referenced files and must not repeat AGENTS.md bodies.
"""

from pathlib import Path

from steering.generators.adapters.cursor import CursorAdapter
from steering.generators.discovery import Discovery
from steering.generators.models import Rule, RuleSet


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rule(path: Path, type_: str, content: str, **frontmatter) -> Rule:
    _write(path, content)
    return Rule(name=path.stem, type=type_, path=path, frontmatter=frontmatter, content=content)


def _generate(root: Path, ruleset: RuleSet) -> dict:
    return CursorAdapter().generate(
        ruleset, root, root, dry_run=False, discovery=Discovery(root, "filesystem", [])
    )


def test_nested_agents_refs_embedded_without_body(tmp_path: Path):
    _write(tmp_path / "nix/REF.md", "referenced content")
    nested = _rule(tmp_path / "nix/AGENTS.md", "agents", "NESTED BODY\n\n@REF.md\n")
    ruleset = RuleSet(auto=[], contextual=[], agents=[nested], skills=[])

    files = _generate(tmp_path, ruleset)

    wrapper = (tmp_path / ".cursor/rules/agents-nix.mdc").read_text(encoding="utf-8")
    assert ".cursor/rules/agents-nix.mdc" in files
    assert "globs: nix/**" in wrapper
    assert "referenced content" in wrapper
    # Cursor already loads the nested AGENTS.md itself; repeating it costs twice.
    assert "NESTED BODY" not in wrapper


def test_nested_agents_without_refs_writes_nothing(tmp_path: Path):
    nested = _rule(tmp_path / "nix/AGENTS.md", "agents", "just prose, no refs\n")
    ruleset = RuleSet(auto=[], contextual=[], agents=[nested], skills=[])

    files = _generate(tmp_path, ruleset)

    assert not any(name.startswith(".cursor/rules/agents-") for name in files)


def test_root_agents_refs_embedded_but_symlinked_rules_skipped(tmp_path: Path):
    _write(tmp_path / "README.md", "readme content")
    auto = _rule(
        tmp_path / ".agents/auto-rules/a.mdc", "auto", "auto body",
        alwaysApply=True, globs=[],
    )
    root = _rule(
        tmp_path / "AGENTS.md", "agents",
        "@README.md\n@.agents/auto-rules/a.mdc\n",
    )
    ruleset = RuleSet(auto=[auto], contextual=[], agents=[root], skills=[])

    files = _generate(tmp_path, ruleset)

    # README is embedded (Cursor won't expand the @ref)...
    assert ".cursor/rules/ref-README.mdc" in files
    assert "readme content" in files[".cursor/rules/ref-README.mdc"]
    # ...the auto-rule is already a symlink, so it is not embedded a second time.
    assert ".cursor/rules/auto-a.mdc" in files
    assert not any("auto-rules-a" in name for name in files)

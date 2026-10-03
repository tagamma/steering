"""Tests for the 'root AGENTS.md must @-reference every auto-rule' check."""

from pathlib import Path

from steering.generators.models import Rule, RuleSet
from steering.generators.references import validate_auto_rule_wiring


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rule(path: Path, type_: str, content: str) -> Rule:
    _write(path, content)
    return Rule(name=path.stem, type=type_, path=path, frontmatter={}, content=content)


def test_wired_auto_rule_passes(tmp_path: Path):
    auto = _rule(tmp_path / ".agents/auto-rules/a.mdc", "auto", "be declarative")
    root = _rule(tmp_path / "AGENTS.md", "agents", "- @.agents/auto-rules/a.mdc\n")
    ruleset = RuleSet(auto=[auto], contextual=[], agents=[root], skills=[])

    assert validate_auto_rule_wiring(ruleset, tmp_path) == []


def test_unwired_auto_rule_is_reported(tmp_path: Path):
    auto = _rule(tmp_path / ".agents/auto-rules/a.mdc", "auto", "be declarative")
    root = _rule(tmp_path / "AGENTS.md", "agents", "# root\n\n@README.md\n")
    ruleset = RuleSet(auto=[auto], contextual=[], agents=[root], skills=[])

    errors = validate_auto_rule_wiring(ruleset, tmp_path)

    assert len(errors) == 1
    assert ".agents/auto-rules/a.mdc" in errors[0]
    assert "AGENTS.md" in errors[0]


def test_missing_root_agents_is_reported(tmp_path: Path):
    auto = _rule(tmp_path / ".agents/auto-rules/a.mdc", "auto", "be declarative")
    # A nested AGENTS.md referencing the rule doesn't count: only the root one
    # is loaded at session start.
    nested = _rule(tmp_path / "nix/AGENTS.md", "agents", "@../.agents/auto-rules/a.mdc\n")
    ruleset = RuleSet(auto=[auto], contextual=[], agents=[nested], skills=[])

    errors = validate_auto_rule_wiring(ruleset, tmp_path)

    assert len(errors) == 1
    assert "no root AGENTS.md" in errors[0]


def test_no_auto_rules_needs_no_wiring(tmp_path: Path):
    ruleset = RuleSet(auto=[], contextual=[], agents=[], skills=[])
    assert validate_auto_rule_wiring(ruleset, tmp_path) == []

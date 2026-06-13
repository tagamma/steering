"""Tests for always-on context budget computation."""

from pathlib import Path

from steering.generators.models import Rule, RuleSet
from steering.generators.budget import compute_always_context


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _auto_rule(path: Path, content: str) -> Rule:
    return Rule(
        name=path.stem,
        type="auto",
        path=path,
        frontmatter={"alwaysApply": True, "globs": ["**/*"]},
        content=content,
    )


def test_budget_counts_root_claude_md_and_auto_rules(tmp_path: Path):
    root = tmp_path
    rule_path = root / ".agents" / "auto-rules" / "a.mdc"
    _write(rule_path, "auto rule body")
    rule = _auto_rule(rule_path, "auto rule body")

    ruleset = RuleSet(auto=[rule], contextual=[], agents=[], skills=[])
    result = compute_always_context(ruleset, root, root)

    # Root CLAUDE.md is always counted; the one auto-rule is counted once.
    assert result.root_claude_md_bytes > 0
    assert rule_path in result.files
    assert result.total_bytes == result.root_claude_md_bytes + len(
        b"auto rule body"
    )


def test_budget_follows_transitive_at_references(tmp_path: Path):
    root = tmp_path
    # Root AGENTS.md @-references README.md, which @-references DEEP.md.
    _write(root / "AGENTS.md", "@README.md")
    _write(root / "README.md", "@DEEP.md")
    _write(root / "DEEP.md", "leaf")

    ruleset = RuleSet(auto=[], contextual=[], agents=[], skills=[])
    result = compute_always_context(ruleset, root, root)

    counted = {p.name for p in result.files}
    assert {"AGENTS.md", "README.md", "DEEP.md"} <= counted


def test_budget_does_not_double_count_cycles(tmp_path: Path):
    root = tmp_path
    # A references B references A: each file counted exactly once.
    _write(root / "AGENTS.md", "@B.md")
    _write(root / "B.md", "@AGENTS.md")

    ruleset = RuleSet(auto=[], contextual=[], agents=[], skills=[])
    result = compute_always_context(ruleset, root, root)

    names = [p.name for p in result.files]
    assert names.count("AGENTS.md") == 1
    assert names.count("B.md") == 1


def test_budget_ignores_contextual_and_nested_agents(tmp_path: Path):
    root = tmp_path
    # Contextual rules and nested AGENTS files are only listed by path in the
    # root CLAUDE.md, not @-embedded, so they don't add to the always-on size.
    ctx_path = root / ".agents" / "contextual-rules" / "c.mdc"
    _write(ctx_path, "@SHOULD-NOT-BE-COUNTED.md")
    ctx = Rule(
        name="c",
        type="contextual",
        path=ctx_path,
        frontmatter={"globs": [], "alwaysApply": False},
        content="@SHOULD-NOT-BE-COUNTED.md",
    )

    ruleset = RuleSet(auto=[], contextual=[ctx], agents=[], skills=[])
    result = compute_always_context(ruleset, root, root)

    assert all("SHOULD-NOT-BE-COUNTED" not in p.name for p in result.files)


def test_total_kb_property(tmp_path: Path):
    root = tmp_path
    ruleset = RuleSet(auto=[], contextual=[], agents=[], skills=[])
    result = compute_always_context(ruleset, root, root)
    assert result.total_kb == result.total_bytes / 1024

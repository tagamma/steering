"""Tests for @-reference and markdown-link extraction and resolution."""

from pathlib import Path

from steering.generators.models import Rule, RuleSet, Skill
from steering.generators.references import (
    extract_references,
    resolves,
    strip_code_blocks,
    validate_references,
)


def _targets(content: str, kind: str | None = None) -> set[str]:
    refs = extract_references(content)
    return {r.target for r in refs if kind is None or r.kind == kind}


# --- extractor: emails / user@host are never references ---------------------


def test_emails_are_not_references():
    assert _targets("Contact root@weaver.lan for help") == set()
    assert _targets("ping tagamma@weaver.lan and a.b@host.com now") == set()


def test_decorators_and_org_tags_are_not_references():
    # Bare words (no '/', no extension) are prose, not paths.
    assert _targets("use @property and @dataclass in python") == set()
    assert _targets("tasks tagged @high/@medium/@low energy") == set()
    assert _targets("estimates (@quick/@short/@long)") == set()


# --- extractor: real @ references -------------------------------------------


def test_basic_at_reference():
    assert _targets("See @AGENTS.md for details.") == {"AGENTS.md"}


def test_at_reference_at_string_start():
    assert _targets("@README.md") == {"README.md"}


def test_trailing_punctuation_stripped_extension_kept():
    # Period after the extension is sentence punctuation; '.md' stays.
    assert _targets("Read @AGENTS.md.") == {"AGENTS.md"}
    assert _targets("see @README.md, then @docs/STRUCTURE.md.") == {
        "README.md",
        "docs/STRUCTURE.md",
    }
    assert _targets("config (@flake.nix) here") == {"flake.nix"}


def test_bare_single_word_dir_ref_treated_as_prose():
    # '@schema/' normalizes to the bare word 'schema' (no slash, no extension),
    # which is indistinguishable from prose/org-tags, so it is not extracted.
    assert _targets("@schema/ is a directory") == set()


def test_path_reference_with_slash_but_no_extension_kept():
    # A multi-component path is a real reference even without an extension.
    # Trailing slash on a directory ref is normalized away.
    assert _targets("@hass/config/packages/ is synced") == {"hass/config/packages"}
    assert _targets("@hass/config/packages is synced") == {"hass/config/packages"}


# --- extractor: fenced code blocks are skipped ------------------------------


def test_fenced_code_blocks_skipped():
    content = (
        "before @real.md\n"
        "```\n"
        "@fake-in-fence.md\n"
        "root@host.com\n"
        "```\n"
        "after @after.md\n"
    )
    assert _targets(content, "at") == {"real.md", "after.md"}


def test_tilde_fences_skipped():
    content = "a @one.md\n~~~\n@hidden.md\n~~~\nb @two.md"
    assert _targets(content, "at") == {"one.md", "two.md"}


def test_strip_code_blocks_preserves_line_count():
    content = "a\n```\nx\ny\n```\nb"
    assert len(strip_code_blocks(content).split("\n")) == len(content.split("\n"))


# --- extractor: markdown links ----------------------------------------------


def test_relative_markdown_links_extracted():
    assert _targets("see [the structure](./STRUCTURE.md)", "link") == {"./STRUCTURE.md"}
    assert _targets("[plan](sub/PLAN.org)", "link") == {"sub/PLAN.org"}


def test_absolute_and_scheme_links_skipped():
    assert _targets("[x](https://example.com/y)", "link") == set()
    assert _targets("[m](mailto:a@b.com)", "link") == set()
    assert _targets("[a](/etc/passwd)", "link") == set()
    assert _targets("[p](//cdn.example.com/x)", "link") == set()


def test_anchor_only_links_skipped():
    assert _targets("jump [here](#section)", "link") == set()


def test_placeholder_link_text_skipped():
    # "[text](url)" in docs is a placeholder, not a relative path.
    assert _targets("Use markdown links ([text](url))", "link") == set()


def test_link_fragment_stripped_for_resolution():
    assert _targets("[s](foo.md#section)", "link") == {"foo.md"}


# --- resolution: two bases (.mdc vs AGENTS) ---------------------------------


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_mdc_rule_resolves_against_generation_root_and_own_dir(tmp_path: Path):
    root = tmp_path
    # A .mdc rule lives under .agents/contextual-rules/.
    rule_dir = root / ".agents" / "contextual-rules"
    rule_dir.mkdir(parents=True)
    # @AGENTS.md should resolve against the generation root (where the Claude
    # adapter embeds the rule), not the rule's own directory.
    _write(root / "AGENTS.md")
    # @atoms/x.md should resolve against the rule's own directory (Cursor embeds
    # sibling atoms/).
    _write(rule_dir / "atoms" / "x.md")

    rule = Rule(
        name="r",
        type="contextual",
        path=rule_dir / "r.mdc",
        frontmatter={},
        content="see @AGENTS.md and @atoms/x.md",
    )
    ruleset = RuleSet(auto=[], contextual=[rule], agents=[], skills=[])
    assert validate_references(ruleset, root, root) == []


def test_agents_file_resolves_against_own_directory(tmp_path: Path):
    root = tmp_path
    agents_dir = root / "nix" / "service"
    agents_dir.mkdir(parents=True)
    _write(agents_dir / "README.md")

    rule = Rule(
        name="AGENTS",
        type="agents",
        path=agents_dir / "AGENTS.md",
        frontmatter={},
        content="@README.md",
    )
    ruleset = RuleSet(auto=[], contextual=[], agents=[rule], skills=[])
    assert validate_references(ruleset, root, root) == []


def test_broken_reference_reported(tmp_path: Path):
    root = tmp_path
    agents_dir = root / "svc"
    agents_dir.mkdir(parents=True)
    rule = Rule(
        name="AGENTS",
        type="agents",
        path=agents_dir / "AGENTS.md",
        frontmatter={},
        content="@MISSING.md",
    )
    ruleset = RuleSet(auto=[], contextual=[], agents=[rule], skills=[])
    errors = validate_references(ruleset, root, root)
    assert len(errors) == 1
    assert "MISSING.md" in errors[0]


def test_dangling_symlink_counts_as_resolved(tmp_path: Path):
    root = tmp_path
    link = root / "schema"
    link.symlink_to(root / "does-not-exist")  # dangling on purpose
    assert resolves("schema", [root]) is True


def test_resolves_returns_false_when_absent(tmp_path: Path):
    assert resolves("nope.md", [tmp_path]) is False

"""Tests for @-reference and markdown-link extraction and resolution."""

import subprocess
from pathlib import Path

from steering.generators.models import Rule, RuleSet, Skill
from steering.generators.references import (
    extract_references,
    is_gitignored,
    resolves,
    strip_code_blocks,
    strip_html_comments,
    strip_indented_code_blocks,
    strip_inline_code,
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


def test_inline_code_spans_skipped():
    # `dig @100.100.100.100` is a shell example, not a reference to a file
    # named 100.100.100.100 -- reported as a broken reference before this.
    content = "run `dig @100.100.100.100 <name>` first, then read @real.md"
    assert _targets(content, "at") == {"real.md"}


def test_inline_code_preserves_line_count():
    content = "a `@x.md`\nb `@y.md`\nc"
    assert len(strip_inline_code(content).split("\n")) == len(content.split("\n"))


def test_multiline_inline_code_preserves_line_count():
    # A wrapped code span (real corpus: an AGENTS.md wraps a JSON schema across
    # lines inside one pair of backticks) must keep its newlines when blanked.
    content = 'schema: `{"a": 1,\n"b": 2}` end'
    assert len(strip_inline_code(content).split("\n")) == len(content.split("\n"))


def test_inline_code_span_across_single_newline_still_stripped():
    content = "run `dig @1.1.1.1\n+short` first, then @real.md"
    assert _targets(content, "at") == {"real.md"}


def test_stray_backticks_do_not_pair_across_blank_lines():
    # Two stray backticks in different paragraphs must not be treated as one
    # giant code span -- that would blank the prose between them and hide a
    # genuinely broken reference. Markdown wouldn't pair them either: a blank
    # line ends the paragraph.
    content = "a stray ` here\n\nsee @broken.md\n\nanother stray ` there"
    assert _targets(content, "at") == {"broken.md"}


# --- extractor: indented code blocks are skipped -----------------------------


def test_indented_code_blocks_skipped():
    # Four-space indentation after a blank line is markdown's other code
    # syntax; a shell example written that way is not a reference to a file
    # named 100.100.100.100.
    content = (
        "Resolve names directly:\n"
        "\n"
        "    dig @100.100.100.100 weaver.lan\n"
        "    cat @notes.fake.md\n"
        "\n"
        "then read @real.md\n"
    )
    assert _targets(content, "at") == {"real.md"}


def test_tab_indented_code_blocks_skipped():
    content = "example:\n\n\tdig @9.9.9.9.md host\n\nsee @real.md"
    assert _targets(content, "at") == {"real.md"}


def test_indented_block_interior_blank_line_does_not_end_it():
    # Blank lines inside an indented block keep the block going; only a
    # non-blank, non-indented line ends it.
    content = "code:\n\n    @a.fake.md\n\n    @b.fake.md\n\nprose @real.md"
    assert _targets(content, "at") == {"real.md"}


def test_nested_list_items_are_not_code():
    # A 4-space sub-bullet directly under its parent item is prose (an
    # indented code block can't interrupt a paragraph), so references there
    # still count.
    content = "- outer item\n    - nested item, see @nested.md"
    assert _targets(content, "at") == {"nested.md"}


def test_indented_continuation_line_still_scanned():
    # Lazy continuation of a paragraph: indentation without a preceding blank
    # line is still prose.
    content = "See the following file\n    @cont.md for details"
    assert _targets(content, "at") == {"cont.md"}


def test_strip_indented_code_blocks_preserves_line_count():
    content = "a:\n\n    x\n\n    y\n\nb"
    assert len(strip_indented_code_blocks(content).split("\n")) == len(
        content.split("\n")
    )


# --- extractor: HTML comments are skipped ------------------------------------


def test_html_comments_skipped():
    # Commented-out sections keep their old refs around on purpose; flagging
    # them as broken would force deleting the comment to commit.
    content = "keep @real.md\n<!-- retired: see @old-notes.md -->\nend"
    assert _targets(content, "at") == {"real.md"}


def test_multiline_html_comment_skipped():
    content = "a\n<!--\n@gone.md\n[x](dead.md)\n-->\nb @real.md"
    assert _targets(content) == {"real.md"}


def test_strip_html_comments_preserves_line_count():
    content = "a\n<!--\nx\ny\n-->\nb"
    assert len(strip_html_comments(content).split("\n")) == len(content.split("\n"))


def test_unclosed_html_comment_left_alone():
    # An unclosed <!-- must not eat the rest of the document.
    content = "a <!-- dangling\nstill prose @real.md"
    assert _targets(content, "at") == {"real.md"}


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


def test_link_title_dropped_from_target():
    # CommonMark allows a quoted title after the destination. The title is not
    # part of the path; validating 'guide.md "the guide"' as one target
    # reports a perfectly valid link to an existing file as broken.
    assert _targets('[guide](docs/guide.md "the guide")', "link") == {"docs/guide.md"}
    assert _targets("[g](docs/guide.md 'the guide')", "link") == {"docs/guide.md"}


def test_angle_bracket_destination_unwrapped():
    # CommonMark allows the destination in <...> (it may contain spaces).
    assert _targets("[f](<docs/my file.md>)", "link") == {"docs/my file.md"}
    # URL check still applies after unwrapping.
    assert _targets("[u](<https://example.com/a b>)", "link") == set()


def test_autolinks_and_bare_urls_not_references():
    # Autolinks, bare URLs, and scp-style remotes never matched either pattern
    # -- this just pins that down.
    assert _targets("see <https://example.com/x.md> and https://h.io/y.md") == set()
    assert _targets("clone git@github.com:me/repo.git") == set()


def test_reference_style_definitions_not_scanned():
    # [id]: target definitions (and [text][id] usage) aren't inline links, and
    # we deliberately don't validate them: extracting them risks matching
    # dictionary-style prose, and neither corpus uses the syntax at all.
    assert _targets("[docs]: ./missing.md\nuse [docs][docs] elsewhere") == set()


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


# --- resolution: git-ignored host-local references --------------------------


def _git_init(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)


def test_gitignored_reference_is_not_broken(tmp_path: Path):
    # A reference to a deliberately .gitignore'd host-local file (e.g.
    # LOCALCONTEXT.md, "you are running on mantis") is correct even though the
    # file is absent from a fresh checkout -- git check-ignore matches on the
    # pattern, not on the file existing.
    root = tmp_path
    _git_init(root)
    (root / ".gitignore").write_text("/LOCALCONTEXT.md\n", encoding="utf-8")
    # Note: LOCALCONTEXT.md is intentionally NOT created on disk.
    rule = Rule(
        name="AGENTS",
        type="agents",
        path=root / "AGENTS.md",
        frontmatter={},
        content="@LOCALCONTEXT.md",
    )
    ruleset = RuleSet(auto=[], contextual=[], agents=[rule], skills=[])
    assert validate_references(ruleset, root, root) == []


def test_is_gitignored_true_for_ignored_false_otherwise(tmp_path: Path):
    root = tmp_path
    _git_init(root)
    (root / ".gitignore").write_text("/LOCALCONTEXT.md\n", encoding="utf-8")
    assert is_gitignored("LOCALCONTEXT.md", [root]) is True
    # A non-ignored path, and a base that is not a git work tree, are both False
    # (the latter guards against accidental suppression of real broken refs).
    assert is_gitignored("tracked.md", [root]) is False
    assert is_gitignored("LOCALCONTEXT.md", [root / "nonexistent"]) is False

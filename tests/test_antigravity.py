"""Tests for the Antigravity CLI (agy) adapter's pointer rules.

Ground truth (canary probes against agy 1.2.17, 2026-10-03): agy loads
AGENTS.md only by walking up from the cwd, expands ``@[label](path)`` includes
(relative to the including file) but not bare ``@path`` refs, loads
``.agents/rules/*.md`` only with a ``trigger:`` frontmatter, and matches glob
triggers against absolute paths (so they need a ``**/`` prefix).
"""

from pathlib import Path

import yaml

from steering.generators.adapters.antigravity import AntigravityAdapter
from steering.generators.config import Config, normalize_vendors
from steering.generators.discovery import Discovery
from steering.generators.models import Rule, RuleSet

RULES = ".agents/rules"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rule(path: Path, type_: str, content: str, **frontmatter) -> Rule:
    _write(path, content)
    return Rule(name=path.stem, type=type_, path=path, frontmatter=frontmatter, content=content)


def _generate(root: Path, ruleset: RuleSet, dry_run: bool = False) -> dict:
    return AntigravityAdapter().generate(
        ruleset, root, root, dry_run=dry_run, discovery=Discovery(root, "filesystem", [])
    )


def _frontmatter(text: str) -> dict:
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm)


def _include(text: str) -> str:
    line = next(l for l in text.splitlines() if l.startswith("@["))
    return line[line.index("](") + 2 : -1]


def _ruleset(**kw) -> RuleSet:
    return RuleSet(
        auto=kw.get("auto", []),
        contextual=kw.get("contextual", []),
        agents=kw.get("agents", []),
        skills=[],
    )


def test_root_refs_become_always_on_pointers_relative_to_rule_file(tmp_path: Path):
    _write(tmp_path / "docs/STYLE.md", "style @NESTED.md")
    _write(tmp_path / "docs/NESTED.md", "transitive")
    root = _rule(tmp_path / "AGENTS.md", "agents", "@docs/STYLE.md\n")

    files = _generate(tmp_path, _ruleset(agents=[root]))

    style = files[f"{RULES}/steering-ref-docs-STYLE.md"]
    assert _frontmatter(style) == {"trigger": "always_on"}
    assert _include(style) == "../../docs/STYLE.md"
    assert (tmp_path / RULES / _include(style)).resolve() == (tmp_path / "docs/STYLE.md").resolve()
    # Transitive refs get their own rule: agy won't expand the bare @ inside STYLE.md.
    assert f"{RULES}/steering-ref-docs-NESTED.md" in files
    # The root AGENTS.md is loaded natively; never point at it.
    assert not any(_include(c).endswith("/AGENTS.md") for c in files.values())
    assert (tmp_path / RULES / "steering-ref-docs-STYLE.md").read_text() == style


def test_auto_rules_always_on_and_not_duplicated_by_root_ref(tmp_path: Path):
    auto = _rule(tmp_path / ".agents/auto-rules/a.mdc", "auto", "auto body", alwaysApply=True)
    root = _rule(tmp_path / "AGENTS.md", "agents", "@.agents/auto-rules/a.mdc\n")

    files = _generate(tmp_path, _ruleset(auto=[auto], agents=[root]))

    assert list(files) == [f"{RULES}/steering-auto-a.md"]
    assert _frontmatter(files[f"{RULES}/steering-auto-a.md"]) == {"trigger": "always_on"}
    assert _include(files[f"{RULES}/steering-auto-a.md"]) == "../auto-rules/a.mdc"


def test_nested_agents_body_and_refs_glob_scoped_with_anchor(tmp_path: Path):
    _write(tmp_path / "nix/user/REF.md", "ref")
    nested = _rule(tmp_path / "nix/user/AGENTS.md", "agents", "body\n@REF.md\n")

    files = _generate(tmp_path, _ruleset(agents=[nested]))

    body = files[f"{RULES}/steering-agents-nix-user.md"]
    ref = files[f"{RULES}/steering-agents-nix-user--REF.md"]
    for text in (body, ref):
        fm = _frontmatter(text)
        assert fm["trigger"] == "glob"
        # agy matches absolute paths: a bare "nix/user/**" never fires.
        assert fm["globs"] == "**/nix/user/**"
    assert _include(body) == "../../nix/user/AGENTS.md"
    assert _include(ref) == "../../nix/user/REF.md"


def test_nested_ref_already_always_on_is_not_repeated(tmp_path: Path):
    _write(tmp_path / "STRUCTURE.md", "structure")
    root = _rule(tmp_path / "AGENTS.md", "agents", "@STRUCTURE.md\n")
    nested = _rule(tmp_path / "sub/AGENTS.md", "agents", "@../STRUCTURE.md\n")

    files = _generate(tmp_path, _ruleset(agents=[root, nested]))

    assert f"{RULES}/steering-ref-STRUCTURE.md" in files
    assert not any("--" in name and "STRUCTURE" in name for name in files)


def test_contextual_rules_map_to_glob_or_model_decision(tmp_path: Path):
    py = _rule(
        tmp_path / ".agents/contextual-rules/py.mdc", "contextual", "python",
        description="Python style", globs=["*.py"],
    )
    db = _rule(
        tmp_path / ".agents/contextual-rules/db.mdc", "contextual", "db",
        description="Database guidelines",
    )

    files = _generate(tmp_path, _ruleset(contextual=[py, db]))

    assert _frontmatter(files[f"{RULES}/steering-contextual-py.md"]) == {
        "trigger": "glob", "globs": "**/*.py", "description": "Python style",
    }
    assert _frontmatter(files[f"{RULES}/steering-contextual-db.md"]) == {
        "trigger": "model_decision", "description": "Database guidelines",
    }


def test_symlinked_ref_keeps_symlink_path(tmp_path: Path):
    # LOCALCONTEXT.md is a per-machine symlink; the pointer must follow the link
    # at load time, not bake in whichever host generated it.
    _write(tmp_path / "docs/hosts/mantis.md", "mantis")
    (tmp_path / "LOCALCONTEXT.md").symlink_to("docs/hosts/mantis.md")
    root = _rule(tmp_path / "AGENTS.md", "agents", "@LOCALCONTEXT.md\n")

    files = _generate(tmp_path, _ruleset(agents=[root]))

    assert _include(files[f"{RULES}/steering-ref-LOCALCONTEXT.md"]) == "../../LOCALCONTEXT.md"


def test_cleanup_only_touches_generated_files_and_removes_gemini_md(tmp_path: Path):
    _write(tmp_path / RULES / "steering-ref-stale.md", "stale")
    _write(tmp_path / RULES / "hand-written.md", "---\ntrigger: always_on\n---\nmine\n")
    _write(tmp_path / "sub/GEMINI.md", "@AGENTS.md")
    root = _rule(tmp_path / "AGENTS.md", "agents", "no refs\n")

    files = _generate(tmp_path, _ruleset(agents=[root]))

    assert files == {}
    assert not (tmp_path / RULES / "steering-ref-stale.md").exists()
    assert (tmp_path / RULES / "hand-written.md").exists()
    assert not (tmp_path / "sub/GEMINI.md").exists()


def test_dry_run_writes_nothing(tmp_path: Path):
    _write(tmp_path / "README.md", "readme")
    root = _rule(tmp_path / "AGENTS.md", "agents", "@README.md\n")

    files = _generate(tmp_path, _ruleset(agents=[root]), dry_run=True)

    assert f"{RULES}/steering-ref-README.md" in files
    assert not (tmp_path / RULES).exists()


def test_gemini_vendor_is_a_deprecated_alias(tmp_path: Path):
    assert normalize_vendors(["cursor", "gemini", "antigravity"]) == ["cursor", "antigravity"]
    config = Config(
        {
            "version": 1.0,
            "vendor_files": {"cursor": ".cursor/rules"},
            "default_vendors": ["gemini"],
            "skills": {"vendor_destinations": {"gemini": ".gemini/skills"}},
        },
        tmp_path / "c.yaml",
    )
    assert config.default_vendors == ["antigravity"]
    assert config.skills_vendor_destinations == {"antigravity": ".gemini/skills"}
    assert config.validate() == []
    assert config.get_antigravity_rules_dir() == ".agents/rules"


def test_ref_shared_by_two_nested_dirs_fires_for_both(tmp_path: Path):
    _write(tmp_path / "docs/SHARED.md", "shared")
    a = _rule(tmp_path / "a/AGENTS.md", "agents", "@../docs/SHARED.md\n")
    b = _rule(tmp_path / "b/AGENTS.md", "agents", "@../docs/SHARED.md\n@../a/AGENTS.md\n")

    files = _generate(tmp_path, _ruleset(agents=[b, a]))

    assert f"{RULES}/steering-agents-a--docs-SHARED.md" in files
    assert f"{RULES}/steering-agents-b--docs-SHARED.md" in files
    # b @-references a's AGENTS.md: a still gets its own rule regardless of order.
    assert f"{RULES}/steering-agents-a.md" in files
    assert f"{RULES}/steering-agents-b--a-AGENTS.md" in files

"""Tests for recognising and removing steering-generated CLAUDE.md files."""

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from steering.generators.adapters.claude import ClaudeAdapter
from steering.generators.claude_cleanup import (
    ROOT_INDEX_HEADER,
    classify_claude_md,
    remove_legacy_claude_files,
    scan_legacy_claude_files,
)
from steering.generators.cli import cli
from steering.generators.discovery import Discovery
from steering.generators.models import RuleSet


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fs(root: Path, ignored: list[str] | None = None) -> Discovery:
    return Discovery(root, "filesystem", ignored or [])


# --- classification ---------------------------------------------------------


def test_pointer_stub_with_sibling_is_a_stub(tmp_path: Path):
    _write(tmp_path / "AGENTS.md", "# rules")
    _write(tmp_path / "CLAUDE.md", "@AGENTS.md\n")
    assert classify_claude_md(tmp_path / "CLAUDE.md") == "stub"


def test_pointer_stub_tolerates_whitespace_and_mdc_sibling(tmp_path: Path):
    _write(tmp_path / "AGENTS.mdc", "# rules")
    _write(tmp_path / "CLAUDE.md", "\n@AGENTS.mdc\n\n")
    assert classify_claude_md(tmp_path / "CLAUDE.md") == "stub"


def test_pointer_without_sibling_is_foreign(tmp_path: Path):
    # Someone importing an AGENTS.md that lives elsewhere -- not our stub.
    _write(tmp_path / "CLAUDE.md", "@AGENTS.md\n")
    assert classify_claude_md(tmp_path / "CLAUDE.md") is None


def test_pointer_with_extra_content_is_foreign(tmp_path: Path):
    # The docs' recommended shape for Claude-specific additions: keep it.
    _write(tmp_path / "AGENTS.md", "# rules")
    _write(
        tmp_path / "CLAUDE.md",
        "@AGENTS.md\n\n## Claude Code\n\nUse plan mode under src/billing/.\n",
    )
    assert classify_claude_md(tmp_path / "CLAUDE.md") is None


def test_root_index_header_is_recognised(tmp_path: Path):
    _write(
        tmp_path / "CLAUDE.md",
        ROOT_INDEX_HEADER + "\n## Auto-Rules\n\nNo auto-rules configured.\n",
    )
    assert classify_claude_md(tmp_path / "CLAUDE.md") == "root-index"


def test_hand_written_file_is_foreign(tmp_path: Path):
    _write(tmp_path / "CLAUDE.md", "# My project\n\nRun the tests before committing.\n")
    assert classify_claude_md(tmp_path / "CLAUDE.md") is None


# --- scanning ---------------------------------------------------------------


def _legacy_tree(root: Path) -> None:
    _write(root / "AGENTS.md", "# root")
    _write(root / "CLAUDE.md", ROOT_INDEX_HEADER + "\n## Auto-Rules\n")
    _write(root / "nix/AGENTS.md", "# nix")
    _write(root / "nix/CLAUDE.md", "@AGENTS.md\n")
    _write(root / "docs/CLAUDE.md", "# hand written\n")


def test_scan_buckets_removable_and_foreign(tmp_path: Path):
    _legacy_tree(tmp_path)

    scan = scan_legacy_claude_files(_fs(tmp_path))

    assert {(i.path.relative_to(tmp_path).as_posix(), i.kind) for i in scan.removable} == {
        ("CLAUDE.md", "root-index"),
        ("nix/CLAUDE.md", "stub"),
    }
    assert [p.relative_to(tmp_path).as_posix() for p in scan.foreign] == ["docs/CLAUDE.md"]
    assert scan.in_submodules == []


def test_scan_respects_ignored_directories(tmp_path: Path):
    _write(tmp_path / "node_modules/pkg/AGENTS.md", "# pkg")
    _write(tmp_path / "node_modules/pkg/CLAUDE.md", "@AGENTS.md\n")

    scan = scan_legacy_claude_files(_fs(tmp_path, ["node_modules"]))

    assert scan.removable == [] and scan.foreign == []


# --- removal ----------------------------------------------------------------


def test_dry_run_reports_but_removes_nothing(tmp_path: Path):
    _legacy_tree(tmp_path)
    scan = scan_legacy_claude_files(_fs(tmp_path))

    removed = remove_legacy_claude_files(scan, dry_run=True)

    assert len(removed) == 2
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "nix/CLAUDE.md").exists()


def test_remove_deletes_only_recognised_files(tmp_path: Path):
    _legacy_tree(tmp_path)
    scan = scan_legacy_claude_files(_fs(tmp_path))

    removed = remove_legacy_claude_files(scan)

    assert len(removed) == 2
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "nix/CLAUDE.md").exists()
    assert (tmp_path / "docs/CLAUDE.md").exists()
    # The sources are untouched.
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "nix/AGENTS.md").exists()


# --- submodules -------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(
        ["git", "-C", str(root), "-c", "protocol.file.allow=always", *args],
        check=True,
        capture_output=True,
        env=env,
    )


def test_scan_skips_files_inside_submodules(tmp_path: Path):
    inner = tmp_path / "inner"
    _write(inner / "AGENTS.md", "# inner")
    _write(inner / "CLAUDE.md", "@AGENTS.md\n")
    _git(inner, "init", "-q")
    _git(inner, "add", "-A")
    _git(inner, "commit", "-q", "-m", "init")

    outer = tmp_path / "outer"
    _write(outer / "AGENTS.md", "# outer")
    _write(outer / "CLAUDE.md", "@AGENTS.md\n")
    _git(outer, "init", "-q")
    _git(outer, "submodule", "add", "-q", str(inner), "sub")
    _git(outer, "add", "-A")
    _git(outer, "commit", "-q", "-m", "init")

    discovery = Discovery(outer, "git", [])
    assert discovery.submodule_paths() == ["sub"]

    scan = scan_legacy_claude_files(discovery)

    assert [i.path for i in scan.removable] == [outer / "CLAUDE.md"]
    assert scan.in_submodules == [outer / "sub" / "CLAUDE.md"]

    remove_legacy_claude_files(scan)
    assert (outer / "sub" / "CLAUDE.md").exists()


# --- adapter ----------------------------------------------------------------


def test_claude_adapter_writes_nothing_and_warns_about_leftovers(tmp_path: Path, capsys):
    _write(tmp_path / "AGENTS.md", "# root")
    _write(tmp_path / "CLAUDE.md", "@AGENTS.md\n")
    ruleset = RuleSet(auto=[], contextual=[], agents=[], skills=[])

    files = ClaudeAdapter().generate(ruleset, tmp_path, tmp_path, discovery=_fs(tmp_path))

    assert files == {}
    assert (tmp_path / "CLAUDE.md").exists()  # generate never deletes
    assert "cleanup-claude-md" in capsys.readouterr().out


def test_claude_adapter_is_quiet_when_clean(tmp_path: Path, capsys):
    _write(tmp_path / "AGENTS.md", "# root")
    ruleset = RuleSet(auto=[], contextual=[], agents=[], skills=[])

    ClaudeAdapter().generate(ruleset, tmp_path, tmp_path, discovery=_fs(tmp_path))

    assert "WARN" not in capsys.readouterr().out


# --- CLI --------------------------------------------------------------------


def test_cli_cleanup_dry_run_then_real(tmp_path: Path):
    _legacy_tree(tmp_path)
    config = tmp_path / "steering.yaml"
    _write(
        config,
        "version: 1.0\nvendor_files:\n  cursor: .cursor/rules\ndiscovery: filesystem\n",
    )
    common = [
        "cleanup-claude-md",
        "--input", str(tmp_path),
        "--output", str(tmp_path),
        "--config-path", str(config),
    ]
    runner = CliRunner()

    dry = runner.invoke(cli, [*common, "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "Would remove 2 file(s)" in dry.output
    assert (tmp_path / "nix/CLAUDE.md").exists()

    real = runner.invoke(cli, common)
    assert real.exit_code == 0, real.output
    assert "Removed 2 file(s)" in real.output
    assert "docs/CLAUDE.md" in real.output  # reported as left alone
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "nix/CLAUDE.md").exists()
    assert (tmp_path / "docs/CLAUDE.md").exists()

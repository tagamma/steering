"""Find and remove the CLAUDE.md files steering used to generate.

Until 2026-10 the Claude adapter wrote a root ``CLAUDE.md`` index (auto-rule
@-references, contextual-rule and skill lists, an AGENTS.md summary) plus a
one-line ``@AGENTS.md`` pointer next to every AGENTS file, because Claude Code
only read CLAUDE.md. Claude Code v2.1.277+ reads AGENTS.md natively -- the root
one at session start, nested ones when it works in that directory -- but ONLY
while no CLAUDE.md exists in or above the working directory. So the files we
used to write now actively stop Claude Code from reading the source of truth.
The adapter no longer writes them; this module recognises and deletes them.

Deleting is gated on content, because a CLAUDE.md is also a file people write
by hand. A file goes only if it is exactly a pointer stub (``@AGENTS.md`` or
``@AGENTS.mdc``, with that sibling actually present) or starts with the header
the old root-index generator wrote. Anything else is reported and left alone.
Files inside git submodules are skipped too: that repository's own steering run
owns them, and deleting them from here would leave the submodule dirty behind
the user's back.
"""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import List, Literal, Optional

from .discovery import Discovery

LegacyKind = Literal["stub", "root-index"]

# Sibling files a one-line pointer stub may point at.
_STUB_TARGETS = ("AGENTS.md", "AGENTS.mdc")

# The first lines every generated root index started with. Nothing else is
# stable across old versions (the sections below it changed over time), but
# this header never did, and nobody writes it by hand.
ROOT_INDEX_HEADER = (
    "# AI Agent Context\n"
    "\n"
    "This repository uses AI-assisted development with structured behavioral rules.\n"
)


@dataclass(frozen=True)
class LegacyClaudeFile:
    """A CLAUDE.md that steering recognises as its own output."""

    path: Path
    kind: LegacyKind


@dataclass
class LegacyScan:
    """Outcome of scanning a tree for steering-generated CLAUDE.md files."""

    removable: List[LegacyClaudeFile] = field(default_factory=list)
    # CLAUDE.md files whose content isn't anything steering ever wrote.
    foreign: List[Path] = field(default_factory=list)
    # CLAUDE.md files inside git submodules (another repo's steering run).
    in_submodules: List[Path] = field(default_factory=list)


def classify_claude_md(path: Path) -> Optional[LegacyKind]:
    """Return which kind of generated file ``path`` is, or None if it isn't one.

    A stub must match exactly (modulo surrounding whitespace) AND have the
    AGENTS file it points at next to it: a lone ``@AGENTS.md`` with no such
    sibling is somebody's deliberate import of a file elsewhere, not our stub.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    stripped = content.strip()
    for target in _STUB_TARGETS:
        if stripped == f"@{target}" and (path.parent / target).is_file():
            return "stub"

    if content.startswith(ROOT_INDEX_HEADER):
        return "root-index"

    return None


def scan_legacy_claude_files(discovery: Discovery) -> LegacyScan:
    """Classify every CLAUDE.md the discovery can see under its root.

    Uses the cleanup view of discovery (tracked plus untracked-but-not-ignored
    in git mode), so a freshly generated, not-yet-committed file is found while
    gitignored checkouts are left alone.
    """
    scan = LegacyScan()
    submodules = [PurePosixPath(p) for p in discovery.submodule_paths()]

    for path in discovery.cleanup_files(["**/CLAUDE.md"]):
        rel = PurePosixPath(path.relative_to(discovery.root).as_posix())
        if any(sub == rel or sub in rel.parents for sub in submodules):
            scan.in_submodules.append(path)
            continue

        kind = classify_claude_md(path)
        if kind is None:
            scan.foreign.append(path)
        else:
            scan.removable.append(LegacyClaudeFile(path=path, kind=kind))

    return scan


def remove_legacy_claude_files(
    scan: LegacyScan, *, dry_run: bool = False
) -> List[Path]:
    """Delete the removable files from a scan; return the paths removed.

    Only ``scan.removable`` is ever touched. With ``dry_run`` nothing is
    deleted and the same list is returned, so callers can print one report
    for both modes.
    """
    removed: List[Path] = []
    for item in scan.removable:
        if not dry_run:
            try:
                item.path.unlink()
            except OSError as e:
                print(f"WARN: Failed to remove {item.path}: {e}")
                continue
        removed.append(item.path)
    return removed

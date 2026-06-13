"""Always-on context budget computation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set

from .adapters.claude import ClaudeAdapter
from .models import RuleSet
from .references import extract_references


@dataclass
class BudgetResult:
    """Result of computing the always-on context budget."""

    total_bytes: int
    files: List[Path] = field(default_factory=list)  # transitively referenced files
    root_claude_md_bytes: int = 0

    @property
    def total_kb(self) -> float:
        """Total always-on context size in kilobytes (1 KB = 1024 bytes)."""
        return self.total_bytes / 1024


def compute_always_context(
    ruleset: RuleSet, output_dir: Path, input_dir: Path
) -> BudgetResult:
    """Compute the size of the always-loaded context for a repository.

    Args:
        ruleset: The loaded ruleset (auto/contextual/agents/skills).
        output_dir: Output directory (repository / generation root).
        input_dir: Input directory containing the rules/ subdirectory.

    Returns:
        A BudgetResult with the total byte size and the list of files counted.
    """
    output_dir = Path(output_dir)
    input_dir = Path(input_dir)

    # The root CLAUDE.md content exactly as generate would produce it.
    root_claude_md = ClaudeAdapter()._generate_main_claude_md(
        ruleset, output_dir, input_dir
    )
    root_bytes = len(root_claude_md.encode("utf-8"))
    total = root_bytes

    # Seed the transitive walk with the files the root CLAUDE.md @-references:
    # the root AGENTS.md and every auto-rule. (Contextual rules and nested
    # AGENTS files are only listed by path, not @-embedded, so they are not
    # part of the always-on context.)
    seeds: List[Path] = []

    root_agents = output_dir / "AGENTS.md"
    if not root_agents.exists():
        root_agents = output_dir / "AGENTS.mdc"
    if root_agents.exists():
        seeds.append(root_agents)

    for rule in ruleset.auto:
        seeds.append(rule.path)

    visited: Set[Path] = set()
    counted: List[Path] = []

    def walk(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in visited:
            return
        visited.add(resolved)
        if not path.exists() or not path.is_file():
            return
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        nonlocal total
        total += len(content.encode("utf-8"))
        counted.append(path)

        # Follow @-references found in this file. The natural base is the
        # file's own directory; the repo root is the secondary base. (We only
        # follow @-references, not markdown links: only @-refs are embedded
        # into context.)
        natural_base = path.parent
        for ref in extract_references(content):
            if ref.kind != "at":
                continue
            for candidate in (natural_base / ref.target, output_dir / ref.target):
                if candidate.exists() and candidate.is_file():
                    walk(candidate)
                    break

    for seed in seeds:
        walk(seed)

    return BudgetResult(
        total_bytes=total, files=counted, root_claude_md_bytes=root_bytes
    )

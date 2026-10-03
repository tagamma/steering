from pathlib import Path
from typing import Dict, Optional

from ..claude_cleanup import scan_legacy_claude_files
from ..discovery import Discovery
from ..models import RuleSet


class ClaudeAdapter:
    """No-op adapter for Claude Code.

    Claude Code v2.1.277+ reads ``AGENTS.md`` natively: the root one at
    session start (with its ``@path`` imports expanded) and nested ones when
    it works on files in their directory. Project skills it reads from
    ``.claude/skills/`` -- not from ``.agents/skills/`` -- which is what
    ``skills.vendor_destinations.claude`` symlinks for. So nothing is
    generated for it anymore: the root AGENTS.md @-references the auto-rules
    (``steering validate`` fails when one isn't wired), nested AGENTS.md files
    load themselves, and contextual guidance lives in skills.

    The ``CLAUDE.md`` files earlier versions wrote now get in the way, because
    Claude Code only reads AGENTS.md while no CLAUDE.md exists in or above the
    working directory. ``generate`` therefore warns when it finds them and
    points at ``steering cleanup-claude-md``, which checks their content
    before deleting. ``generate`` itself never deletes anything here: removing
    57 files from a tree is a separate, deliberate step.

    https://code.claude.com/docs/en/memory#agents-md
    """

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
        discovery: Optional[Discovery] = None,
    ) -> Dict[str, str]:
        output_dir = Path(output_dir)
        if discovery is None:
            discovery = Discovery.fallback(output_dir)

        # Read-only, so it runs in dry-run mode too.
        scan = scan_legacy_claude_files(discovery)
        if scan.removable:
            print(
                f"WARN: {len(scan.removable)} CLAUDE.md file(s) left over from "
                "earlier steering runs stop Claude Code from reading AGENTS.md "
                "natively; run `steering cleanup-claude-md` to remove them."
            )

        return {}

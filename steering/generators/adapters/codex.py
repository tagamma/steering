from pathlib import Path
from typing import Dict

from ..models import RuleSet


class CodexAdapter:
    """No-op adapter for OpenAI's Codex CLI.

    Codex reads ``AGENTS.md`` (walking up to the repo root) and discovers
    skills under ``.agents/skills/`` natively. Both are source-of-truth files
    steering already manages, so nothing needs generating. This adapter exists
    only so users can list ``codex`` in ``default_vendors``.

    https://developers.openai.com/codex/skills
    """

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
    ) -> Dict[str, str]:
        return {}

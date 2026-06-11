from pathlib import Path
from typing import Dict, Optional

from ..discovery import Discovery
from ..models import RuleSet


class GeminiAdapter:
    """Cleanup-only adapter for Google's Gemini CLI.

    Gemini CLI reads ``AGENTS.md`` hierarchically (repo root and subdirectories)
    once ``contextFileName`` is set to ``AGENTS.md`` in ``.gemini/settings.json``,
    and discovers skills under ``.agents/skills/`` natively. Both are
    source-of-truth files steering already manages, so no ``GEMINI.md`` files
    are generated.

    This adapter only removes stale ``GEMINI.md`` files left over from when
    steering used to generate them; it writes nothing. It exists so users can
    keep ``gemini`` in ``default_vendors`` and have those old files cleaned up.

    https://google-gemini.github.io/gemini-cli/docs/cli/configuration.html
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
        if dry_run:
            return {}

        output_dir = Path(output_dir)
        if discovery is None:
            discovery = Discovery.fallback(output_dir)

        # Remove old generated GEMINI.md files. The scan is discovery-aware, so
        # files git doesn't know about (e.g. inside gitignored checkouts) are
        # left alone.
        for gemini_file in discovery.cleanup_files(["**/GEMINI.md"]):
            try:
                gemini_file.unlink()
            except Exception as e:
                print(f"⚠️  Warning: Failed to remove {gemini_file}: {e}")

        return {}

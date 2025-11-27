from pathlib import Path
from typing import Dict, List

from ..models import RuleSet


class GeminiAdapter:
    """Generate Gemini CLI configuration using @ references to source files.

    Works exactly like ClaudeAdapter but generates GEMINI.md files instead.
    Gemini CLI supports the same @ reference format as Claude Code.
    """

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
    ) -> Dict[str, str]:
        """Generate Gemini CLI configuration files.

        Args:
            ruleset: The complete set of rules to generate from
            output_dir: Output directory (repository root)
            input_dir: Input directory containing rules/ subdirectory
            dry_run: If True, don't create actual files

        Returns:
            Dict mapping generated file paths to their content
        """
        files: Dict[str, str] = {}

        output_dir = Path(output_dir)
        input_dir = Path(input_dir)

        # Clean up old GEMINI.md files
        if not dry_run:
            self._cleanup_gemini_files(output_dir)

        # Generate main GEMINI.md at repository root
        gemini_md_content = self._generate_main_gemini_md(
            ruleset, output_dir, input_dir
        )
        gemini_md_path = output_dir / "GEMINI.md"

        files[str(gemini_md_path.relative_to(output_dir))] = gemini_md_content

        if not dry_run:
            gemini_md_path.parent.mkdir(parents=True, exist_ok=True)
            gemini_md_path.write_text(gemini_md_content, encoding="utf-8")

        # Generate adjacent GEMINI.md files next to AGENTS files
        agents_gemini_files = self._generate_agents_gemini_files(
            ruleset.agents, output_dir, dry_run
        )
        files.update(agents_gemini_files)

        return files

    def _cleanup_gemini_files(self, output_dir: Path):
        """Clean up old generated GEMINI.md files.

        Removes all GEMINI.md files throughout the repository (they're all generated).

        Args:
            output_dir: Output directory (repository root)
        """
        for gemini_file in output_dir.rglob("GEMINI.md"):
            try:
                if gemini_file.is_file() or gemini_file.is_symlink():
                    gemini_file.unlink()
            except Exception as e:
                print(f"⚠️  Warning: Failed to remove {gemini_file}: {e}")

    def _generate_main_gemini_md(
        self, ruleset: RuleSet, output_dir: Path, input_dir: Path
    ) -> str:
        """Generate the main GEMINI.md file at repository root.

        Args:
            ruleset: The complete set of rules
            output_dir: Output directory (repository root)
            input_dir: Input directory containing rules/

        Returns:
            String content for GEMINI.md
        """
        sections = []

        # Header
        sections.extend(
            [
                "# Gemini CLI Context",
                "",
                "This repository uses AI-assisted development with structured behavioral rules.",
                "",
            ]
        )

        # Auto-rules section (always included via @ references)
        sections.extend(["## Auto-Rules", ""])

        sections.append(
            "The following rules are automatically applied across all contexts:"
        )
        sections.append("")

        # Include root AGENTS.md if it exists
        root_agents = output_dir / "AGENTS.md"
        if not root_agents.exists():
            root_agents = output_dir / "AGENTS.mdc"

        if root_agents.exists():
            sections.append(f"- @{root_agents.name}")

        if ruleset.auto:
            for rule in ruleset.auto:
                # Generate @ reference relative to repository root
                try:
                    rule_rel_path = rule.path.relative_to(output_dir)
                    sections.append(f"- @{rule_rel_path}")
                except ValueError:
                    # Can't make relative path - use absolute
                    sections.append(f"- @{rule.path}")

        if not ruleset.auto and not root_agents.exists():
            sections.append("No auto-rules configured.")

        sections.append("")

        # Contextual rules section (listed for on-demand loading)
        sections.extend(
            [
                "## Contextual Rules",
                "",
                "The following rules apply to specific contexts. Load them when working in the relevant domain:",
                "",
            ]
        )

        if ruleset.contextual:
            for rule in ruleset.contextual:
                # Generate file path relative to repository root
                try:
                    rule_rel_path = rule.path.relative_to(output_dir)
                except ValueError:
                    rule_rel_path = rule.path

                # Format: - `path`: description
                sections.append(f"- `{rule_rel_path}`: {rule.description}")
        else:
            sections.append("No contextual rules configured.")

        sections.append("")

        # AGENTS files section
        sections.extend(
            [
                "## Local Context (AGENTS files)",
                "",
                "This repository has AGENTS.{md,mdc} files co-located with code throughout the codebase.",
                "These provide directory-specific context and guidelines.",
                "",
            ]
        )

        if ruleset.agents:
            sections.append(
                f"Found {len(ruleset.agents)} AGENTS file(s) throughout the codebase."
            )
            sections.append(
                "Gemini CLI automatically loads GEMINI.md files when entering directories."
            )
            sections.append("")

            # List AGENTS files (excluding root since it's in auto-rules)
            non_root_agents = [r for r in ruleset.agents if r.path.parent != output_dir]

            if non_root_agents:
                sections.append("AGENTS files in subdirectories:")
                for rule in sorted(non_root_agents, key=lambda r: str(r.path))[:5]:
                    try:
                        rule_rel_path = rule.path.relative_to(output_dir)
                        sections.append(f"- `{rule_rel_path}`")
                    except ValueError:
                        sections.append(f"- `{rule.path}`")

                if len(non_root_agents) > 5:
                    sections.append(f"- ... and {len(non_root_agents) - 5} more")
        else:
            sections.append("No AGENTS files discovered.")

        sections.append("")

        # Footer with usage instructions
        sections.extend(
            [
                "## Usage",
                "",
                "- **Auto-rules** above (including root AGENTS.md) are always active",
                "- **Contextual rules** can be loaded on-demand if their description matches the context you're working in/on",
                "- **AGENTS files** in subdirectories are auto-loaded via GEMINI.md when you enter those directories",
                "",
            ]
        )

        return "\n".join(sections)

    def _generate_agents_gemini_files(
        self, agents_rules: List, output_dir: Path, dry_run: bool
    ) -> Dict[str, str]:
        """Generate GEMINI.md files adjacent to AGENTS files.

        Args:
            agents_rules: List of Rule objects for AGENTS files
            output_dir: Output directory (repository root)
            dry_run: If True, don't create actual files

        Returns:
            Dict mapping file paths to their content
        """
        files: Dict[str, str] = {}

        for rule in agents_rules:
            # Create GEMINI.md in the same directory as the AGENTS file
            gemini_path = rule.path.parent / "GEMINI.md"

            # Skip if this would overwrite the root GEMINI.md
            if gemini_path == output_dir / "GEMINI.md":
                continue

            # Generate simple @ reference to the AGENTS file
            agents_filename = rule.path.name
            content = f"@{agents_filename}\n"

            try:
                gemini_rel = gemini_path.relative_to(output_dir)
                files[str(gemini_rel)] = content
            except ValueError:
                # Can't make relative path
                files[str(gemini_path)] = content

            if not dry_run:
                gemini_path.parent.mkdir(parents=True, exist_ok=True)
                gemini_path.write_text(content, encoding="utf-8")

        return files

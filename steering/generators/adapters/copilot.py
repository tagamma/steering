from pathlib import Path
from typing import Dict, List

from ..models import RuleSet


class CopilotAdapter:
    """Generate GitHub Copilot configuration files.

    Creates:
    - .github/copilot-instructions.md (repository-wide instructions from auto-rules)
    - .github/instructions/*.instructions.md (path-specific from contextual rules)
    - AGENTS.md files are already supported natively by Copilot (no generation needed)
    """

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
    ) -> Dict[str, str]:
        """Generate GitHub Copilot configuration files.

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

        # Clean up old generated files
        if not dry_run:
            self._cleanup_copilot_files(output_dir)

        # Generate repository-wide instructions from auto-rules
        if ruleset.auto:
            copilot_instructions = self._generate_copilot_instructions(
                ruleset.auto, output_dir
            )
            copilot_instructions_path = (
                output_dir / ".github" / "copilot-instructions.md"
            )

            files[str(copilot_instructions_path.relative_to(output_dir))] = (
                copilot_instructions
            )

            if not dry_run:
                copilot_instructions_path.parent.mkdir(parents=True, exist_ok=True)
                copilot_instructions_path.write_text(
                    copilot_instructions, encoding="utf-8"
                )

        # Generate path-specific instructions from contextual rules
        for rule in ruleset.contextual:
            instruction_file = self._generate_instruction_file(rule, output_dir)
            instruction_path = (
                output_dir / ".github" / "instructions" / f"{rule.name}.instructions.md"
            )

            files[str(instruction_path.relative_to(output_dir))] = instruction_file

            if not dry_run:
                instruction_path.parent.mkdir(parents=True, exist_ok=True)
                instruction_path.write_text(instruction_file, encoding="utf-8")

        # Note: AGENTS.md files are supported natively by Copilot, no generation needed!
        # Add informational message about AGENTS support
        if ruleset.agents:
            agents_note = (
                f"# GitHub Copilot Native AGENTS.md Support\n\n"
                f"GitHub Copilot natively supports AGENTS.md files throughout the repository.\n"
                f"Discovered {len(ruleset.agents)} AGENTS.md file(s):\n\n"
            )
            for agent in sorted(ruleset.agents, key=lambda r: str(r.path))[:10]:
                try:
                    rel_path = agent.path.relative_to(output_dir)
                    agents_note += f"- {rel_path}\n"
                except ValueError:
                    agents_note += f"- {agent.path}\n"

            if len(ruleset.agents) > 10:
                agents_note += f"- ... and {len(ruleset.agents) - 10} more\n"

            agents_note += (
                "\nThese files are automatically read by Copilot coding agent.\n"
                "No additional generation or configuration required!\n"
            )

            files["_COPILOT_AGENTS_INFO.md"] = agents_note

        return files

    def _cleanup_copilot_files(self, output_dir: Path):
        """Clean up old generated Copilot files.

        Args:
            output_dir: Output directory (repository root)
        """
        import shutil

        # Clean up copilot-instructions.md
        copilot_instructions = output_dir / ".github" / "copilot-instructions.md"
        if copilot_instructions.exists():
            try:
                copilot_instructions.unlink()
            except Exception as e:
                print(f"WARN: Failed to remove {copilot_instructions}: {e}")

        # Clean up .github/instructions/ directory
        instructions_dir = output_dir / ".github" / "instructions"
        if instructions_dir.exists():
            try:
                shutil.rmtree(instructions_dir)
            except Exception as e:
                print(f"WARN: Failed to remove {instructions_dir}: {e}")

    def _generate_copilot_instructions(self, auto_rules: List, output_dir: Path) -> str:
        """Generate repository-wide copilot-instructions.md from auto-rules.

        Args:
            auto_rules: List of auto-rule Rule objects
            output_dir: Output directory (repository root)

        Returns:
            String content for copilot-instructions.md
        """
        sections = []

        # Header
        sections.extend(
            [
                "# GitHub Copilot Repository Instructions",
                "",
                "This repository uses AI-assisted development with structured behavioral rules.",
                "These instructions apply repository-wide to all Copilot Chat conversations and coding agent tasks.",
                "",
                "---",
                "",
            ]
        )

        # Combine all auto-rule content
        for rule in auto_rules:
            sections.extend(
                [
                    f"## {rule.title or rule.name}",
                    "",
                    rule.content,
                    "",
                    "---",
                    "",
                ]
            )

        # Footer
        sections.extend(
            [
                "## Additional Context",
                "",
                "- **Path-specific instructions**: See `.github/instructions/` for domain-specific guidance",
                "- **Local context**: AGENTS.md files throughout the repository provide directory-specific context",
                "",
            ]
        )

        return "\n".join(sections)

    def _generate_instruction_file(self, rule, output_dir: Path) -> str:
        """Generate a path-specific instruction file from a contextual rule.

        Args:
            rule: The contextual Rule object
            output_dir: Output directory (repository root)

        Returns:
            String content for the .instructions.md file
        """
        sections = []

        # Frontmatter with applyTo
        sections.append("---")

        # Add applyTo from rule's globs
        globs = rule.globs
        if globs:
            if len(globs) == 1:
                sections.append(f'applyTo: "{globs[0]}"')
            else:
                # Multiple globs: comma-separated in quotes
                globs_str = ", ".join(f'"{g}"' for g in globs)
                sections.append(f"applyTo: {globs_str}")
        else:
            # No globs specified, apply to all files
            sections.append('applyTo: "**"')

        sections.extend(["---", ""])

        # Title and content
        sections.extend(
            [
                f"# {rule.title or rule.name}",
                "",
                rule.content,
                "",
            ]
        )

        return "\n".join(sections)

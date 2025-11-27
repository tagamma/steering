import os
from pathlib import Path
from typing import Dict, List

from ..models import RuleSet


class ContinueDevAdapter:
    """Generate Continue.dev configuration by creating symlinks to source rule files.

    Uses the same philosophy as Cursor: symlink rules directly for clean single source of truth.
    Only creates special .md files for AGENTS files that need directory-specific globs.
    """

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
    ) -> Dict[str, str]:
        """Generate Continue.dev configuration files.

        Args:
            ruleset: The complete set of rules to generate from
            output_dir: Output directory (repository root)
            input_dir: Input directory containing rules/ subdirectory
            dry_run: If True, don't create actual files/symlinks

        Returns:
            Dict mapping generated file paths to their content/target
            Format: {file_path: "SYMLINK->{target}" or actual_content}
        """
        files: Dict[str, str] = {}

        output_dir = Path(output_dir)
        input_dir = Path(input_dir)

        # Create .continue/rules/ directory
        continue_rules_dir = output_dir / ".continue" / "rules"

        if not dry_run:
            continue_rules_dir.mkdir(parents=True, exist_ok=True)
            # Clean up old generated files
            self._cleanup_continue_rules(continue_rules_dir)

        # Symlink auto-rules directly
        for rule in ruleset.auto:
            symlink_name = f"auto-{rule.name}.md"
            symlink_path = continue_rules_dir / symlink_name

            # Calculate relative path from symlink to source file
            try:
                relative_target = os.path.relpath(rule.path, continue_rules_dir)
            except ValueError:
                # Can't make relative path (different drives on Windows)
                relative_target = str(rule.path)

            files[str(symlink_path.relative_to(output_dir))] = (
                f"SYMLINK->{relative_target}"
            )

            if not dry_run:
                self._create_symlink(symlink_path, relative_target)

        # Symlink contextual-rules directly
        for rule in ruleset.contextual:
            symlink_name = f"contextual-{rule.name}.md"
            symlink_path = continue_rules_dir / symlink_name

            # Calculate relative path from symlink to source file
            try:
                relative_target = os.path.relpath(rule.path, continue_rules_dir)
            except ValueError:
                relative_target = str(rule.path)

            files[str(symlink_path.relative_to(output_dir))] = (
                f"SYMLINK->{relative_target}"
            )

            if not dry_run:
                self._create_symlink(symlink_path, relative_target)

        # Process AGENTS files - these need special handling for directory scoping
        agents_files = self._process_agents_files(
            ruleset.agents, output_dir, continue_rules_dir, dry_run
        )
        files.update(agents_files)

        # Process @ references in AGENTS files (workaround for Continue.dev not embedding them)
        reference_files = self._process_agents_references(
            ruleset.agents, output_dir, dry_run
        )
        files.update(reference_files)

        return files

    def _cleanup_continue_rules(self, continue_rules_dir: Path):
        """Clean up old generated files in .continue/rules/ directory.

        Args:
            continue_rules_dir: Root .continue/rules/ directory
        """
        import shutil

        if continue_rules_dir.exists():
            for item in continue_rules_dir.iterdir():
                try:
                    if item.is_symlink() or item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    print(f"WARN: Failed to remove {item}: {e}")

    def _create_symlink(self, link_path: Path, target: str):
        """Create a symlink, replacing any existing file/symlink.

        Args:
            link_path: Path where the symlink should be created
            target: Target path (relative or absolute)
        """
        # Remove existing file/symlink if it exists
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()

        # Create the symlink
        link_path.symlink_to(target)

    def _process_agents_files(
        self,
        agents_rules: List,
        output_dir: Path,
        continue_rules_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """Process AGENTS files and create special .md files with directory-specific globs.

        AGENTS files need special handling because they're scattered throughout the repo
        but Continue only looks in .continue/rules/. We create .md files with globs
        patterns that scope them to their directory.

        @ references in AGENTS files are left as-is (not processed/embedded).

        Args:
            agents_rules: List of Rule objects for AGENTS files
            output_dir: Output directory (repository root)
            continue_rules_dir: .continue/rules/ directory
            dry_run: If True, don't create actual files

        Returns:
            Dict mapping file paths to their content
        """
        files: Dict[str, str] = {}

        for rule in agents_rules:
            # Generate kebab-case filename from the rule's path
            try:
                rel_path = rule.path.relative_to(output_dir)
            except ValueError:
                # File not under output_dir, skip it
                print(
                    f"WARN: AGENTS file {rule.path} not under output directory, skipping"
                )
                continue

            # Convert path to kebab-case name with agents- prefix
            # e.g., nix/services/grafana/AGENTS.md -> agents-nix-services-grafana.md
            parts = list(rel_path.parts[:-1])  # Exclude the filename itself

            if not parts:  # AGENTS.md is at repo root
                kebab_name = "agents-root.md"
            else:
                kebab_name = "agents-" + "-".join(parts) + ".md"

            rule_path = continue_rules_dir / kebab_name

            # Calculate directory glob pattern
            agents_dir = rule.path.parent
            try:
                agents_dir_rel = agents_dir.relative_to(output_dir)
                # Continue.dev uses glob patterns like "nix/services/grafana/**/*"
                glob_pattern = str(agents_dir_rel / "**" / "*")
            except ValueError:
                # Can't make relative path
                glob_pattern = "**/*"

            # Create markdown content with frontmatter and original content
            content = self._create_agents_content(rule, glob_pattern)

            files[str(rule_path.relative_to(output_dir))] = content

            if not dry_run:
                rule_path.parent.mkdir(parents=True, exist_ok=True)
                rule_path.write_text(content, encoding="utf-8")

        return files

    def _create_agents_content(self, rule, glob_pattern: str) -> str:
        """Create markdown content for an AGENTS file with scoped globs.

        Args:
            rule: The Rule object for the AGENTS file
            glob_pattern: Glob pattern to scope this rule to its directory

        Returns:
            String content for the markdown file
        """
        # Build frontmatter
        frontmatter_lines = ["---"]

        # Add name
        dir_name = rule.path.parent.name
        frontmatter_lines.append(f"name: Local context for {dir_name}")

        # Add description if present
        if rule.description:
            description = rule.description.replace('"', '\\"')
            frontmatter_lines.append(f'description: "{description}"')
        else:
            frontmatter_lines.append(
                f'description: "Directory-specific context for {dir_name}"'
            )

        # Add globs to scope to directory
        frontmatter_lines.append(f"globs: {glob_pattern}")

        # AGENTS files should not always apply (they apply via glob matching)
        frontmatter_lines.append("alwaysApply: false")

        frontmatter_lines.append("---")
        frontmatter_lines.append("")

        # Use the original content as-is, including any @ references
        # The @ references will be handled separately by _process_agents_references
        return "\n".join(frontmatter_lines) + "\n" + rule.content

    def _process_agents_references(
        self,
        agents_rules: List,
        output_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """Process @ references in AGENTS files and create ref-*.md files.

        This is a workaround for Continue.dev not automatically embedding @ references.
        All ref files are created in the root .continue/rules/ directory with unique
        path-based names (Continue.dev only supports one central rules directory).

        Args:
            agents_rules: List of Rule objects for AGENTS files
            output_dir: Output directory (repository root)
            dry_run: If True, don't create actual files

        Returns:
            Dict mapping file paths to their content
        """
        import re

        files: Dict[str, str] = {}

        # Root .continue/rules/ directory (Continue.dev only supports one location)
        continue_rules_dir = output_dir / ".continue" / "rules"

        for rule in agents_rules:
            # Find all @ references in the AGENTS file content
            references = re.findall(r"@([\w\-./]+\.[\w]+)", rule.content)

            if not references:
                continue  # No references to process

            # Get the AGENTS file's directory
            agents_dir = rule.path.parent

            # Get relative path from output_dir for unique naming and glob scoping
            try:
                agents_rel_dir = agents_dir.relative_to(output_dir)
                # Convert path to prefix for unique filename
                # e.g., nix/services/grafana -> nix-services-grafana
                path_prefix = str(agents_rel_dir).replace("/", "-")
                # Calculate directory glob pattern to scope to this directory
                glob_pattern = str(agents_rel_dir / "**" / "*")
            except ValueError:
                # Can't make relative path, use a generic prefix
                path_prefix = "external"
                glob_pattern = "**/*"

            for ref in references:
                # Resolve the referenced file path
                ref_path = agents_dir / ref

                if not ref_path.exists():
                    print(f"WARN: Referenced file {ref} not found in {agents_dir}")
                    continue

                try:
                    # Read the referenced file content
                    ref_content = ref_path.read_text(encoding="utf-8")
                except Exception as e:
                    print(f"WARN: Failed to read {ref_path}: {e}")
                    continue

                # Create unique filename with path prefix
                # e.g., ref-nix-services-grafana-README.md
                ref_basename = ref.replace("/", "-").replace(".", "-")
                if "." in ref:
                    parts = ref.split(".")
                    ref_basename = "-".join(parts[:-1])

                # Combine path prefix with ref basename for uniqueness
                ref_filename = f"ref-{path_prefix}-{ref_basename}.md"

                continue_ref_file = continue_rules_dir / ref_filename

                # Scope to the same directory as the AGENTS file using globs
                # This ensures the ref file only applies when working in that directory
                content_lines = [
                    "---",
                    f"name: Referenced content from {path_prefix}/{ref}",
                    'description: "Auto-embedded for Continue.dev @ reference workaround"',
                    f"globs: {glob_pattern}",
                    "alwaysApply: false",
                    "---",
                    "",
                    f"# Referenced: {ref}",
                    f"# Source: {agents_rel_dir}/AGENTS.md",
                    "",
                    "This file is auto-generated to work around Continue.dev not automatically",
                    "embedding @ references. It has exactly the same content as the actual file",
                    "being referenced so no need to read that one unless modifying it",
                    "(always modify the source file not this rule).",
                    "",
                    "---",
                    "",
                    ref_content,
                ]
                content = "\n".join(content_lines)

                # Track the file
                try:
                    rel_continue_file = continue_ref_file.relative_to(output_dir)
                    files[str(rel_continue_file)] = content
                except ValueError:
                    files[str(continue_ref_file)] = content

                # Write the file
                if not dry_run:
                    continue_ref_file.parent.mkdir(parents=True, exist_ok=True)
                    continue_ref_file.write_text(content, encoding="utf-8")

        return files

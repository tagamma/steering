import os
from pathlib import Path
from typing import Dict, List, Optional

from ..discovery import Discovery
from ..models import RuleSet


class CursorAdapter:
    """Generate Cursor configuration by creating symlinks to source rule files."""

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
        discovery: Optional[Discovery] = None,
    ) -> Dict[str, str]:
        """Generate Cursor configuration files.

        Args:
            ruleset: The complete set of rules to generate from
            output_dir: Output directory (repository root)
            input_dir: Input directory containing rules/ subdirectory
            dry_run: If True, don't create actual files/symlinks
            discovery: File discovery for repo-wide cleanup scans

        Returns:
            Dict mapping generated file paths to their content/target
            Format: {file_path: "SYMLINK->{target}" or actual_content}
        """
        files: Dict[str, str] = {}

        output_dir = Path(output_dir)
        input_dir = Path(input_dir)
        if discovery is None:
            discovery = Discovery.fallback(output_dir)

        # Create .cursor/rules/ directory
        cursor_rules_dir = output_dir / ".cursor" / "rules"

        if not dry_run:
            cursor_rules_dir.mkdir(parents=True, exist_ok=True)
            # Clean up old generated files
            self._cleanup_cursor_rules(cursor_rules_dir, discovery)

        # Symlink auto-rules and process their @ references
        for rule in ruleset.auto:
            symlink_name = f"auto-{rule.name}.mdc"
            symlink_path = cursor_rules_dir / symlink_name

            # Calculate relative path from symlink to source file
            try:
                relative_target = os.path.relpath(rule.path, cursor_rules_dir)
            except ValueError:
                # Can't make relative path (different drives on Windows)
                relative_target = str(rule.path)

            files[str(symlink_path.relative_to(output_dir))] = (
                f"SYMLINK->{relative_target}"
            )

            if not dry_run:
                self._create_symlink(symlink_path, relative_target)

            # Process @ references in this auto-rule
            ref_files = self._process_rule_references(
                rule, output_dir, cursor_rules_dir, dry_run
            )
            files.update(ref_files)

        # Symlink contextual-rules and process their @ references
        for rule in ruleset.contextual:
            symlink_name = f"contextual-{rule.name}.mdc"
            symlink_path = cursor_rules_dir / symlink_name

            # Calculate relative path from symlink to source file
            try:
                relative_target = os.path.relpath(rule.path, cursor_rules_dir)
            except ValueError:
                relative_target = str(rule.path)

            files[str(symlink_path.relative_to(output_dir))] = (
                f"SYMLINK->{relative_target}"
            )

            if not dry_run:
                self._create_symlink(symlink_path, relative_target)

            # Process @ references in this contextual rule
            ref_files = self._process_rule_references(
                rule, output_dir, cursor_rules_dir, dry_run
            )
            files.update(ref_files)

        # AI-NOTE: AGENTS files are natively supported by Cursor (root and
        # nested, as of v1.7+), so no per-AGENTS wrapper .mdc files are
        # generated. Cursor still doesn't embed @ references found inside
        # AGENTS.md files, so we create ref-*.mdc files in distributed
        # .cursor/rules/ directories next to them (see
        # _process_agents_references below).
        reference_files = self._process_agents_references(
            ruleset.agents, output_dir, dry_run
        )
        files.update(reference_files)

        # Symlink skills into .cursor/skills/ for Cursor discovery
        skill_files = self._process_skills(
            ruleset.skills, output_dir, dry_run
        )
        files.update(skill_files)

        return files

    def _cleanup_cursor_rules(self, cursor_rules_dir: Path, discovery: Discovery):
        """Clean up old generated files in .cursor/rules/ directories.

        Removes:
        - All files in root .cursor/rules/ (they're all generated)
        - Distributed .cursor/rules/ directories (ref files) next to code git
          knows about; .cursor directories inside gitignored checkouts are
          left alone

        Args:
            cursor_rules_dir: Root .cursor/rules/ directory
            discovery: File discovery rooted at the output directory
        """
        import shutil

        # Clean root .cursor/rules/ directory
        if cursor_rules_dir.exists():
            for item in cursor_rules_dir.iterdir():
                try:
                    if item.is_symlink() or item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    print(f"WARN: Failed to remove {item}: {e}")

        # Clean up distributed .cursor/rules/ directories
        for cursor_dir in discovery.cleanup_dirs(".cursor/rules"):
            # Skip the root one we just cleaned
            if cursor_dir == cursor_rules_dir:
                continue

            try:
                if cursor_dir.exists() and cursor_dir.is_dir():
                    shutil.rmtree(cursor_dir)
            except Exception as e:
                print(f"WARN: Failed to remove {cursor_dir}: {e}")

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

    def _process_rule_references(
        self,
        rule,
        output_dir: Path,
        cursor_rules_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """Process @ references in auto/contextual rules and create ref-*.mdc files.

        For auto/contextual rules, the generated ref files inherit the parent rule's
        globs and alwaysApply settings.

        Args:
            rule: The Rule object containing @ references
            output_dir: Output directory (repository root)
            cursor_rules_dir: .cursor/rules/ directory at repo root
            dry_run: If True, don't create actual files

        Returns:
            Dict mapping file paths to their content
        """
        import re

        files: Dict[str, str] = {}

        # Find all @ references in the rule content
        references = re.findall(r"@([\w\-./]+\.[\w]+)", rule.content)

        if not references:
            return files

        # Get the rule's directory (for resolving relative references)
        rule_dir = rule.path.parent

        for ref in references:
            # Resolve the referenced file path
            ref_path = rule_dir / ref

            if not ref_path.exists():
                print(
                    f"WARN: Referenced file {ref} not found in {rule_dir} (from rule {rule.name})"
                )
                continue

            try:
                ref_content = ref_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"WARN: Failed to read {ref_path}: {e}")
                continue

            # Create ref-*.mdc filename
            ref_filename = ref.replace("/", "-").replace(".", "-")
            if "." in ref:
                parts = ref.split(".")
                ref_filename = f"ref-{'-'.join(parts[:-1])}.mdc"
            else:
                ref_filename = f"ref-{ref_filename}.mdc"

            cursor_ref_file = cursor_rules_dir / ref_filename

            # Inherit globs and alwaysApply from parent rule
            globs_value = rule.frontmatter.get("globs", [])
            always_apply = rule.frontmatter.get("alwaysApply", False)

            # Format globs properly for YAML
            if isinstance(globs_value, list):
                globs_str = str(globs_value)
            elif isinstance(globs_value, str):
                globs_str = f"{globs_value}"
            else:
                globs_str = "[]"

            # Create .mdc content
            content_lines = [
                "---",
                f"description: Referenced content from {ref} (auto-embedded for Cursor bug workaround)",
                f"globs: {globs_str}",
                f"alwaysApply: {str(always_apply).lower()}",
                "---",
                "",
                f"# Referenced: {ref}",
                "",
                "This file is auto-generated to work around a Cursor v1.7 bug",
                "where @ references in AGENTS.md files aren't embedded into context automatically. It has exactly the same content as the actual file being referenced so no need to read that one unless modifying it (always modify the source file not this rule).",
                "",
                "---",
                "",
                ref_content,
            ]
            content = "\n".join(content_lines)

            # Track the file
            try:
                rel_cursor_file = cursor_ref_file.relative_to(output_dir)
                files[str(rel_cursor_file)] = content
            except ValueError:
                files[str(cursor_ref_file)] = content

            # Write the file
            if not dry_run:
                cursor_ref_file.parent.mkdir(parents=True, exist_ok=True)
                cursor_ref_file.write_text(content, encoding="utf-8")

        return files

    def _process_skills(
        self,
        skills: List,
        output_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """Symlink skill directories into .cursor/skills/ for Cursor discovery.

        Each skill gets its own subdirectory with SKILL.md symlinked from the
        source location.

        Args:
            skills: List of Skill objects
            output_dir: Output directory (repository root)
            dry_run: If True, don't create actual symlinks

        Returns:
            Dict mapping file paths to their symlink targets
        """
        files: Dict[str, str] = {}

        if not skills:
            return files

        cursor_skills_dir = output_dir / ".cursor" / "skills"

        if not dry_run:
            # Clean up old generated skill symlinks
            if cursor_skills_dir.exists():
                import shutil
                shutil.rmtree(cursor_skills_dir)
            cursor_skills_dir.mkdir(parents=True, exist_ok=True)

        for skill in skills:
            skill_dir = cursor_skills_dir / skill.name
            skill_link = skill_dir / "SKILL.md"

            # Calculate relative path from the symlink location to the source
            try:
                relative_target = os.path.relpath(
                    skill.path.resolve(), skill_dir
                )
            except ValueError:
                relative_target = str(skill.path.resolve())

            try:
                rel_link = skill_link.relative_to(output_dir)
                files[str(rel_link)] = f"SYMLINK->{relative_target}"
            except ValueError:
                files[str(skill_link)] = f"SYMLINK->{relative_target}"

            if not dry_run:
                skill_dir.mkdir(parents=True, exist_ok=True)
                self._create_symlink(skill_link, relative_target)

        return files

    def _process_agents_references(
        self,
        agents_rules: List,
        output_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """Process @ references in AGENTS files and create ref-*.mdc files.

        This is a workaround for Cursor v1.7 bug where @ references in AGENTS.md
        files aren't automatically embedded into context. We create distributed
        .cursor/rules/ directories next to AGENTS files with ref-*.mdc files that
        include the referenced content.

        Args:
            agents_rules: List of Rule objects for AGENTS files
            output_dir: Output directory (repository root)
            dry_run: If True, don't create actual files

        Returns:
            Dict mapping file paths to their content
        """
        import re

        files: Dict[str, str] = {}

        for rule in agents_rules:
            # Find all @ references in the AGENTS file content
            # Match @filename.ext or @path/to/file.ext
            references = re.findall(r"@([\w\-./]+\.[\w]+)", rule.content)

            if not references:
                continue  # No references to process

            # Create .cursor/rules/ directory next to the AGENTS file
            agents_dir = rule.path.parent
            local_cursor_dir = agents_dir / ".cursor" / "rules"

            for ref in references:
                # Resolve the referenced file path
                # References are relative to the AGENTS file's directory
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

                # Create a ref-*.mdc filename (clean up the path)
                ref_filename = ref.replace("/", "-").replace(".", "-")
                # Keep the original extension at the end
                if "." in ref:
                    parts = ref.split(".")
                    ref_filename = f"ref-{'-'.join(parts[:-1])}.mdc"
                else:
                    ref_filename = f"ref-{ref_filename}.mdc"

                cursor_ref_file = local_cursor_dir / ref_filename

                # For AGENTS.md references: empty globs and alwaysApply: true
                # This makes them apply to everything in their subdirectory
                # Create .mdc content with frontmatter
                content_lines = [
                    "---",
                    f"description: Referenced content from {ref} (auto-embedded for Cursor bug workaround)",
                    "globs: ",
                    "alwaysApply: true",
                    "---",
                    "",
                    f"# Referenced: {ref}",
                    "",
                    "This file is auto-generated to work around a Cursor v1.7 bug",
                    "where @ references in AGENTS.md files aren't embedded into context automatically. It has exactly the same content as the actual file being referenced so no need to read that one unless modifying it (always modify the source file not this rule).",
                    "",
                    "---",
                    "",
                    ref_content,
                ]
                content = "\n".join(content_lines)

                # Track the file
                try:
                    rel_cursor_file = cursor_ref_file.relative_to(output_dir)
                    files[str(rel_cursor_file)] = content
                except ValueError:
                    files[str(cursor_ref_file)] = content

                # Write the file
                if not dry_run:
                    cursor_ref_file.parent.mkdir(parents=True, exist_ok=True)
                    cursor_ref_file.write_text(content, encoding="utf-8")

        return files

    def _generate_conflict_report(
        self, existing_files: List[str], new_files: Dict[str, str]
    ) -> List[str]:
        """Check for filename conflicts.

        Args:
            existing_files: List of already-generated file paths
            new_files: Dict of new files to be generated

        Returns:
            List of conflict error messages
        """
        conflicts = []

        existing_set = set(existing_files)
        for new_file in new_files:
            if new_file in existing_set:
                conflicts.append(
                    f"CONFLICT: File '{new_file}' would be generated multiple times"
                )

        # Check for conflicts within new_files
        if len(set(new_files.keys())) != len(new_files):
            duplicates = [k for k in new_files if list(new_files.keys()).count(k) > 1]
            for dup in set(duplicates):
                conflicts.append(
                    f"CONFLICT: File '{dup}' generated multiple times in this run"
                )

        return conflicts

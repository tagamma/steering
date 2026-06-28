import os
from pathlib import Path
from typing import Dict, List, Optional

from ..discovery import Discovery
from ..models import RuleSet
from ..references import extract_references

_REF_MAX_DEPTH = 3
_REF_MAX_BYTES = 64 * 1024


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

        cursor_rules_dir = output_dir / ".cursor" / "rules"

        if not dry_run:
            cursor_rules_dir.mkdir(parents=True, exist_ok=True)
            self._cleanup_cursor_rules(cursor_rules_dir, discovery)

        for rule in ruleset.auto:
            symlink_name = f"auto-{rule.name}.mdc"
            symlink_path = cursor_rules_dir / symlink_name

            try:
                relative_target = os.path.relpath(rule.path, cursor_rules_dir)
            except ValueError:
                relative_target = str(rule.path)

            files[str(symlink_path.relative_to(output_dir))] = (
                f"SYMLINK->{relative_target}"
            )

            if not dry_run:
                self._create_symlink(symlink_path, relative_target)

            ref_files = self._process_rule_references(
                rule, output_dir, cursor_rules_dir, dry_run
            )
            files.update(ref_files)

        for rule in ruleset.contextual:
            symlink_name = f"contextual-{rule.name}.mdc"
            symlink_path = cursor_rules_dir / symlink_name

            try:
                relative_target = os.path.relpath(rule.path, cursor_rules_dir)
            except ValueError:
                relative_target = str(rule.path)

            files[str(symlink_path.relative_to(output_dir))] = (
                f"SYMLINK->{relative_target}"
            )

            if not dry_run:
                self._create_symlink(symlink_path, relative_target)

            ref_files = self._process_rule_references(
                rule, output_dir, cursor_rules_dir, dry_run
            )
            files.update(ref_files)

        # Root AGENTS.md: loaded natively but @refs not expanded → alwaysApply ref-*.mdc.
        # Nested AGENTS.md: not loaded → glob-scoped wrapper .mdc in .cursor/rules/.
        files.update(
            self._process_agents_references(ruleset.agents, output_dir, dry_run)
        )
        files.update(
            self._process_nested_agents_wrappers(
                ruleset.agents, output_dir, cursor_rules_dir, dry_run
            )
        )

        # Symlink skills into .cursor/skills/
        skill_files = self._process_skills(
            ruleset.skills, output_dir, dry_run
        )
        files.update(skill_files)

        return files

    def _cleanup_cursor_rules(self, cursor_rules_dir: Path, discovery: Discovery):
        """Clear root .cursor/rules/ and distributed ref dirs (skips gitignored trees)."""
        import shutil

        if cursor_rules_dir.exists():
            for item in cursor_rules_dir.iterdir():
                try:
                    if item.is_symlink() or item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    print(f"WARN: Failed to remove {item}: {e}")

        for cursor_dir in discovery.cleanup_dirs(".cursor/rules"):
            if cursor_dir == cursor_rules_dir:
                continue

            try:
                if cursor_dir.exists() and cursor_dir.is_dir():
                    shutil.rmtree(cursor_dir)
            except Exception as e:
                print(f"WARN: Failed to remove {cursor_dir}: {e}")

    def _create_symlink(self, link_path: Path, target: str):
        """Create a symlink, replacing any existing file/symlink."""
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(target)

    def _process_rule_references(
        self,
        rule,
        output_dir: Path,
        cursor_rules_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """Expand @refs in auto/contextual rules to ref-*.mdc (inherits parent globs/alwaysApply)."""
        files: Dict[str, str] = {}

        # Shared extractor: skips fenced code blocks and ignores emails/user@host.
        references = [r.target for r in extract_references(rule.content) if r.kind == "at"]
        if not references:
            return files

        rule_dir = rule.path.parent
        for ref in references:
            # Resolve relative to the rule's dir, falling back to the repo root.
            ref_path = rule_dir / ref
            if not ref_path.exists():
                ref_path = output_dir / ref

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

            ref_filename = ref.replace("/", "-").replace(".", "-")
            if "." in ref:
                parts = ref.split(".")
                ref_filename = f"ref-{'-'.join(parts[:-1])}.mdc"
            else:
                ref_filename = f"ref-{ref_filename}.mdc"

            cursor_ref_file = cursor_rules_dir / ref_filename

            globs_value = rule.frontmatter.get("globs", [])
            always_apply = rule.frontmatter.get("alwaysApply", False)
            if isinstance(globs_value, list):
                globs_str = str(globs_value)
            elif isinstance(globs_value, str):
                globs_str = f"{globs_value}"
            else:
                globs_str = "[]"

            content_lines = [
                "---",
                f"description: embedded @{ref}",
                f"globs: {globs_str}",
                f"alwaysApply: {str(always_apply).lower()}",
                "---",
                "",
                f"# @{ref}",
                "",
                "Auto-generated embed (Cursor doesn't expand @refs). Edit the source, not this file.",
                "",
                ref_content,
            ]
            content = "\n".join(content_lines)
            try:
                rel_cursor_file = cursor_ref_file.relative_to(output_dir)
                files[str(rel_cursor_file)] = content
            except ValueError:
                files[str(cursor_ref_file)] = content

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
        """Symlink skills into .cursor/skills/ (one subdir per skill)."""
        files: Dict[str, str] = {}

        if not skills:
            return files

        cursor_skills_dir = output_dir / ".cursor" / "skills"

        if not dry_run:
            if cursor_skills_dir.exists():
                import shutil
                shutil.rmtree(cursor_skills_dir)
            cursor_skills_dir.mkdir(parents=True, exist_ok=True)

        for skill in skills:
            skill_dir = cursor_skills_dir / skill.name
            skill_link = skill_dir / "SKILL.md"

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
        """Embed root AGENTS.md @refs as alwaysApply ref-*.mdc."""
        files: Dict[str, str] = {}

        for rule in agents_rules:
            if rule.path.parent.resolve() != output_dir.resolve():
                continue  # nested AGENTS.md handled by _process_nested_agents_wrappers

            references = [
                r.target for r in extract_references(rule.content) if r.kind == "at"
            ]
            if not references:
                continue

            agents_dir = rule.path.parent
            local_cursor_dir = agents_dir / ".cursor" / "rules"

            for ref in references:
                # Relative to the AGENTS file's dir, falling back to the repo root.
                ref_path = agents_dir / ref
                if not ref_path.exists():
                    ref_path = output_dir / ref

                if not ref_path.exists():
                    print(f"WARN: Referenced file {ref} not found in {agents_dir}")
                    continue

                try:
                    ref_content = ref_path.read_text(encoding="utf-8")
                except Exception as e:
                    print(f"WARN: Failed to read {ref_path}: {e}")
                    continue

                ref_filename = ref.replace("/", "-").replace(".", "-")
                if "." in ref:
                    parts = ref.split(".")
                    ref_filename = f"ref-{'-'.join(parts[:-1])}.mdc"
                else:
                    ref_filename = f"ref-{ref_filename}.mdc"

                cursor_ref_file = local_cursor_dir / ref_filename

                content_lines = [
                    "---",
                    f"description: embedded @{ref}",
                    "globs: ",
                    "alwaysApply: true",
                    "---",
                    "",
                    f"# @{ref}",
                    "",
                    "Auto-generated embed (Cursor doesn't expand @refs). Edit the source, not this file.",
                    "",
                    ref_content,
                ]
                content = "\n".join(content_lines)
                try:
                    rel_cursor_file = cursor_ref_file.relative_to(output_dir)
                    files[str(rel_cursor_file)] = content
                except ValueError:
                    files[str(cursor_ref_file)] = content

                if not dry_run:
                    cursor_ref_file.parent.mkdir(parents=True, exist_ok=True)
                    cursor_ref_file.write_text(content, encoding="utf-8")

        return files

    def _process_nested_agents_wrappers(
        self,
        agents_rules: List,
        output_dir: Path,
        cursor_rules_dir: Path,
        dry_run: bool,
    ) -> Dict[str, str]:
        """One glob-scoped wrapper .mdc per nested AGENTS.md (body + expanded @refs)."""
        files: Dict[str, str] = {}
        out_resolved = output_dir.resolve()

        for rule in agents_rules:
            agents_dir = rule.path.parent
            if agents_dir.resolve() == out_resolved:
                continue  # root handled by _process_agents_references

            try:
                reldir = agents_dir.resolve().relative_to(out_resolved).as_posix()
            except ValueError:
                continue  # outside the output tree

            sanitized = reldir.replace("/", "-").replace(".", "-")
            wrapper_path = cursor_rules_dir / f"agents-{sanitized}.mdc"

            seen: set[Path] = {rule.path.resolve()}
            expansion = self._expand_references(rule.content, agents_dir, seen)

            content = "\n".join(
                [
                    "---",
                    f"description: {reldir} (nested AGENTS.md)",
                    f"globs: {reldir}/**",
                    "alwaysApply: false",
                    "---",
                    "",
                    "<!-- steering: nested AGENTS.md wrapper. Edit source AGENTS.md, not this file. -->",
                    "",
                    rule.content,
                    expansion,
                ]
            )

            try:
                files[str(wrapper_path.relative_to(output_dir))] = content
            except ValueError:
                files[str(wrapper_path)] = content

            if not dry_run:
                wrapper_path.parent.mkdir(parents=True, exist_ok=True)
                wrapper_path.write_text(content, encoding="utf-8")

        return files

    def _expand_references(
        self,
        content: str,
        base_dir: Path,
        seen: "set[Path]",
        depth: int = 1,
    ) -> str:
        """Recursively embed @ref contents resolved from base_dir; seen dedupes/cycle-breaks."""
        if depth > _REF_MAX_DEPTH:
            return ""
        out: List[str] = []
        for ref in (r.target for r in extract_references(content) if r.kind == "at"):
            ref_path = (base_dir / ref).resolve()
            if ref_path in seen:
                continue
            seen.add(ref_path)
            if not ref_path.is_file():
                continue
            try:
                ref_content = ref_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"WARN: Failed to read {ref_path}: {e}")
                continue
            clipped = (
                ref_content
                if len(ref_content) <= _REF_MAX_BYTES
                else ref_content[:_REF_MAX_BYTES] + "\n…[truncated]"
            )
            out.append(f"\n\n----- expanded @{ref} -----\n{clipped}")
            out.append(
                self._expand_references(ref_content, ref_path.parent, seen, depth + 1)
            )
        return "".join(out)

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

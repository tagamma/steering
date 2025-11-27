from pathlib import Path
from typing import List
import glob as glob_module

from .models import Rule, RuleSet, load_rule_from_file
from .config import Config


class RuleLoader:
    """Loads rules from the filesystem based on configuration."""

    def __init__(self, config: Config, input_dir: Path):
        """Initialize the rule loader.

        Args:
            config: Configuration object
            input_dir: Base directory containing rules/ subdirectory
        """
        self.config = config
        self.input_dir = Path(input_dir)
        self.rules_dir = self.input_dir / "rules"

    def load_auto_rules(self) -> List[Rule]:
        """Load all auto-rules from the configured directory.

        Returns:
            List of Rule objects for auto-rules
        """
        rules = []
        pattern = str(self.input_dir / self.config.auto_rules_glob)

        for file_path in sorted(
            Path(p) for p in glob_module.glob(pattern, recursive=True)
        ):
            if file_path.is_file():
                try:
                    rule = load_rule_from_file(file_path, "auto")
                    rules.append(rule)
                except Exception as e:
                    print(f"WARN: Failed to load auto-rule {file_path}: {e}")

        return rules

    def load_contextual_rules(self) -> List[Rule]:
        """Load all contextual rules from the configured directory.

        Returns:
            List of Rule objects for contextual rules
        """
        rules = []
        pattern = str(self.input_dir / self.config.contextual_rules_glob)

        for file_path in sorted(
            Path(p) for p in glob_module.glob(pattern, recursive=True)
        ):
            if file_path.is_file():
                try:
                    rule = load_rule_from_file(file_path, "contextual")
                    rules.append(rule)
                except Exception as e:
                    print(
                        f"WARN: Failed to load contextual rule {file_path}: {e}"
                    )

        return rules

    def load_agents_files(self, output_dir: Path) -> List[Rule]:
        """Discover and load AGENTS.{md,mdc} files throughout the repository.

        Args:
            output_dir: The output directory (repository root) to search from

        Returns:
            List of Rule objects for discovered AGENTS files
        """
        rules = []
        output_dir = Path(output_dir)

        # Expand the agents glob pattern to support .md and .mdc
        # Convert pattern like "**/AGENTS.{md,mdc}" to actual glob patterns
        base_pattern = self.config.agents_glob

        # Handle brace expansion manually since glob doesn't support it well
        patterns = []
        if "{" in base_pattern and "}" in base_pattern:
            # Extract the brace content
            start = base_pattern.index("{")
            end = base_pattern.index("}")
            prefix = base_pattern[:start]
            suffix = base_pattern[end + 1 :]
            options = base_pattern[start + 1 : end].split(",")

            for option in options:
                patterns.append(prefix + option.strip() + suffix)
        else:
            patterns = [base_pattern]

        # Search for AGENTS files
        for pattern in patterns:
            full_pattern = str(output_dir / pattern)
            for file_path in glob_module.glob(full_pattern, recursive=True):
                file_path = Path(file_path)

                # Skip if in ignored directory
                if self._is_ignored(file_path, output_dir):
                    continue

                if file_path.is_file():
                    try:
                        rule = load_rule_from_file(file_path, "agents")
                        rules.append(rule)
                    except Exception as e:
                        print(
                            f"WARN: Failed to load AGENTS file {file_path}: {e}"
                        )

        return sorted(rules, key=lambda r: str(r.path))

    def _is_ignored(self, file_path: Path, base_dir: Path) -> bool:
        """Check if a file path should be ignored based on configured ignore patterns.

        Args:
            file_path: The file path to check
            base_dir: The base directory for relative path calculation

        Returns:
            True if the file should be ignored
        """
        try:
            relative_path = file_path.relative_to(base_dir)
        except ValueError:
            # Path is not relative to base_dir
            return False

        parts = relative_path.parts

        for ignored_dir in self.config.ignored_directories:
            # Remove glob patterns if present
            ignored_dir = ignored_dir.rstrip("/*")

            # Check if any part of the path matches an ignored directory
            for part in parts:
                if part == ignored_dir or part.startswith(ignored_dir):
                    return True

                # Handle wildcard patterns
                if "*" in ignored_dir:
                    import fnmatch

                    if fnmatch.fnmatch(part, ignored_dir):
                        return True

        return False

    def load_all_rules(self, output_dir: Path) -> RuleSet:
        """Load all rules (auto, contextual, and agents).

        Args:
            output_dir: The output directory (repository root) for discovering AGENTS files

        Returns:
            A RuleSet containing all loaded rules
        """
        auto_rules = self.load_auto_rules()
        contextual_rules = self.load_contextual_rules()
        agents_rules = self.load_agents_files(output_dir)

        # Load included rules if specified
        for included_path in self.config.included_rules:
            rule_path = self.input_dir / included_path
            if not rule_path.exists():
                # Try resolving from output directory (for relative paths)
                rule_path = output_dir / included_path

            if rule_path.exists():
                # Determine rule type based on path
                if "auto-rules" in str(rule_path):
                    rule = load_rule_from_file(rule_path, "auto")
                    auto_rules.append(rule)
                elif "contextual-rules" in str(rule_path):
                    rule = load_rule_from_file(rule_path, "contextual")
                    contextual_rules.append(rule)
                # NOTE: agents files are handled separately, not through included_rules
            else:
                print(f"WARN: Included rule not found: {included_path}")

        return RuleSet(
            auto=auto_rules, contextual=contextual_rules, agents=agents_rules
        )

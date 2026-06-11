from pathlib import Path
from typing import List, Optional
import glob as glob_module

from .models import Rule, RuleSet, Skill, load_rule_from_file, load_skill_from_file
from .config import Config
from .discovery import Discovery, expand_braces, resolve_discovery_mode


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

    def load_agents_files(self, discovery: Discovery) -> List[Rule]:
        """Discover and load AGENTS.{md,mdc} files throughout the repository.

        Discovery is mode-aware: in git mode only git-tracked files are
        considered; in filesystem mode an ignore-pruned walk (that never
        follows directory symlinks) is used.

        Args:
            discovery: Discovery rooted at the output directory (repo root)

        Returns:
            List of Rule objects for discovered AGENTS files
        """
        # Expand the agents glob pattern to support .md and .mdc
        patterns = expand_braces(self.config.agents_glob)

        rules = []
        for file_path in discovery.files(patterns):
            try:
                rule = load_rule_from_file(file_path, "agents")
                rules.append(rule)
            except Exception as e:
                print(f"WARN: Failed to load AGENTS file {file_path}: {e}")

        untracked = discovery.untracked_matches(patterns)
        if untracked:
            print(
                f"WARN: Skipped {len(untracked)} untracked AGENTS file(s); "
                "`git add` them or run with --no-git to include them:"
            )
            for path in untracked:
                print(f"  - {path}")

        return sorted(rules, key=lambda r: str(r.path))

    def load_skills(self) -> List[Skill]:
        """Load all skills from the configured directory.

        Skills are SKILL.md files in subdirectories. The parent directory name
        becomes the skill name. Symlinks are followed, so skills can be defined
        elsewhere and linked into the skills directory.

        Returns:
            List of Skill objects
        """
        skills = []
        pattern = str(self.input_dir / self.config.skills_glob)

        for file_path in sorted(
            Path(p) for p in glob_module.glob(pattern, recursive=True)
        ):
            # Follow symlinks for existence check -- the source dir might be
            # a symlink to a skill defined elsewhere in the repo
            if file_path.is_file() or (file_path.is_symlink() and file_path.resolve().is_file()):
                try:
                    skill = load_skill_from_file(file_path)
                    skills.append(skill)
                except Exception as e:
                    print(f"WARN: Failed to load skill {file_path}: {e}")

        return skills

    def load_all_rules(
        self, output_dir: Path, discovery: Optional[Discovery] = None
    ) -> RuleSet:
        """Load all rules (auto, contextual, agents) and skills.

        Args:
            output_dir: The output directory (repository root) for discovering AGENTS files
            discovery: File discovery for repo-wide scans. If None, one is
                built from the config's discovery setting (which may raise
                DiscoveryError when output_dir is not a git work tree).

        Returns:
            A RuleSet containing all loaded rules and skills
        """
        output_dir = Path(output_dir)
        if discovery is None:
            mode = resolve_discovery_mode(self.config.discovery, False, output_dir)
            discovery = Discovery(output_dir, mode, self.config.ignored_directories)

        auto_rules = self.load_auto_rules()
        contextual_rules = self.load_contextual_rules()
        agents_rules = self.load_agents_files(discovery)
        skills = self.load_skills()

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
            auto=auto_rules, contextual=contextual_rules, agents=agents_rules,
            skills=skills,
        )

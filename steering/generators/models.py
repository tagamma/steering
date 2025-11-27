from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import yaml


@dataclass
class Rule:
    """Represents a single AI rule."""

    name: str  # Rule identifier (filename without extension)
    type: str  # Rule category: "auto", "contextual", or "agents"
    path: Path  # Full path to the source file
    frontmatter: Dict[str, Any]  # YAML frontmatter metadata
    content: str  # Markdown content

    @property
    def title(self) -> str:
        """Extract title from the first line of content."""
        first_line = self.content.split("\n")[0] if self.content else ""
        # Remove markdown heading markers
        return first_line.lstrip("#").strip()

    @property
    def description(self) -> str:
        """Get the description from frontmatter."""
        return self.frontmatter.get("description", "")

    @property
    def always_apply(self) -> bool:
        """Check if this rule should always be applied."""
        return self.frontmatter.get("alwaysApply", False)

    @property
    def globs(self) -> List[str]:
        """Get the glob patterns this rule applies to."""
        globs = self.frontmatter.get("globs", [])
        if isinstance(globs, str):
            globs = [globs]
        return globs if globs else []


@dataclass
class RuleSet:
    """Collection of rules for generation."""

    auto: List[Rule]  # Auto-rules (always apply)
    contextual: List[Rule]  # Contextual rules (apply based on concern)
    agents: List[Rule]  # Discovered AGENTS.{md,mdc} files

    @property
    def all_rules(self) -> List[Rule]:
        """Get all rules combined."""
        return self.auto + self.contextual + self.agents


def parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: The full file content

    Returns:
        A tuple of (frontmatter_dict, body_content)
        If no frontmatter is present, returns ({}, content)
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        # Malformed frontmatter, treat as no frontmatter
        return {}, content

    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        # Invalid YAML, treat as no frontmatter
        return {}, content

    body = parts[2].strip()
    return frontmatter, body


def load_rule_from_file(file_path: Path, rule_type: str) -> Rule:
    """Load a single rule from a file.

    Args:
        file_path: Path to the rule file
        rule_type: Type of rule ("auto", "contextual", or "agents")

    Returns:
        A Rule object

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file can't be parsed
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Rule file not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Failed to read {file_path}: {e}")

    frontmatter, body = parse_frontmatter(content)

    # Use stem (filename without extension) as the rule name
    name = file_path.stem

    return Rule(
        name=name,
        type=rule_type,
        path=file_path,
        frontmatter=frontmatter,
        content=body,
    )


def validate_rule(rule: Rule) -> List[str]:
    """Validate a rule and return list of validation errors.

    Args:
        rule: The rule to validate

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # AGENTS files don't require description (may not have frontmatter at all)
    if rule.type != "agents" and not rule.description:
        errors.append(
            f"Rule '{rule.name}' missing required 'description' in frontmatter"
        )

    # Auto-rules and contextual-rules require globs field for Cursor compatibility
    if rule.type in ("auto", "contextual"):
        if "globs" not in rule.frontmatter:
            errors.append(
                f"Rule '{rule.name}' missing 'globs' field in frontmatter (required for Cursor)"
            )
        else:
            # Validate globs format if present
            globs = rule.frontmatter["globs"]
            if globs is not None and not isinstance(globs, (list, str)):
                errors.append(
                    f"Rule '{rule.name}' has invalid 'globs' field (must be string, list, or empty)"
                )

    # Auto-rules specific validation
    if rule.type == "auto":
        if not rule.always_apply:
            errors.append(
                f"Auto-rule '{rule.name}' must have 'alwaysApply: true' in frontmatter"
            )
        if "alwaysApply" not in rule.frontmatter:
            errors.append(
                f"Auto-rule '{rule.name}' missing 'alwaysApply' field in frontmatter"
            )

    # Contextual-rules specific validation
    if rule.type == "contextual":
        if rule.always_apply:
            errors.append(
                f"Contextual rule '{rule.name}' should have 'alwaysApply: false' in frontmatter"
            )

    # AGENTS files don't require globs (they're scoped by directory)
    # but if they have globs, validate the format
    if rule.type == "agents" and "globs" in rule.frontmatter:
        globs = rule.frontmatter["globs"]
        if globs is not None and not isinstance(globs, (list, str)):
            errors.append(
                f"Rule '{rule.name}' has invalid 'globs' field (must be string or list)"
            )

    return errors


def validate_ruleset(ruleset: RuleSet) -> List[str]:
    """Validate a complete ruleset and check for conflicts.

    Args:
        ruleset: The ruleset to validate

    Returns:
        List of error and warning messages
    """
    issues = []

    # Validate individual rules
    for rule in ruleset.all_rules:
        errors = validate_rule(rule)
        issues.extend(errors)

    # Check for duplicate rule names across types
    # For AGENTS files, use full path since they all have the same name
    all_names = {}
    for rule in ruleset.all_rules:
        # Use path for AGENTS files, name for others
        key = str(rule.path) if rule.type == "agents" else rule.name

        if key in all_names:
            issues.append(
                f"CONFLICT: Rule name '{rule.name}' exists in both "
                f"{all_names[key]} and {rule.type}"
            )
        else:
            all_names[key] = rule.type

    return issues

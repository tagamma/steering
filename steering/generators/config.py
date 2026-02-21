from pathlib import Path
from typing import Any, Dict, List
import yaml


class Config:
    def __init__(self, config_dict: Dict[str, Any], config_path: Path):
        self.config_path = config_path
        self._data = config_dict

        version = self._data.get("version")
        if version != 1.0:
            raise ValueError(
                f"Unsupported config version: {version}. Only version 1.0 is supported."
            )

        # Extract config sections
        self.version = version
        self.vendor_files = self._data.get("vendor_files", {})
        self.default_vendor = self._data.get("default_vendor", "all")
        self.default_vendors = self._data.get(
            "default_vendors", ["cursor", "claude", "continue", "copilot"]
        )
        self.auto_rules_glob = self._data.get(
            "auto_rules_glob", "rules/auto-rules/**/*.mdc"
        )
        self.contextual_rules_glob = self._data.get(
            "contextual_rules_glob", "rules/contextual-rules/**/*.mdc"
        )
        self.agents_glob = self._data.get("agents_glob", "**/AGENTS.{md,mdc}")
        self.ignored_directories = self._data.get("ignored_directories", [])
        self.included_rules = self._data.get("included_rules", [])

        # Skills configuration
        skills_data = self._data.get("skills", {})
        self.skills_shared_path: str = skills_data.get("shared_path", "")
        self.skills_vendor_destinations: Dict[str, str] = skills_data.get(
            "vendor_destinations", {}
        )

        # Vendor-specific settings
        self.cursor_settings = self._data.get("cursor", {})
        self.claude_settings = self._data.get("claude", {})

    def validate(self) -> List[str]:
        """Validate the configuration and return any issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        issues = []

        if "cursor" not in self.vendor_files:
            issues.append("Missing 'cursor' in vendor_files configuration")
        if "claude" not in self.vendor_files:
            issues.append("Missing 'claude' in vendor_files configuration")

        if not isinstance(self.ignored_directories, list):
            issues.append("'ignored_directories' must be a list")

        # Validate default_vendors
        if not isinstance(self.default_vendors, list):
            issues.append("'default_vendors' must be a list")
        else:
            valid_vendors = ["cursor", "claude", "continue", "copilot", "gemini"]
            for vendor in self.default_vendors:
                if vendor not in valid_vendors:
                    issues.append(
                        f"Invalid vendor in default_vendors: '{vendor}'. "
                        f"Must be one of: {', '.join(valid_vendors)}"
                    )

        # Validate skills configuration
        if not isinstance(self.skills_vendor_destinations, dict):
            issues.append("'skills.vendor_destinations' must be a dictionary")
        else:
            valid_vendors = ["cursor", "claude", "continue", "copilot", "gemini"]
            for vendor in self.skills_vendor_destinations:
                if vendor not in valid_vendors:
                    issues.append(
                        f"Invalid vendor in skills.vendor_destinations: '{vendor}'. "
                        f"Must be one of: {', '.join(valid_vendors)}"
                    )

        # Warn about suspicious configurations
        if not self.auto_rules_glob:
            issues.append("WARNING: No auto_rules_glob pattern specified")
        if not self.contextual_rules_glob:
            issues.append("WARNING: No contextual_rules_glob pattern specified")

        return issues

    def get_cursor_output_dir(self) -> str:
        return self.vendor_files.get("cursor", ".cursor/rules")

    def get_claude_output_file(self) -> str:
        return self.vendor_files.get("claude", "CLAUDE.md")


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default location.

    Returns:
        A Config object

    Raises:
        FileNotFoundError: If the config file doesn't exist
        ValueError: If the config is invalid
    """
    if config_path is None:
        from pathlib import Path as PathLib

        # Look for steering/resources/default-config.yaml relative to this file
        package_dir = PathLib(__file__).parent.parent.parent
        config_path = package_dir / "resources" / "default-config.yaml"

    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse config file {config_path}: {e}")

    if not isinstance(config_dict, dict):
        raise ValueError(f"Config file {config_path} must contain a YAML dictionary")

    config = Config(config_dict, config_path)

    # Validate the configuration
    issues = config.validate()
    errors = [issue for issue in issues if not issue.startswith("WARNING:")]

    if errors:
        raise ValueError(
            "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    # Print warnings if any
    warnings = [issue for issue in issues if issue.startswith("WARNING:")]
    if warnings:
        import sys

        for warning in warnings:
            print(f"WARN: {warning}", file=sys.stderr)

    return config

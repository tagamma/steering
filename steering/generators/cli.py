#!/usr/bin/env python3

from pathlib import Path
import sys

import click
from rich.console import Console
from rich.table import Table

from .budget import compute_always_context
from .config import load_config
from .discovery import Discovery, DiscoveryError, resolve_discovery_mode
from .generator import RuleLoader
from .models import validate_ruleset
from .references import validate_references
from .skills import SkillConflictError, sync_skills, validate_skill_layouts
from .adapters import (
    CursorAdapter,
    ClaudeAdapter,
    ContinueDevAdapter,
    CopilotAdapter,
    GeminiAdapter,
    CodexAdapter,
)


console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Steering - AI agent behavioral management system.

    Manage and generate AI rule configurations for multiple vendors.
    """
    pass


@cli.command()
@click.option(
    "--input",
    required=True,
    help="Input directory containing rules/ subdirectory",
)
@click.option(
    "--output",
    default=".",
    help="Output directory for generated files (default: current directory)",
)
@click.option(
    "--vendor",
    type=click.Choice(
        ["cursor", "claude", "continue", "copilot", "gemini", "codex", "all"],
        case_sensitive=False,
    ),
    default="all",
    help="Which vendor to generate for (default: all)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be generated without creating files",
)
@click.option(
    "--no-git",
    is_flag=True,
    help=(
        "Discover files by scanning the filesystem recursively instead of "
        "limiting repo-wide scans to git-tracked files. Required when the "
        "output directory is not a git work tree."
    ),
)
@click.option(
    "--config-path",
    help="Path to config.yaml (default: {input}/resources/default-config.yaml)",
)
def generate(input, output, vendor, dry_run, no_git, config_path):
    """Generate AI rule configurations for specified vendor(s)."""
    console.print("[blue]🎯 Steering Generator[/blue]")
    console.print("[dim]" + "=" * 50 + "[/dim]\n")

    input_dir = Path(input)
    output_dir = Path(output)

    # Load configuration
    try:
        if config_path:
            config = load_config(Path(config_path))
        else:
            # Try input dir resources first, then fall back to package default
            try:
                config = load_config(input_dir / "resources" / "default-config.yaml")
            except FileNotFoundError:
                config = load_config()
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load config:[/red] {e}")
        sys.exit(1)

    # Resolve how repo-wide scans discover files (git-tracked vs filesystem)
    try:
        discovery_mode = resolve_discovery_mode(config.discovery, no_git, output_dir)
    except DiscoveryError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)
    discovery = Discovery(output_dir, discovery_mode, config.ignored_directories)

    console.print("[cyan]Configuration:[/cyan]")
    console.print(f"  Input: [white]{input_dir}[/white]")
    console.print(f"  Output: [white]{output_dir}[/white]")
    console.print(f"  Vendor: [white]{vendor}[/white]")
    console.print(
        f"  Discovery: [white]"
        f"{'git-tracked files' if discovery_mode == 'git' else 'filesystem scan'}"
        f"[/white]"
    )
    console.print(f"  Dry run: [white]{'yes' if dry_run else 'no'}[/white]\n")

    # Load rules
    console.print("[cyan]Loading rules...[/cyan]")
    try:
        loader = RuleLoader(config, input_dir)
        ruleset = loader.load_all_rules(output_dir, discovery)

        console.print(f"  ✅ {len(ruleset.auto)} auto-rule(s)")
        console.print(f"  ✅ {len(ruleset.contextual)} contextual rule(s)")
        console.print(f"  ✅ {len(ruleset.agents)} AGENTS file(s)")
        console.print(f"  ✅ {len(ruleset.skills)} skill(s)\n")
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load rules:[/red] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Resolve the active vendors before validation: a few filesystem contracts
    # (notably Codex's skill-directory symlink rule) are vendor-specific.
    vendors = config.default_vendors if vendor == "all" else [vendor]

    # Validate rules
    console.print("[cyan]Validating rules...[/cyan]")
    issues = validate_ruleset(ruleset) + validate_skill_layouts(ruleset.skills, vendors)
    if issues:
        errors = [i for i in issues if not i.startswith("INFO:")]
        infos = [i for i in issues if i.startswith("INFO:")]

        if errors:
            console.print("[red]ERROR: Validation errors:[/red]")
            for error in errors:
                console.print(f"  • {error}")
            sys.exit(1)

        if infos:
            for info in infos:
                console.print(f"  [dim]{info}[/dim]")

    console.print("  ✅ All rules valid\n")

    # Generate configurations
    adapters = {
        "cursor": CursorAdapter(),
        "claude": ClaudeAdapter(),
        "continue": ContinueDevAdapter(),
        "copilot": CopilotAdapter(),
        "gemini": GeminiAdapter(),
        "codex": CodexAdapter(),
    }

    all_files = {}

    for vendor_name in vendors:
        console.print(f"[cyan]Generating {vendor_name} configuration...[/cyan]")

        try:
            adapter = adapters[vendor_name]
            files = adapter.generate(
                ruleset, output_dir, input_dir, dry_run=dry_run, discovery=discovery
            )
            all_files.update(files)

            console.print(f"  ✅ Generated {len(files)} file(s)\n")
        except Exception as e:
            console.print(
                f"[red]ERROR: Failed to generate {vendor_name} config:[/red] {e}"
            )
            import traceback

            traceback.print_exc()
            sys.exit(1)

    # Sync shared skills
    if config.skills_shared_path:
        console.print("[cyan]Syncing shared skills...[/cyan]")
        try:
            skill_files = sync_skills(config, output_dir, vendors, dry_run=dry_run)
            all_files.update(skill_files)
            if skill_files:
                console.print(f"  ✅ Synced {len(skill_files)} skill symlink(s)\n")
            else:
                console.print("  [dim]No shared skills found[/dim]\n")
        except SkillConflictError as e:
            console.print(f"[red]ERROR: Skill conflict:[/red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]ERROR: Failed to sync skills:[/red] {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)

    # Display results
    console.print("[green]✅ Generation Complete![/green]\n")

    if dry_run:
        console.print("[yellow]Dry Run Results (no files created):[/yellow]\n")
    else:
        console.print("[cyan]Generated Files:[/cyan]\n")

    # Create table of generated files
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("File", style="white")
    table.add_column("Type", style="yellow")

    for file_path, content in sorted(all_files.items()):
        if content.startswith("SYMLINK->"):
            file_type = "symlink"
        else:
            file_type = "file"
        table.add_row(file_path, file_type)

    console.print(table)


@cli.command()
@click.option(
    "--input",
    required=True,
    help="Input directory containing rules/ subdirectory (also the repo root)",
)
@click.option(
    "--config-path",
    help="Path to config.yaml (default: {input}/resources/default-config.yaml)",
)
@click.option(
    "--no-git",
    is_flag=True,
    help=(
        "Discover AGENTS files by scanning the filesystem recursively instead "
        "of limiting the scan to git-tracked files. Required when the input "
        "directory is not a git work tree."
    ),
)
@click.option(
    "--max-context-kb",
    type=float,
    default=None,
    help=(
        "Fail validation if the always-on context (root CLAUDE.md plus every "
        "file it @-references transitively) exceeds this many KB. Overrides "
        "'validate.max_always_context_kb' from the config."
    ),
)
def validate(input, config_path, no_git, max_context_kb):
    """Validate all rules, AGENTS files, references, and context budget.

    Beyond frontmatter shape and name conflicts, this checks that every
    @-reference and relative markdown link in the rules, AGENTS files, and
    skills actually resolves to a file on disk -- catching stale references to
    deleted files that would otherwise be shipped to agents as broken context.
    It also computes the always-on context budget and can fail if it grows past
    a configured ceiling.
    """
    console.print("[yellow]Validating rules...[/yellow]\n")

    input_dir = Path(input)

    # Load configuration
    try:
        if config_path:
            config = load_config(Path(config_path))
        else:
            try:
                config = load_config(input_dir / "resources" / "default-config.yaml")
            except FileNotFoundError:
                config = load_config()
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load config:[/red] {e}")
        sys.exit(1)

    # The input dir doubles as the repository (generation) root for validation,
    # so AGENTS-file discovery and reference resolution share it.
    try:
        discovery_mode = resolve_discovery_mode(config.discovery, no_git, input_dir)
    except DiscoveryError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)
    discovery = Discovery(input_dir, discovery_mode, config.ignored_directories)

    # Load the full ruleset (auto, contextual, AGENTS files, skills) exactly
    # the way `generate` does, so validation covers the same content that ends
    # up in generated configs.
    try:
        loader = RuleLoader(config, input_dir)
        ruleset = loader.load_all_rules(input_dir, discovery)

        console.print(f"  Loaded {len(ruleset.auto)} auto-rule(s)")
        console.print(f"  Loaded {len(ruleset.contextual)} contextual rule(s)")
        console.print(f"  Loaded {len(ruleset.agents)} AGENTS file(s)")
        console.print(f"  Loaded {len(ruleset.skills)} skill(s)\n")
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load rules:[/red] {e}")
        sys.exit(1)

    errors: list[str] = []

    # Frontmatter shape + name-conflict checks.
    issues = validate_ruleset(ruleset)
    shape_errors = [i for i in issues if not i.startswith("INFO:")]
    infos = [i for i in issues if i.startswith("INFO:")]
    errors.extend(shape_errors)

    # Vendor filesystem contracts. Validation uses the configured default set,
    # matching `generate --vendor all`.
    errors.extend(validate_skill_layouts(ruleset.skills, config.default_vendors))

    # @-reference and markdown-link resolution checks.
    ref_errors = validate_references(ruleset, input_dir, input_dir)
    errors.extend(ref_errors)

    # Always-on context budget.
    budget = compute_always_context(ruleset, input_dir, input_dir)
    ceiling = max_context_kb if max_context_kb is not None else config.max_always_context_kb
    console.print(
        f"[cyan]Always-on context:[/cyan] {budget.total_kb:.1f} KB "
        f"across {len(budget.files) + 1} file(s) "
        f"(root CLAUDE.md + {len(budget.files)} @-referenced)"
    )
    if ceiling is not None:
        if budget.total_kb > ceiling:
            errors.append(
                f"Always-on context is {budget.total_kb:.1f} KB, over the "
                f"{ceiling:.1f} KB limit. Trim auto-rules or the files they "
                f"@-reference, or raise the limit."
            )
        else:
            console.print(f"  [dim](limit: {ceiling:.1f} KB)[/dim]")
    console.print()

    if infos:
        console.print("[cyan]Information:[/cyan]\n")
        for info in infos:
            console.print(f"  • {info[6:]}")  # Remove "INFO: " prefix
        console.print()

    if errors:
        console.print("[red]ERROR: Validation errors found:[/red]\n")
        for error in errors:
            console.print(f"  • {error}")
        console.print()
        sys.exit(1)

    console.print("[green]SUCCESS: Validation complete! No issues found.[/green]")
    sys.exit(0)


@cli.command("list")
@click.option(
    "--input",
    required=True,
    help="Input directory containing rules/ subdirectory",
)
@click.option(
    "--config-path",
    help="Path to config.yaml (default: {input}/resources/default-config.yaml)",
)
def list_rules(input, config_path):
    """List all configured rules."""
    console.print("[blue]Configured Rules[/blue]\n")

    input_dir = Path(input)

    # Load configuration
    try:
        if config_path:
            config = load_config(Path(config_path))
        else:
            try:
                config = load_config(input_dir / "resources" / "default-config.yaml")
            except FileNotFoundError:
                config = load_config()
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load config:[/red] {e}")
        sys.exit(1)

    # Load rules and skills
    try:
        loader = RuleLoader(config, input_dir)
        auto_rules = loader.load_auto_rules()
        contextual_rules = loader.load_contextual_rules()
        skills = loader.load_skills()
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load rules:[/red] {e}")
        sys.exit(1)

    # Display auto-rules
    if auto_rules:
        console.print("[cyan]Auto-Rules (always apply):[/cyan]\n")
        auto_table = Table(show_header=True, header_style="bold cyan")
        auto_table.add_column("Name", style="white")
        auto_table.add_column("Description", style="dim")

        for rule in sorted(auto_rules, key=lambda r: r.name):
            auto_table.add_row(rule.name, rule.description)

        console.print(auto_table)
        console.print()

    # Display contextual rules
    if contextual_rules:
        console.print("[cyan]Contextual Rules (load on-demand):[/cyan]\n")
        ctx_table = Table(show_header=True, header_style="bold cyan")
        ctx_table.add_column("Name", style="white")
        ctx_table.add_column("Description", style="dim")

        for rule in sorted(contextual_rules, key=lambda r: r.name):
            ctx_table.add_row(rule.name, rule.description)

        console.print(ctx_table)
        console.print()

    # Display skills
    if skills:
        console.print("[cyan]Skills (tool capabilities):[/cyan]\n")
        skill_table = Table(show_header=True, header_style="bold cyan")
        skill_table.add_column("Name", style="white")
        skill_table.add_column("Description", style="dim")
        skill_table.add_column("Tools", style="yellow")

        for skill in sorted(skills, key=lambda s: s.name):
            desc = skill.description
            if len(desc) > 80:
                desc = desc[:77] + "..."
            skill_table.add_row(skill.name, desc, skill.allowed_tools or "-")

        console.print(skill_table)
        console.print()

    # Summary
    console.print(
        f"[dim]Total: {len(auto_rules)} auto-rules, {len(contextual_rules)} contextual rules, {len(skills)} skills[/dim]"
    )


if __name__ == "__main__":
    cli()

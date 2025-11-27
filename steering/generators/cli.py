#!/usr/bin/env python3

from pathlib import Path
import sys

import click
from rich.console import Console
from rich.table import Table

from .config import load_config
from .generator import RuleLoader
from .models import validate_ruleset
from .adapters import (
    CursorAdapter,
    ClaudeAdapter,
    ContinueDevAdapter,
    CopilotAdapter,
    GeminiAdapter,
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
        ["cursor", "claude", "continue", "copilot", "gemini", "all"],
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
    "--config-path",
    help="Path to config.yaml (default: {input}/resources/default-config.yaml)",
)
def generate(input, output, vendor, dry_run, config_path):
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

    console.print("[cyan]Configuration:[/cyan]")
    console.print(f"  Input: [white]{input_dir}[/white]")
    console.print(f"  Output: [white]{output_dir}[/white]")
    console.print(f"  Vendor: [white]{vendor}[/white]")
    console.print(f"  Dry run: [white]{'yes' if dry_run else 'no'}[/white]\n")

    # Load rules
    console.print("[cyan]Loading rules...[/cyan]")
    try:
        loader = RuleLoader(config, input_dir)
        ruleset = loader.load_all_rules(output_dir)

        console.print(f"  ✅ {len(ruleset.auto)} auto-rule(s)")
        console.print(f"  ✅ {len(ruleset.contextual)} contextual rule(s)")
        console.print(f"  ✅ {len(ruleset.agents)} AGENTS file(s)\n")
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load rules:[/red] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Validate rules
    console.print("[cyan]Validating rules...[/cyan]")
    issues = validate_ruleset(ruleset)
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
    # Use config.default_vendors when vendor is "all", otherwise use specified vendor
    vendors = config.default_vendors if vendor == "all" else [vendor]

    adapters = {
        "cursor": CursorAdapter(),
        "claude": ClaudeAdapter(),
        "continue": ContinueDevAdapter(),
        "copilot": CopilotAdapter(),
        "gemini": GeminiAdapter(),
    }

    all_files = {}

    for vendor_name in vendors:
        console.print(f"[cyan]Generating {vendor_name} configuration...[/cyan]")

        try:
            adapter = adapters[vendor_name]
            files = adapter.generate(ruleset, output_dir, input_dir, dry_run=dry_run)
            all_files.update(files)

            console.print(f"  ✅ Generated {len(files)} file(s)\n")
        except Exception as e:
            console.print(
                f"[red]ERROR: Failed to generate {vendor_name} config:[/red] {e}"
            )
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
    help="Input directory containing rules/ subdirectory",
)
@click.option(
    "--config-path",
    help="Path to config.yaml (default: {input}/resources/default-config.yaml)",
)
def validate(input, config_path):
    """Validate all rules and check for conflicts."""
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

    # Load rules (without AGENTS files for validation)
    try:
        loader = RuleLoader(config, input_dir)
        auto_rules = loader.load_auto_rules()
        contextual_rules = loader.load_contextual_rules()

        console.print(f"  Loaded {len(auto_rules)} auto-rule(s)")
        console.print(f"  Loaded {len(contextual_rules)} contextual rule(s)\n")

        from .models import RuleSet

        ruleset = RuleSet(auto=auto_rules, contextual=contextual_rules, agents=[])
    except Exception as e:
        console.print(f"[red]ERROR: Failed to load rules:[/red] {e}")
        sys.exit(1)

    # Validate
    issues = validate_ruleset(ruleset)

    if not issues:
        console.print("[green]SUCCESS: Validation complete! No issues found.[/green]")
        sys.exit(0)

    # Separate errors and info messages
    errors = [i for i in issues if not i.startswith("INFO:")]
    infos = [i for i in issues if i.startswith("INFO:")]

    if errors:
        console.print("[red]ERROR: Validation errors found:[/red]\n")
        for error in errors:
            console.print(f"  • {error}")
        console.print()

    if infos:
        console.print("[cyan]Information:[/cyan]\n")
        for info in infos:
            console.print(f"  • {info[6:]}")  # Remove "INFO: " prefix
        console.print()

    if errors:
        sys.exit(1)
    else:
        console.print("[green]SUCCESS: No errors found[/green]")


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

    # Load rules
    try:
        loader = RuleLoader(config, input_dir)
        auto_rules = loader.load_auto_rules()
        contextual_rules = loader.load_contextual_rules()
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

    # Summary
    console.print(
        f"[dim]Total: {len(auto_rules)} auto-rules, {len(contextual_rules)} contextual rules[/dim]"
    )


if __name__ == "__main__":
    cli()

# Steering - AI Agent Behavioral Management System

> **Status:** This project started as a purely personal tool for my NixOS config monorepo. I'm open sourcing it because I believe it might be useful to others. If there is initial traction, I will make it more convenient to use (e.g. easier installation) and add missing functionality.

Steering provides a provider-agnostic system for managing and steering AI agents (Claude Code, Cursor, Gemini CLI, etc.) through structured behavioral rules and contextual guidance. It centralizes rule management and generates vendor-specific configuration files automatically.

## Why Steering?

I believe a lot of the value provided by AI coding assistants is unlocked by providing the right context to them and doing so in a convenient and scalable manner. `steering` helps with that.

The landscape of AI coding assistants evolves so rapidly that it doesn't make sense to commit to just using one tool. However, the configuration barrier -- setting up rules, context, and preferences for each tool -- often locks developers in and makes experimentation less attractive. I want that barrier to be lowered so I wrote `steering` to allow one to define their behavioral rules once and then automatically generate the necessary configuration for any supported tool.

Furthermore, it often makes sense to have multiple tools configured at once. For example, `claude-code` and `Cursor` are fundamentally different tools that excel at different jobs. With `steering`, one can easily maintain consistent behavior across both lowering cognitive load due to having to manually manage which tools knows what rules and context.

Historically, `steering` was more critical before `AGENTS.md` started becoming a standard supported by many AI coding tools. However, it remains relevant for various other use cases, (for example, to force-embed `@` references for tools that don't support them natively or to generate configurations for newer tools like `GEMINI.md` when comparing it to claude-code).

## Core Concepts

### Three-Tier Rule System

1. **Auto Rules** - Universal principles that always apply across all contexts.
   - Example: Code quality standards, security practices, general preferences that always apply (e.g. "we do TDD")
   - Stored in `rules/auto-rules/*.mdc`.

2. **Contextual Rules** - Domain or technology-specific patterns applied based on context.
   - Example: Frontend patterns, database guidelines.
   - Stored in `rules/contextual-rules/*.mdc`.

3. **Local Rules** - Directory-specific guidelines co-located with code.
   - Stored as `AGENTS.md` or `AGENTS.mdc` files.
   - Automatically discovered and included.

### Canonical File Structure

Steering encourages a consistent organization of project files to help both humans and AI agents navigate codebases:

- `AGENTS.md`: Context and rules for AI agents.
- `STRUCTURE.md`: Directory layout and navigation guide.
- `README.md`: Human-readable documentation.
- `TODO.org` / `KANBAN.org` / `PLAN.org`: Task tracking.

### Provider Adapters

Steering generates native configurations for supported tools, for example:

- **Cursor**: Creates symlinks in `.cursor/rules/` (preserving frontmatter).
- **Claude**: Generates `CLAUDE.md` with `@` references.
- **Gemini**: Generates a `GEMINI.md` file just like for Claude, but with some gemini-cli-specific quirks handled.

### Rule Format (MDC)

Rules use Markdown with YAML frontmatter (`.mdc`) follow the format used by Cursor:

```yaml
---
description: When to apply this rule
globs: ["**/*.py"]
alwaysApply: false
---
# Rule Title

Rule content...
```

## Architecture

```text
steering/
├── README.md                   # This file
├── resources/
│   └── default-config.yaml     # Configuration settings
├── rules/                      # Centralized rule definitions
│   ├── auto-rules/             # Always-apply rules
│   └── contextual-rules/       # Context-specific rules
├── steering/                   # Python package source
│   ├── generators/             # Core logic and CLI
│   └── adapters/               # Provider-specific adapters
└── pyproject.toml              # Dependencies
```

## Key Features

### Expected Usage Pattern

Currently, the expected workflow is:

1. **Clone locally**: Clone this repository to your machine.
2. **Pre-commit Hook (if using nix)**: Use the `pre-commit-nix` hook if you use (copy `resources/hooks/pre-commit-nix` to your target repository's `.git/hooks/pre-commit`).
3. **Pre-commit Hook (if not using nix)**: Copy the hook from `resources/hooks/pre-commit-manual` to your target repository's `.git/hooks/pre-commit` and update it to point to your `steering` installation.
4. **Invoke CLI via Nix (if using nix)**: If you use Nix, you can invoke the CLI directly: `nix run github:tagamma/steering`.

In the future, this process will be streamlined.

### Basic Commands

```bash
# Generate configurations for Cursor
# (Assuming you are in the directory containing 'rules/' and 'resources/default-config.yaml')
steering generate --input . --output . --vendor cursor

# Generate configurations for Claude
steering generate --input . --output . --vendor claude

# Generate for all configured providers
steering generate --input . --output .

# Validate all rules
steering validate --input .

# List configured contexts/concerns
steering list --input .
```

### Configuration File (resources/default-config.yaml)

```yaml
version: 1.0

defaults:
  vendor_files:
    - cursor: ".cursor/rules"
    - claude: "CLAUDE.md"
  local_rules_glob: "AGENTS.{md,mdc}"
  auto_rules_glob: "rules/auto-rules/*.mdc"
  contextual_rules_glob: "rules/contextual-rules/*.mdc"
```

### Creating Rules

1. **Auto Rule Example** (`rules/auto/code-quality.mdc`):

```yaml
---
description: Enforce consistent code quality standards
globs: ["**/*"]
alwaysApply: true
---
# Code Quality Standards

- Always use descriptive variable names
- Keep functions under 50 lines
- Write tests for new functionality
- Document complex logic with comments
```

2. **Contextual Rule Example** (`rules/contextual/react-patterns.mdc`):

```yaml
---
description: React development patterns and best practices
globs: ["**/*.jsx", "**/*.tsx"]
alwaysApply: false
---
# React Development Patterns

- Prefer functional components with hooks
- Use proper prop validation with TypeScript
- Implement error boundaries for robustness
- Follow component composition over inheritance
```

3. **Local Rule Example** (`src/components/AGENTS.md`):

```yaml
# Component Guidelines

This directory contains reusable UI components.
- Each component should be self-contained
- Include Storybook stories for documentation
- Use CSS modules for styling
```

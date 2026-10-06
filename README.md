# Steering - AI Agent Behavioral Management System

> **Status:** This project started as a purely personal tool for my NixOS config monorepo. I'm open sourcing it because I believe it might be useful to others. If there is initial traction, I will make it more convenient to use (e.g. easier installation) and add missing functionality.

Steering provides a provider-agnostic system for managing and steering AI agents (Claude Code, Cursor, Codex, Antigravity CLI, etc.) through structured behavioral rules and contextual guidance. It centralizes rule management and generates vendor-specific configuration files automatically.

## Why Steering?

I believe a lot of the value provided by AI coding assistants is unlocked by providing the right context to them and doing so in a convenient and scalable manner. `steering` helps with that.

The landscape of AI coding assistants evolves so rapidly that it doesn't make sense to commit to just using one tool. However, the configuration barrier -- setting up rules, context, and preferences for each tool -- often locks developers in and makes experimentation less attractive. I want that barrier to be lowered so I wrote `steering` to allow one to define their behavioral rules once and then automatically generate the necessary configuration for any supported tool.

Furthermore, it often makes sense to have multiple tools configured at once. For example, `claude-code` and `Cursor` are fundamentally different tools that excel at different jobs. With `steering`, one can easily maintain consistent behavior across both lowering cognitive load due to having to manually manage which tools knows what rules and context.

Historically, `steering` was more critical before `AGENTS.md` started becoming a standard supported by many AI coding tools (Claude Code reads it natively since v2.1.277, so steering no longer generates `CLAUDE.md` at all). It remains relevant for the gaps that are left: force-embedding `@` references for tools that don't expand them, symlinking skills into vendor-specific locations, and validating that the whole context tree is consistent (every reference resolves, every auto-rule is wired up, the always-on context stays within budget).

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

- **Cursor**: Creates symlinks in `.cursor/rules/` (preserving frontmatter), and embeds the files that `AGENTS.md` files `@`-reference as `.mdc` rules (alwaysApply for the root `AGENTS.md`, glob-scoped to the directory for nested ones). Cursor loads root and nested `AGENTS.md` natively but doesn't expand `@` refs anywhere (verified against the CLI, 2026-10), so only the referenced files are embedded, never the `AGENTS.md` bodies. Gitignored targets (host-local files like `AGENTS.md.local`) are never embedded: the generated rules are committed, so they would publish the file and drift from CI's output.
- **Claude**: No generated files. Claude Code v2.1.277+ reads `AGENTS.md` natively (the root one at session start, with its `@path` imports expanded; nested ones as it works in their directories) -- but only while no `CLAUDE.md` exists in or above the working directory. So the auto-rules reach it through `@` references in the root `AGENTS.md` (`steering validate` fails if one is missing), and skills through the `.claude/skills` symlink destination (it does not read `.agents/skills/`). The `CLAUDE.md` files earlier versions generated now block all of that; `generate` warns about them and `steering cleanup-claude-md` removes them after checking that each one really is steering's output (a bare `@AGENTS.md` pointer next to an `AGENTS.md`, or the old root index). Hand-written `CLAUDE.md` files are reported and left alone.
- **Antigravity** (`agy`, Google's successor to Gemini CLI; opt-in, add `antigravity` to `default_vendors`): pointer rules in `.agents/rules/steering-*.md` (gitignore them). agy reads `AGENTS.md` natively, but only walking up from the session's cwd -- reading a file in a nested directory doesn't pull that directory's `AGENTS.md` in -- and it expands `@[label](path)` includes but not bare `@path` refs (verified against agy 1.2.17 with canary files, 2026-10). So each file the root `AGENTS.md` and the auto-rules `@`-reference becomes a `trigger: always_on` rule, and each nested `AGENTS.md` plus its refs a `trigger: glob` rule scoped to `**/<dir>/**` (agy matches globs against absolute paths, so a bare `<dir>/**` never fires). Each rule is a one-line `@[label](path)` include rather than an embedded copy, so the output only changes when references do. Skills need nothing: agy reads `.agents/skills/` natively. It also deletes stale `GEMINI.md` files from when steering generated them for Gemini CLI, since agy still reads `GEMINI.md`. The old `gemini` vendor name still works as a deprecated alias.
- **Codex**: No generated files. Codex reads `AGENTS.md` and `.agents/skills/` natively, both of which steering already manages as source-of-truth. Steering still validates Codex's filesystem contract: a complete skill directory may be symlinked, but an individual `SKILL.md` may not.

### Skill link layout

Keep `.agents/skills/<name>/SKILL.md` as a regular file. When the source lives
elsewhere, symlink the complete `<name>` directory into `.agents/skills/`:

```text
.agents/skills/agd -> ../../nix/packages/agd/skill
```

Don't create a real `agd/` directory containing only a symlinked `SKILL.md`.
Claude Code accepts that shape, but Codex intentionally ignores it. `steering
validate` rejects the incompatible layout whenever `codex` is in
`default_vendors`; copying the complete directory also works, but a directory
symlink preserves one source of truth.

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

## Usage

### Expected Usage Pattern

Currently, the expected workflow is:

1. **Clone locally**: Clone this repository to your machine.
2. **Pre-commit Hook**: Install `resources/hooks/pre-commit`, which blocks a commit whose
   generated configs have drifted from the rule sources it stages.

   ```bash
   mkdir -p .githooks && cp resources/hooks/pre-commit .githooks/
   chmod +x .githooks/pre-commit
   git config core.hooksPath .githooks   # tracked hook: a fresh clone runs one command, not zero
   ```

   It runs steering via `uvx`, falling back to `nix`; set `STEERING_CMD` to pin it to
   whatever your CI runs. The hook is **check-only** — it regenerates into a throwaway
   snapshot of your *index*, never writes to your working tree, and never stages anything.
   On drift it prints the command that fixes it. (The old examples regenerated in place
   and auto-staged the result, which meant a commit could quietly carry generated changes
   nobody reviewed — and, in a repo with submodules, clobber generated files the submodule
   owns. The header comment in the hook has the full story.)
3. **Manual CLI**: You can also manually invoke the `steering` CLI from your repository root.
4. **Nix Run**: If you use Nix, you can invoke the CLI directly without cloning as well: `nix run github:tagamma/steering`.

### Basic Commands

```bash
# Generate configurations for Cursor
# (Assuming you are in the directory containing 'rules/' and 'resources/default-config.yaml')
steering generate --input . --output . --vendor cursor

# Generate for all configured providers
steering generate --input . --output .

# Remove the CLAUDE.md files older steering versions generated (Claude Code
# reads AGENTS.md natively now, but only while no CLAUDE.md is in the way).
# Content-checked: hand-written CLAUDE.md files are listed, never deleted.
steering cleanup-claude-md --input . --output . --dry-run
steering cleanup-claude-md --input . --output .

# Generate for a directory that is not a git repository (e.g. a knowledge base).
# Inside a git work tree, discovery only considers git-tracked files; outside
# one, an explicit --no-git is required to opt into a recursive filesystem scan.
steering generate --input . --output . --no-git

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
  local_rules_glob: "AGENTS.{md,mdc}"
  auto_rules_glob: "rules/auto-rules/*.mdc"
  contextual_rules_glob: "rules/contextual-rules/*.mdc"
  # How repo-wide scans find files: "auto" (default) uses git-tracked files
  # inside a git work tree and errors outside one; "filesystem" opts into a
  # recursive walk (same as passing --no-git), for non-git directories.
  discovery: auto
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

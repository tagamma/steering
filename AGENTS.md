# Steering - AI Agent Behavioral Management System

@README.md

## Developer Context

### Project Structure

```text
projects/steering/
├── steering/                    # Python package source
│   ├── generators/              # Logic for rule generation
│   └── adapters/                # Vendor-specific implementations
├── rules/                       # The actual rule definitions (DATA, not code)
├── resources/
│   └── default-config.yaml      # Configuration schema/defaults
└── flake.nix                    # Env definition
```

### Critical Implementation Logic

1. **Cursor Adapter (`adapters/cursor.py`)**:
   - **Symlinks**: Most rules are symlinked to `.cursor/rules/`.
   - **Agent Wrapping**: `AGENTS.md` files are *not* symlinked. They are wrapped in a new `.mdc` file that includes their content + a directory-scoped `glob`. This is because Cursor doesn't natively support "local" rules in scattered directories yet.

2. **Claude Adapter (`adapters/claude.py`)**:
   - **Reference**: Generates `CLAUDE.md` using `@` references.
   - **Locality**: Creates adjacent `CLAUDE.md` files next to `AGENTS.md` files to support local context loading.

3. **Rule Discovery (`generator.py` + `discovery.py`)**:
   - Repo-wide scans (AGENTS file discovery, cleanup of generated files) are git-aware: inside a git work tree only git-tracked files are considered (`git ls-files --recurse-submodules`); outside one, a recursive walk requires explicit opt-in (`--no-git` or `discovery: filesystem`).
   - The filesystem walk never follows directory symlinks (recursive `glob` did, which let scans escape into Nix `result` symlinks and similar).
   - Respects `ignored_directories` from config to avoid scanning `node_modules` etc.

### Development Workflow

- Enter dev shell with all deps with `nix develop`.
- Validate rules with `steering validate --input projects/steering`
- Generate configurations for all supported tools with `steering generate --input projects/steering --output . --dry-run` to test all adapters for crashes, etc
- Ensure `resources/default-config.yaml` is valid.

## AI Instructions

- Never put rule data inside the `steering/` python package. Rules live in `rules/`.
- When generating MDC files, ensure YAML frontmatter is valid and preserved.
- All generated paths (symlinks, references) must be relative to the repo root.
- Python code must be fully typed.
- Managed via `uv` and `pyproject.toml`.

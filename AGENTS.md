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
   - **Ground truth** (canary probes against Cursor CLI 2026.09.26 on 2026-10-03): Cursor loads root AND nested AGENTS.md natively (nested attach when it works on a file in that directory), but expands `@` refs nowhere -- not in AGENTS.md, not in `.cursor/rules/*.mdc` either, whatever the docs say. `tests/test_cursor.py` pins the consequences.
   - **Symlinks**: Auto/contextual rules symlinked to `.cursor/rules/`.
   - **Root AGENTS.md**: `@` refs embedded as alwaysApply `ref-*.mdc`, skipping refs to the auto/contextual rules already symlinked.
   - **Nested AGENTS.md**: glob-scoped `agents-*.mdc` holding ONLY the expanded `@` refs (the body would load twice). Nothing is written when there are no refs.
   - **Host-local refs**: gitignored `@` targets (`AGENTS.md.local`, `LOCALCONTEXT.md`) are never embedded (`is_gitignored`, checked before existence so CI doesn't warn). The output is committed, so embedding would leak the file and break the CI drift check. Cursor never sees them.

2. **Claude Adapter (`adapters/claude.py`)**:
   - **No output**: Claude Code (v2.1.277+) reads `AGENTS.md` natively, root and nested, and expands `@path` imports in it. Auto-rules reach it only through `@` references in the root `AGENTS.md`, so `validate_auto_rule_wiring` (`references.py`) fails validation when one isn't referenced.
   - **Leftovers**: Claude Code reads `AGENTS.md` only while no `CLAUDE.md` exists in or above the cwd, so the files steering used to generate now block it. `generate` warns; `steering cleanup-claude-md` (`claude_cleanup.py`) deletes them, gated on content: an exact `@AGENTS.md`/`@AGENTS.mdc` pointer with that sibling present, or the old root index header. Anything else is hand-written and reported, never deleted. Files inside git submodules are skipped (that repo's own run owns them). `generate` never deletes.
   - **Skills**: Claude Code does not read `.agents/skills/`; it needs the `skills.vendor_destinations.claude: .claude/skills` symlink.

3. **Antigravity Adapter (`adapters/antigravity.py`)**:
   - **Ground truth** (canary probes against agy 1.2.17 on 2026-10-03): agy loads `AGENTS.md`/`GEMINI.md` natively but only walking up from the cwd (reading a nested file does not attach its `AGENTS.md`), expands `@[label](path)` includes (relative to the including file) but not bare `@path`, and loads `.agents/rules/*.md` only with a `trigger:` frontmatter (`always_on`, `glob`, `model_decision`); `.mdc` and Cursor's `alwaysApply` are ignored. Glob triggers fire on file reads and match absolute paths, so they need a `**/` prefix. `tests/test_antigravity.py` pins the consequences.
   - **Opt-in**: not in the default config's `default_vendors` (it writes files users must gitignore); `--vendor antigravity` or listing it enables it.
   - **Output**: `.agents/rules/steering-*.md` (configurable via `vendor_files.antigravity`), each a single `@[label](path)` pointer: auto-rules and the transitive refs of the root `AGENTS.md`/auto-rules → `always_on`; contextual rules → `glob`/`model_decision`; nested `AGENTS.md` bodies and their refs → `glob` on `**/<dir>/**`. One file per target because agy caps each rule at 24 KB after expansion. Pointers use the unresolved path so per-machine symlinks (LOCALCONTEXT.md) resolve at load time.
   - **Cleanup**: deletes only `steering-*.md` in the rules dir (hand-written rules can sit alongside) plus stale `GEMINI.md` files. `gemini` is a deprecated vendor alias (`config.VENDOR_ALIASES`).

4. **Rule Discovery (`generator.py` + `discovery.py`)**:
   - Repo-wide scans (AGENTS file discovery, cleanup of generated files) are git-aware: inside a git work tree only git-tracked files are considered (`git ls-files --recurse-submodules`); outside one, a recursive walk requires explicit opt-in (`--no-git` or `discovery: filesystem`).
   - The filesystem walk never follows directory symlinks (recursive `glob` did, which let scans escape into Nix `result` symlinks and similar).
   - Respects `ignored_directories` from config to avoid scanning `node_modules` etc.

5. **Skill links (`skills.py`)**:
   - `.agents/skills/<name>` may be a symlink to a complete skill directory.
   - Never symlink only `.agents/skills/<name>/SKILL.md`: Codex ignores individual
     manifest symlinks. Keep the manifest regular inside the directory target.
   - `steering validate` enforces this when `codex` is enabled; keep the regular,
     directory-symlink, and manifest-symlink cases covered by tests.

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

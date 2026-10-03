import os
from pathlib import Path
from typing import Dict, List, Optional

from ..discovery import Discovery
from ..models import Rule, RuleSet
from ..references import extract_references

_REF_MAX_DEPTH = 3

# Everything this adapter writes into the rules dir starts with this prefix;
# cleanup deletes only those files, so hand-written rules can live alongside.
GENERATED_PREFIX = "steering-"

DEFAULT_RULES_DIR = ".agents/rules"


class AntigravityAdapter:
    """Generate Antigravity CLI (``agy``) workspace rules.

    Ground truth (canary probes against agy 1.2.17, 2026-10-03):

    - agy loads ``AGENTS.md`` (and ``GEMINI.md``) natively, but only by walking
      up from the session's cwd. Reading a file in a nested directory does NOT
      pull that directory's ``AGENTS.md`` in.
    - It expands ``@[label](path)`` includes (path relative to the including
      file) but not bare ``@path`` refs, so the ``@`` refs every other tool
      reads are dead text to agy.
    - ``.agents/rules/*.md`` rules load with ``trigger: always_on``,
      ``model_decision`` (only the description is injected) or ``glob``.
      ``.mdc`` files and Cursor's ``alwaysApply`` frontmatter are ignored, and
      a rule with no frontmatter is never loaded. Symlinked and gitignored rule
      files load fine.
    - ``glob`` rules fire when the agent reads a matching file, but the
      patterns match absolute paths: ``**/sub/**`` works, ``sub/**`` never
      matches.
    - Skills are read from ``.agents/skills/`` natively (directory symlinks
      included), so there is nothing to do for them.

    So, like the Cursor adapter, this writes rules for what agy can't reach on
    its own -- but as pointers (an ``@[label](path)`` include per file) rather
    than embedded copies, so the output only changes when the references do:

    - the auto-rules, plus every file they and the root ``AGENTS.md``
      ``@``-reference (transitively) → ``always_on``
    - contextual rules (and their refs) → ``glob`` when they have globs,
      ``model_decision`` otherwise
    - each nested ``AGENTS.md`` and its refs → ``glob`` scoped to its directory

    agy truncates each rule at 24 KB after expanding includes, hence one rule
    file per target rather than one per scope.

    It also deletes stale ``GEMINI.md`` files left over from when steering
    generated them for Gemini CLI: agy still reads ``GEMINI.md``, so a stale
    one would keep feeding it outdated context.
    """

    def __init__(self, rules_dir: str = DEFAULT_RULES_DIR):
        self.rules_dir = rules_dir

    def generate(
        self,
        ruleset: RuleSet,
        output_dir: Path,
        input_dir: Path,
        *,
        dry_run: bool = False,
        discovery: Optional[Discovery] = None,
    ) -> Dict[str, str]:
        output_dir = Path(output_dir)
        if discovery is None:
            discovery = Discovery.fallback(output_dir)

        rules_dir = output_dir / self.rules_dir
        files: Dict[str, str] = {}
        out_resolved = output_dir.resolve()

        root_agents = [
            r for r in ruleset.agents if r.path.parent.resolve() == out_resolved
        ]
        nested_agents = [
            r for r in ruleset.agents if r.path.parent.resolve() != out_resolved
        ]
        # Resolved paths agy already loads for the whole session: the root
        # AGENTS.md (natively) plus every always_on pointer. Scoped rules skip
        # those, but dedupe only within their own scope otherwise -- a file two
        # directories both reference has to fire for either of them.
        always_on: set[Path] = {r.path.resolve() for r in root_agents}

        def emit(name: str, target: Path, frontmatter: List[str], claimed: "set[Path]") -> None:
            self._emit(files, rules_dir, output_dir, claimed, name, target, frontmatter)

        # Auto-rules first, so a root @ref to one keeps the auto- name.
        always = self._frontmatter_always()
        for rule in ruleset.auto:
            emit(f"auto-{rule.name}", rule.path, always, always_on)
        for rule in root_agents + ruleset.auto:
            for ref in self._collect_refs(rule.content, rule.path.parent, output_dir):
                emit(f"ref-{self._slug(ref, output_dir, output_dir)}", ref, always, always_on)

        for rule in ruleset.contextual:
            fm = self._frontmatter_contextual(rule)
            scoped = set(always_on)
            emit(f"contextual-{rule.name}", rule.path, fm, scoped)
            for ref in self._collect_refs(rule.content, rule.path.parent, output_dir):
                slug = self._slug(ref, rule.path.parent, output_dir)
                emit(f"contextual-{rule.name}--{slug}", ref, fm, scoped)

        # Nested AGENTS.md: agy only loads one when the session starts inside
        # its directory, so (unlike Cursor) the body gets a pointer too.
        for rule in nested_agents:
            try:
                reldir = rule.path.parent.resolve().relative_to(out_resolved).as_posix()
            except ValueError:
                continue  # outside the output tree
            fm = self._frontmatter_glob(
                [f"{reldir}/**"],
                f"{reldir}/{rule.path.name} and the files it @-references",
            )
            scope = self._slug(rule.path.parent, output_dir, output_dir, keep_ext=True)
            scoped = set(always_on)
            emit(f"agents-{scope}", rule.path, fm, scoped)
            for ref in self._collect_refs(rule.content, rule.path.parent, output_dir):
                slug = self._slug(ref, rule.path.parent, output_dir)
                emit(f"agents-{scope}--{slug}", ref, fm, scoped)

        if not dry_run:
            self._cleanup(rules_dir)
            self._cleanup_gemini_md(discovery)
            if files:
                rules_dir.mkdir(parents=True, exist_ok=True)
            for rel, content in files.items():
                (output_dir / rel).write_text(content, encoding="utf-8")

        return files

    # -- output ---------------------------------------------------------------

    def _emit(
        self,
        files: Dict[str, str],
        rules_dir: Path,
        output_dir: Path,
        claimed: "set[Path]",
        name: str,
        target: Path,
        frontmatter: List[str],
    ) -> None:
        """Queue one pointer rule for ``target`` unless something already covers it."""
        resolved = target.resolve()
        if resolved in claimed or not target.is_file():
            return
        claimed.add(resolved)

        rule_file = rules_dir / f"{GENERATED_PREFIX}{name}.md"
        # Relative to the rule file (that's how agy resolves includes), built
        # from the unresolved path so a per-machine symlink like LOCALCONTEXT.md
        # is followed when agy loads the rule rather than baked in here.
        include = os.path.relpath(target.absolute(), rules_dir.absolute())
        label = self._display(target, output_dir)
        files[self._display(rule_file, output_dir)] = "\n".join(
            ["---", *frontmatter, "---", "", f"@[{label}]({include})", ""]
        )

    def _cleanup(self, rules_dir: Path) -> None:
        if not rules_dir.is_dir():
            return
        for item in rules_dir.glob(f"{GENERATED_PREFIX}*.md"):
            try:
                if item.is_symlink() or item.is_file():
                    item.unlink()
            except Exception as e:
                print(f"WARN: Failed to remove {item}: {e}")

    def _cleanup_gemini_md(self, discovery: Discovery) -> None:
        # Discovery-aware, so files git doesn't know about (e.g. inside
        # gitignored checkouts) are left alone.
        for gemini_file in discovery.cleanup_files(["**/GEMINI.md"]):
            try:
                gemini_file.unlink()
            except Exception as e:
                print(f"WARN: Failed to remove {gemini_file}: {e}")

    # -- frontmatter ----------------------------------------------------------

    @staticmethod
    def _frontmatter_always() -> List[str]:
        return ["trigger: always_on"]

    @staticmethod
    def _frontmatter_glob(globs: List[str], description: str) -> List[str]:
        # agy matches globs against absolute paths, so a repo-relative pattern
        # never fires; anchor anything that isn't already.
        anchored = [g if g.startswith(("**/", "/")) else f"**/{g}" for g in globs]
        if len(anchored) == 1:
            globs_line = f"globs: {_yaml_str(anchored[0])}"
        else:
            globs_line = "globs: [" + ", ".join(_yaml_str(g) for g in anchored) + "]"
        return ["trigger: glob", globs_line, f"description: {_yaml_str(description)}"]

    def _frontmatter_contextual(self, rule: Rule) -> List[str]:
        description = rule.description or rule.title or rule.name
        if rule.always_apply:
            return self._frontmatter_always()
        if rule.globs:
            return self._frontmatter_glob(rule.globs, description)
        return ["trigger: model_decision", f"description: {_yaml_str(description)}"]

    # -- references -----------------------------------------------------------

    def _collect_refs(self, content: str, base_dir: Path, output_dir: Path) -> List[Path]:
        """Files ``content`` @-references, transitively (depth-limited), in order.

        Resolution mirrors the budget walk: the referencing file's directory
        first, then the repo root.
        """
        out: List[Path] = []
        seen: set[Path] = set()

        def walk(text: str, base: Path, depth: int) -> None:
            if depth > _REF_MAX_DEPTH:
                return
            for ref in (r.target for r in extract_references(text) if r.kind == "at"):
                path = self._resolve(ref, base, output_dir)
                if path is None:
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                out.append(path)
                try:
                    child = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                walk(child, path.parent, depth + 1)

        walk(content, base_dir, 1)
        return out

    @staticmethod
    def _resolve(ref: str, base: Path, output_dir: Path) -> Optional[Path]:
        for candidate in (base / ref, output_dir / ref):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _display(path: Path, output_dir: Path) -> str:
        try:
            return Path(os.path.relpath(path.absolute(), output_dir.absolute())).as_posix()
        except ValueError:
            return str(path)

    def _slug(self, path: Path, base: Path, output_dir: Path, keep_ext: bool = False) -> str:
        """Filename-safe name for ``path``: relative to ``base`` when it's inside
        it (so a nested ref doesn't repeat its scope), else to the repo root."""
        rel = self._display(path, base)
        if rel.startswith("../"):
            rel = self._display(path, output_dir)
        if not keep_ext:
            rel, _ = os.path.splitext(rel)
        parts = [part.strip(".").replace(".", "-") for part in rel.split("/")]
        return "-".join(part or "up" for part in parts)


def _yaml_str(value: str) -> str:
    """Double-quoted YAML scalar (a glob starting with '*' would read as an alias)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

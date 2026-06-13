"""Extraction and resolution of references embedded in rule/AGENTS/skill content.

Two kinds of references are checked:

- ``@path`` references (the embedding mechanism Claude/Cursor use). We only
  treat ``@`` as a reference when it sits at a word start, so emails and
  ``user@host`` strings (``root@weaver.lan``, ``tagamma@weaver.lan``) are not
  mistaken for paths.
- Relative markdown links ``[text](relative/path)`` with no scheme and no
  pure-anchor target. These catch mentions of files that were since deleted.

Resolution semantics differ by where the reference lives:

- References inside ``.mdc`` rules (auto/contextual) are embedded by the
  generators at the output (repo) root, so they resolve relative to the
  generation root. They are also allowed to resolve relative to the rule
  file's own directory, which is how the Cursor adapter embeds them (e.g. an
  ``atoms/`` sibling directory next to a contextual rule).
- References inside ``AGENTS.md``/``SKILL.md`` files are read in place, so they
  resolve relative to the directory containing the file.

In all cases a reference is considered resolved if it exists under *any* of its
candidate bases. If it resolves under none, it is reported as broken -- unless
its target is deliberately git-ignored (a host-local file like LOCALCONTEXT.md
that is intentionally absent from a fresh checkout and from CI), in which case
the reference is correct and left alone.

Distinguishing real path references from prose is inherently fuzzy: agents
write ``@high/@medium/@low`` energy tags, ``@property`` decorators, and
``[text](url)`` placeholders that are not files. We treat a token as a path
reference only when it actually looks like one -- it contains a ``/`` or carries
a file extension. Bare single words (``@high``, ``@property``) are left alone.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .models import RuleSet


# A reference token: word-start '@' followed by a path-ish run of characters.
# The leading lookbehind forbids the previous char being part of an
# identifier/host (alphanumeric, '.', '-', '_') so emails and user@host are
# skipped. '@' at the very start of the string is handled by the alternation.
# The path may start with '.' or '/' so parent-relative refs like
# '@../../AGENTS.md' (used by several nested AGENTS files) are matched.
_AT_REF = re.compile(r"(?:(?<=^)|(?<=[\s(\[{]))@([A-Za-z0-9./][A-Za-z0-9._/-]*)")

# Relative markdown links: [text](target). We exclude anything with a scheme
# (http://, mailto:) and pure anchors (#foo); fragments/queries are stripped.
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Trailing characters that are sentence punctuation rather than part of a path.
# A trailing '/' is also stripped so directory refs like '@schema/' normalize
# to 'schema' (the directory it points at).
_TRAILING_PUNCT = ".,:;!?)]}>\"'/"


@dataclass(frozen=True)
class Reference:
    """A reference extracted from some content."""

    target: str  # The referenced path (relative)
    kind: str  # "at" for @refs, "link" for markdown links


def strip_code_blocks(content: str) -> str:
    """Blank out fenced code blocks so their contents are not scanned.

    Lines inside ``` ... ``` (or ~~~) fences are replaced with empty lines,
    preserving line count so any future line-number reporting stays accurate.
    """
    out: List[str] = []
    in_fence = False
    fence_marker = ""
    for line in content.split("\n"):
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence = True
            fence_marker = stripped[:3]
            out.append("")
            continue
        if in_fence:
            if stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def _clean_target(target: str) -> str:
    """Strip trailing sentence punctuation while keeping real path chars.

    ``@AGENTS.md.`` -> ``AGENTS.md`` (trailing period removed, extension kept).
    ``@foo/bar),`` -> ``foo/bar``.
    ``@schema/`` -> ``schema`` (trailing slash on a dir ref removed).
    """
    return target.rstrip(_TRAILING_PUNCT)


def _looks_like_path(target: str) -> bool:
    """Whether a cleaned target is path-like enough to be a real reference.

    A real path reference has structure: either it spans directories (contains
    a ``/``) or it names a file with an extension (``foo.md``). Bare single
    words (``high``, ``property``, ``url``) are prose -- org-mode tags, Python
    decorators, link-text placeholders -- and are not treated as references.
    """
    if "/" in target:
        return True
    # A trailing-dotless word like "README" is ambiguous; require a real
    # extension (a dot with following extension chars, not a sentence period
    # which _clean_target already stripped).
    last = target.rsplit("/", 1)[-1]
    return "." in last and not last.endswith(".")


def extract_references(content: str) -> List[Reference]:
    """Extract @-references and relative markdown links from content.

    Fenced code blocks are skipped (they contain shell examples and doc
    snippets with ``@`` and link-like tokens). Emails and ``user@host``
    strings are never matched as @-references. Bare prose words that merely
    start with ``@`` (org tags, decorators) are not treated as references.
    """
    body = strip_code_blocks(content)
    refs: List[Reference] = []
    seen = set()

    for match in _AT_REF.finditer(body):
        target = _clean_target(match.group(1))
        if not target or not _looks_like_path(target):
            continue
        key = ("at", target)
        if key not in seen:
            seen.add(key)
            refs.append(Reference(target=target, kind="at"))

    for match in _MD_LINK.finditer(body):
        raw = match.group(1).strip()
        # Strip a fragment/query so "foo.md#section" resolves as "foo.md".
        raw = raw.split("#", 1)[0].split("?", 1)[0].strip()
        if not raw:
            continue  # pure anchor link, nothing to resolve
        # Skip absolute URLs / schemes (http:, mailto:, etc.), root-absolute
        # paths, and protocol-relative URLs.
        if "://" in raw or raw.startswith("//") or re.match(r"^[a-zA-Z][\w+.-]*:", raw):
            continue
        if raw.startswith("/"):
            continue
        target = _clean_target(raw)
        # Require a path-like target so bare placeholders like "(url)" or
        # "(text)" in documentation examples are ignored.
        if not target or not _looks_like_path(target):
            continue
        key = ("link", target)
        if key not in seen:
            seen.add(key)
            refs.append(Reference(target=target, kind="link"))

    return refs


def resolves(target: str, bases: List[Path]) -> bool:
    """Whether a reference target resolves under any of the given bases.

    Uses ``lexists`` so a dangling symlink still counts as resolved: the
    reference/ tree in this repo is symlinked in but only checked out
    on-demand, so its symlink targets are routinely absent.
    """
    for base in bases:
        candidate = base / target
        try:
            if candidate.exists() or candidate.is_symlink():
                return True
        except OSError:
            continue
    return False


def is_gitignored(target: str, bases: List[Path]) -> bool:
    """Whether a reference target is a deliberately git-ignored path.

    Some references intentionally point at host-local files kept out of version
    control -- e.g. a per-machine ``LOCALCONTEXT.md`` listed in ``.gitignore``
    ("you are running on mantis"). Those files are absent from a fresh checkout
    and from CI, so the plain existence check in ``resolves`` flags them as
    broken even though the reference is correct. We treat a target as resolved
    when, under any of its bases, git reports the path as ignored.
    ``git check-ignore`` matches on patterns rather than on the file existing,
    so this holds in CI where the host-local file is genuinely absent.
    """
    for base in bases:
        try:
            result = subprocess.run(
                ["git", "-C", str(base), "check-ignore", "-q", target],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        # 0 = path is ignored; 1 = not ignored; 128 = outside a work tree / bad
        # path. Only a clean match counts.
        if result.returncode == 0:
            return True
    return False


def validate_references(
    ruleset: "RuleSet", output_dir: Path, input_dir: Path
) -> List[str]:
    """Check that every @-reference and relative markdown link resolves.

    Resolution bases per source file:

    - ``.mdc`` auto/contextual rules: the generation root (``input_dir``) and
      the rule file's own directory. The first is where the Claude adapter
      embeds the rule (so its refs resolve from the repo root); the second is
      how the Cursor adapter embeds sibling ``atoms/`` content.
    - ``AGENTS.md``/``SKILL.md``: the file's own directory and the repository
      (generation) root.

    A reference is an error only if it resolves under none of its bases and its
    target is not git-ignored (deliberately host-local files are exempt).

    Args:
        ruleset: The loaded ruleset (auto/contextual/agents/skills).
        output_dir: Output directory (repository / generation root).
        input_dir: Input directory containing the rules/ subdirectory.

    Returns:
        A list of human-readable error messages (empty if all references
        resolve).
    """
    output_dir = Path(output_dir)
    input_dir = Path(input_dir)
    errors: List[str] = []

    # (source_path, content, candidate_bases) for everything we scan.
    sources: List[tuple[Path, str, List[Path]]] = []

    # Auto/contextual rules are .mdc files. They resolve from the generation
    # root and from the rule's own directory (sibling atoms/ embeds).
    for rule in ruleset.auto + ruleset.contextual:
        bases = [input_dir, output_dir, rule.path.parent]
        sources.append((rule.path, rule.content, bases))

    # AGENTS files resolve from their own directory and the repo root.
    for rule in ruleset.agents:
        sources.append((rule.path, rule.content, [rule.path.parent, output_dir]))

    # Skills (SKILL.md) resolve from their own directory and the repo root.
    for skill in ruleset.skills:
        sources.append((skill.path, skill.content, [skill.path.parent, output_dir]))

    for source_path, content, bases in sources:
        for ref in extract_references(content):
            if resolves(ref.target, bases):
                continue
            # A reference to a deliberately git-ignored host-local file (e.g.
            # LOCALCONTEXT.md) is correct even though the file is absent from a
            # fresh checkout / CI -- don't flag it as broken.
            if is_gitignored(ref.target, bases):
                continue
            try:
                rel_source = source_path.relative_to(output_dir)
            except ValueError:
                rel_source = source_path
            label = "reference" if ref.kind == "at" else "link"
            base_list = ", ".join(str(b) for b in bases)
            errors.append(
                f"Broken {label} '{ref.target}' in {rel_source} "
                f"(resolves under none of: {base_list})"
            )

    return errors

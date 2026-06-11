"""Git-aware file discovery for repository-wide scans.

Repo-wide scans (AGENTS file discovery, cleanup of generated files) run in
one of two modes:

- ``git``: only files git knows about (tracked files, recursing into
  submodules). Selected automatically when the output directory is inside a
  git work tree.
- ``filesystem``: a recursive directory walk that prunes ignored directories
  and never follows directory symlinks. Because a plain walk can pick up far
  more than intended (vendored checkouts, build outputs), it requires an
  explicit opt-in via ``--no-git`` or ``discovery: filesystem`` in the
  config.
"""

import fnmatch
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Literal, Optional, Set, Tuple

DiscoveryMode = Literal["git", "filesystem"]

VALID_DISCOVERY_SETTINGS = ("auto", "git", "filesystem")


class DiscoveryError(Exception):
    """Raised when a usable discovery mode cannot be resolved."""


def is_git_work_tree(root: Path) -> bool:
    """Return True if root is inside a git work tree (and git is available)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def resolve_discovery_mode(
    configured: str, force_filesystem: bool, root: Path
) -> DiscoveryMode:
    """Resolve the discovery mode for a run.

    Args:
        configured: The ``discovery`` config setting (auto/git/filesystem)
        force_filesystem: True when --no-git was passed on the command line
        root: The output directory (repository root) scans run against

    Returns:
        The resolved mode

    Raises:
        DiscoveryError: If root is not inside a git work tree and filesystem
            scanning was not explicitly requested
    """
    if force_filesystem or configured == "filesystem":
        return "filesystem"
    if is_git_work_tree(root):
        return "git"
    if configured == "git":
        raise DiscoveryError(
            f"'{root}' is not inside a git work tree, but the config requires "
            "'discovery: git'."
        )
    raise DiscoveryError(
        f"'{root}' is not inside a git work tree. Pass --no-git to scan the "
        "directory recursively, or set 'discovery: filesystem' in the config."
    )


def expand_braces(pattern: str) -> List[str]:
    """Expand a single ``{a,b}`` group: ``**/AGENTS.{md,mdc}`` -> two patterns."""
    if "{" in pattern and "}" in pattern:
        start = pattern.index("{")
        end = pattern.index("}")
        prefix = pattern[:start]
        suffix = pattern[end + 1 :]
        options = pattern[start + 1 : end].split(",")
        return [prefix + option.strip() + suffix for option in options]
    return [pattern]


class Discovery:
    """Mode-aware file discovery rooted at the output directory."""

    def __init__(
        self, root: Path, mode: DiscoveryMode, ignored_directories: List[str]
    ):
        self.root = Path(root)
        self.mode: DiscoveryMode = mode
        self.ignored_directories = ignored_directories
        self._tracked_cache: Optional[List[str]] = None
        self._untracked_cache: Optional[List[str]] = None

    @classmethod
    def fallback(cls, root: Path) -> "Discovery":
        """Default for adapters invoked without a Discovery (i.e. not via the
        CLI, which always builds one from the config): a plain filesystem walk
        with no ignore list, matching the adapters' pre-discovery behavior."""
        return cls(root, "filesystem", [])

    def files(self, patterns: List[str]) -> List[Path]:
        """Non-ignored files under root matching any of the glob patterns.

        In git mode only git-tracked files are returned (the discovery source
        of truth); use untracked_matches() to surface candidates skipped
        because they are not tracked yet.
        """
        candidates = self._tracked() if self.mode == "git" else self._walk_files()
        return self._filter(candidates, patterns)

    def untracked_matches(self, patterns: List[str]) -> List[Path]:
        """Untracked-but-not-gitignored files that would otherwise match.

        Only meaningful in git mode; returns [] in filesystem mode.
        """
        if self.mode != "git":
            return []
        return self._filter(self._untracked(), patterns)

    def cleanup_files(self, patterns: List[str]) -> List[Path]:
        """Files eligible for cleanup of generated artifacts.

        In git mode this is tracked plus untracked-but-not-gitignored files,
        so freshly generated (not yet committed) artifacts are still cleaned
        while gitignored areas (vendored checkouts, build outputs) are left
        alone. In filesystem mode it is the same pruned walk used for
        discovery.
        """
        if self.mode == "git":
            candidates = self._tracked() + self._untracked()
        else:
            candidates = self._walk_files()
        return self._filter(candidates, patterns)

    def cleanup_dirs(self, rel_target: str) -> List[Path]:
        """Directories matching a relative path suffix, e.g. ``.cursor/rules``.

        Generated directories are typically gitignored, so they can't be
        listed by git directly: in git mode every directory that contains a
        tracked (or untracked, non-gitignored) file is probed for the target;
        in filesystem mode the pruned walk looks for the target's first
        component directly, even if it appears in ignored_directories, since
        the target itself is what we're looking for.
        """
        first, *rest = PurePosixPath(rel_target).parts
        found: Set[Path] = set()

        if self.mode == "git":
            for parent in self._populated_dirs():
                rel_parts = parent.relative_to(self.root).parts
                if rel_parts and self._is_ignored_parts(rel_parts):
                    continue
                candidate = parent.joinpath(first, *rest)
                if candidate.is_dir():
                    found.add(candidate)
        else:
            for dirpath, dirnames, _ in os.walk(self.root):
                rel_dir = Path(dirpath).relative_to(self.root)
                kept: List[str] = []
                for name in dirnames:
                    if name == first:
                        candidate = Path(dirpath).joinpath(name, *rest)
                        if candidate.is_dir():
                            found.add(candidate)
                        continue  # never descend into the target itself
                    if not self._is_ignored_parts((rel_dir / name).parts):
                        kept.append(name)
                dirnames[:] = kept

        return sorted(found)

    def is_ignored(self, file_path: Path) -> bool:
        """Whether a path falls inside a configured ignored directory."""
        try:
            relative_path = file_path.relative_to(self.root)
        except ValueError:
            # Path is not relative to root
            return False
        return self._is_ignored_parts(relative_path.parts)

    def _is_ignored_parts(self, parts: Tuple[str, ...]) -> bool:
        rel_str = "/".join(parts)

        for ignored_dir in self.ignored_directories:
            # Remove glob patterns if present
            ignored_dir = ignored_dir.rstrip("/*")

            # Multi-component patterns (e.g. "private/hass/config/custom_components")
            # match by path prefix instead of single-component equality.
            if "/" in ignored_dir:
                if rel_str == ignored_dir or rel_str.startswith(ignored_dir + "/"):
                    return True
                continue

            # Check if any part of the path matches an ignored directory
            for part in parts:
                if part == ignored_dir or part.startswith(ignored_dir):
                    return True

                # Handle wildcard patterns
                if "*" in ignored_dir and fnmatch.fnmatch(part, ignored_dir):
                    return True

        return False

    def _filter(
        self, rel_candidates: Iterable[str], patterns: List[str]
    ) -> List[Path]:
        matched: List[Path] = []
        for rel in rel_candidates:
            if not self._matches(rel, patterns):
                continue
            path = self.root / rel
            if self._is_ignored_parts(PurePosixPath(rel).parts):
                continue
            if path.is_file():
                matched.append(path)
        return sorted(matched)

    @staticmethod
    def _matches(rel_posix: str, patterns: Iterable[str]) -> bool:
        for pattern in patterns:
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
            # glob's '**/' may match zero directories; fnmatch has no '**'
            # semantics, so also check the bare remainder for root-level files.
            if pattern.startswith("**/") and fnmatch.fnmatch(rel_posix, pattern[3:]):
                return True
        return False

    def _tracked(self) -> List[str]:
        if self._tracked_cache is None:
            self._tracked_cache = self._git_ls_files(
                "--cached", "--recurse-submodules"
            )
        return self._tracked_cache

    def _untracked(self) -> List[str]:
        if self._untracked_cache is None:
            # --recurse-submodules only works with --cached; untracked files
            # inside submodules are out of scope.
            self._untracked_cache = self._git_ls_files(
                "--others", "--exclude-standard"
            )
        return self._untracked_cache

    def _git_ls_files(self, *args: str) -> List[str]:
        result = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "-z", *args],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise DiscoveryError(f"git ls-files failed in '{self.root}': {stderr}")
        stdout = result.stdout.decode("utf-8", errors="surrogateescape")
        return [entry for entry in stdout.split("\0") if entry]

    def _walk_files(self) -> List[str]:
        rels: List[str] = []
        # os.walk does not follow directory symlinks, unlike recursive glob,
        # so build outputs symlinked into the tree (e.g. Nix `result`) are
        # never traversed.
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = Path(dirpath).relative_to(self.root)
            dirnames[:] = [
                d
                for d in dirnames
                if not self._is_ignored_parts((rel_dir / d).parts)
            ]
            for name in filenames:
                rels.append((rel_dir / name).as_posix())
        return rels

    def _populated_dirs(self) -> Set[Path]:
        """All directories containing at least one git-known file, plus root."""
        dirs: Set[Path] = {self.root}
        for rel in self._tracked() + self._untracked():
            parent = PurePosixPath(rel).parent
            while str(parent) != ".":
                dirs.add(self.root / parent)
                parent = parent.parent
        return dirs

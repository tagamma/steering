import os
from pathlib import Path
from typing import Dict, List

from .config import Config


class SkillConflictError(Exception):
    """Raised when a skill destination conflicts with an existing non-symlink entry."""

    pass


def sync_skills(
    config: Config,
    output_dir: Path,
    vendors: List[str],
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Sync shared skills by symlinking them into vendor-specific destinations.

    For each skill directory under the shared path, creates a symlink in each
    vendor's skills destination. Detects conflicts where a destination already
    exists but isn't a symlink to the expected source.

    Args:
        config: Configuration object with skills settings
        output_dir: Output directory (repository root)
        vendors: List of active vendor names to sync skills for
        dry_run: If True, don't create actual symlinks

    Returns:
        Dict mapping created symlink paths (relative to output_dir) to
        "SYMLINK->{target}" strings

    Raises:
        SkillConflictError: If a destination exists and isn't a symlink to
            the expected source
    """
    files: Dict[str, str] = {}

    if not config.skills_shared_path:
        return files

    shared_path = output_dir / config.skills_shared_path

    if not shared_path.is_dir():
        return files

    # Discover skill directories (immediate subdirectories of shared_path)
    skill_dirs = sorted(
        [d for d in shared_path.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )

    if not skill_dirs:
        return files

    # Filter vendor_destinations to only active vendors
    active_destinations = {
        vendor: dest_path
        for vendor, dest_path in config.skills_vendor_destinations.items()
        if vendor in vendors
    }

    if not active_destinations:
        return files

    skill_names = {d.name for d in skill_dirs}

    for vendor, dest_rel_path in active_destinations.items():
        dest_dir = output_dir / dest_rel_path

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Clean up stale symlinks: symlinks that point into shared_path
            # but whose target no longer exists (skill was removed)
            _cleanup_stale_skill_symlinks(dest_dir, shared_path, skill_names)

        for skill_dir in skill_dirs:
            skill_name = skill_dir.name
            link_path = dest_dir / skill_name

            # Calculate relative symlink target
            try:
                relative_target = os.path.relpath(skill_dir, dest_dir)
            except ValueError:
                relative_target = str(skill_dir)

            # Check for conflicts
            if link_path.exists() or link_path.is_symlink():
                if link_path.is_symlink():
                    existing_target = os.readlink(link_path)
                    # Resolve to absolute for comparison
                    existing_abs = (dest_dir / existing_target).resolve()
                    expected_abs = skill_dir.resolve()

                    if existing_abs == expected_abs:
                        # Already correctly symlinked, record and skip
                        try:
                            rel_link = link_path.relative_to(output_dir)
                            files[str(rel_link)] = f"SYMLINK->{relative_target}"
                        except ValueError:
                            files[str(link_path)] = f"SYMLINK->{relative_target}"
                        continue
                    else:
                        raise SkillConflictError(
                            f"Conflict: '{link_path.relative_to(output_dir)}' is a "
                            f"symlink to '{existing_target}', but expected it to "
                            f"point to shared skill '{skill_dir.relative_to(output_dir)}'"
                        )
                else:
                    raise SkillConflictError(
                        f"Conflict: '{link_path.relative_to(output_dir)}' already "
                        f"exists and is not a symlink. Cannot symlink shared skill "
                        f"'{skill_dir.relative_to(output_dir)}' there."
                    )

            # Record the symlink
            try:
                rel_link = link_path.relative_to(output_dir)
                files[str(rel_link)] = f"SYMLINK->{relative_target}"
            except ValueError:
                files[str(link_path)] = f"SYMLINK->{relative_target}"

            # Create the symlink
            if not dry_run:
                link_path.symlink_to(relative_target)

    return files


def _cleanup_stale_skill_symlinks(
    dest_dir: Path,
    shared_path: Path,
    current_skill_names: set[str],
) -> None:
    """Remove symlinks in dest_dir that point into shared_path but are stale.

    A symlink is stale if it points into the shared skills directory but the
    target no longer exists (the skill was removed from shared_path).

    Only touches symlinks whose resolved target falls under shared_path.
    Non-symlink entries and symlinks pointing elsewhere are left alone.

    Args:
        dest_dir: The vendor's skills destination directory
        shared_path: The shared skills source directory
        current_skill_names: Names of skills currently in shared_path
    """
    if not dest_dir.is_dir():
        return

    shared_resolved = shared_path.resolve()

    for entry in dest_dir.iterdir():
        if not entry.is_symlink():
            continue

        # Resolve where this symlink points
        try:
            target_resolved = (dest_dir / os.readlink(entry)).resolve()
        except (OSError, ValueError):
            continue

        # Only touch symlinks that point into the shared skills directory
        try:
            target_resolved.relative_to(shared_resolved)
        except ValueError:
            continue

        # If the skill name is no longer in shared_path, remove the stale symlink
        if entry.name not in current_skill_names:
            try:
                entry.unlink()
                print(f"Removed stale skill symlink: {entry}")
            except OSError as e:
                print(f"WARN: Failed to remove stale symlink {entry}: {e}")

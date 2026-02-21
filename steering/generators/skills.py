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

    for vendor, dest_rel_path in active_destinations.items():
        dest_dir = output_dir / dest_rel_path

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

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

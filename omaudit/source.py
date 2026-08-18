"""
Fetching and locating plugin sources.

Shared by census.py (bulk ecosystem audits) and `omaudit add` (single-plugin
installs) so there is one clone implementation, not two slightly different
ones that drift apart.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def rmtree_force(path: Path) -> None:
    """shutil.rmtree alone can't delete a clone's .git/objects on Windows —
    git marks packed objects read-only, so unlink fails with a permission
    error. Clear the flag and retry."""
    def onerror(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def current_commit(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, timeout=30, text=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def is_cached(spec: str, dest: Path) -> bool:
    """True if dest already holds the exact source spec asks for, so clone()
    can skip the network entirely."""
    if not dest.exists():
        return False
    _, _, commit = spec.partition("@")
    if commit:
        return current_commit(dest) == commit
    return (dest / ".git").is_dir()


def clone(spec: str, dest: Path) -> Path | None:
    """spec is 'url' or 'url@commit'. A pinned commit is fetched directly
    (what census.py uses, so audits describe exactly what was listed); a
    bare url does a normal shallow clone of the default branch (what
    `omaudit add` uses, since it's installing whatever HEAD is right now)."""
    url, _, commit = spec.partition("@")
    if dest.exists():
        if is_cached(spec, dest):
            return dest
        rmtree_force(dest)
    try:
        if commit:
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--quiet", str(dest)],
                           check=True, capture_output=True, timeout=60)
            subprocess.run(["git", "-C", str(dest), "remote", "add", "origin", url],
                           check=True, capture_output=True, timeout=60)
            subprocess.run(["git", "-C", str(dest), "fetch", "--depth", "1",
                            "--quiet", "origin", commit],
                           check=True, capture_output=True, timeout=180)
            subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", "FETCH_HEAD"],
                           check=True, capture_output=True, timeout=60)
        else:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
                check=True, capture_output=True, timeout=180,
            )
        return dest
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"  ! clone failed: {spec} ({type(exc).__name__})", file=sys.stderr)
        return None


def find_plugin_roots(root: Path) -> list[Path]:
    """A repo may hold one plugin at its root or several in subdirectories.

    Omarchy's first-party tree mixes both: `shell/plugins/clipboard/` next
    to `shell/plugins/panels/weather/`. A one-level glob would see the
    top-level plugins and never look at `panels/` / `services/`."""
    if (root / "manifest.json").is_file():
        return [root]
    from .scan import SKIP_DIRS
    found: list[Path] = []
    for manifest in sorted(root.rglob("manifest.json")):
        rel = manifest.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        found.append(manifest.parent)
    return found

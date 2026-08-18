"""Filesystem locations: user plugins, first-party plugins, baseline store.

First-party plugins live under `$OMARCHY_PATH/shell/plugins` (default
`/usr/share/omarchy/...`) and are owned by the package, so their baselines
cannot sit next to the QML. Those go in `~/.config/omaudit/baselines/`.
"""

import os
from pathlib import Path

DEFAULT_OMARCHY = Path("/usr/share/omarchy")


def omarchy_root() -> Path:
    raw = os.environ.get("OMARCHY_PATH")
    return Path(raw).expanduser() if raw else DEFAULT_OMARCHY


def user_plugins_dir() -> Path:
    return Path.home() / ".config" / "omarchy" / "plugins"


def builtin_plugins_dir() -> Path:
    return omarchy_root() / "shell" / "plugins"


def baseline_store_dir() -> Path:
    return Path.home() / ".config" / "omaudit" / "baselines"


def report_card_path() -> Path:
    return Path.home() / ".config" / "omaudit" / "report-card.txt"


def census_dir() -> Path:
    return Path.home() / ".config" / "omaudit" / "census"


def clone_cache_dir() -> Path:
    return Path.home() / ".cache" / "omaudit" / "clones"


def omarchy_version() -> str | None:
    try:
        text = (omarchy_root() / "version").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def is_under(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def is_builtin(plugin_dir: Path) -> bool:
    return is_under(plugin_dir, builtin_plugins_dir())


def sidecar_writable(plugin_dir: Path) -> bool:
    sidecar = plugin_dir / ".omaudit-baseline.json"
    try:
        if sidecar.exists():
            return os.access(sidecar, os.W_OK)
        return os.access(plugin_dir, os.W_OK)
    except OSError:
        return False


def baseline_path(plugin_dir: Path, plugin_id: str) -> Path:
    """Sidecar next to the plugin when we can write there; otherwise the
    XDG store. First-party plugins live in /usr/share and must use the store."""
    sidecar = plugin_dir / ".omaudit-baseline.json"
    if sidecar.is_file() or sidecar_writable(plugin_dir):
        return sidecar
    safe = plugin_id.replace("/", "_")
    return baseline_store_dir() / f"{safe}.json"

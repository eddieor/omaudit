"""
manifest.json handling.

Reimplements the structural rules Omarchy's own `omarchy plugin validate`
enforces, then adds the proposed `permissions` block on top. Keeping our own
copy of the structural checks means omaudit runs in CI on a machine with no
Omarchy installed.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .capabilities import CAPABILITIES

KIND_ENTRYPOINTS = {
    "bar-widget": ("barWidget", "BarWidget.qml"),
    "panel": ("panel", "Panel.qml"),
    "overlay": ("overlay", "Overlay.qml"),
    "menu": ("menu", "Menu.qml"),
    "service": ("service", "Service.qml"),
    "bar": ("bar", "Bar.qml"),
}

REQUIRED_FIELDS = ["schemaVersion", "id", "name", "version", "kinds", "entryPoints"]
RESERVED_ID_PREFIX = "omarchy."


@dataclass
class Manifest:
    path: Path
    data: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def id(self) -> str:
        return str(self.data.get("id", "<unknown>"))

    @property
    def has_permissions_block(self) -> bool:
        return self.data.get("permissions") is not None

    @property
    def declared(self) -> set[str]:
        perms = self.data.get("permissions") or {}
        if not isinstance(perms, dict):
            return set()
        return {k for k in perms if k in CAPABILITIES}

    def declared_scope(self, capability: str) -> list[str]:
        perms = self.data.get("permissions") or {}
        entry = perms.get(capability)
        if isinstance(entry, dict):
            scope = entry.get("scope", [])
            return [str(s) for s in scope] if isinstance(scope, list) else []
        return []

    def reason(self, capability: str) -> str:
        perms = self.data.get("permissions") or {}
        entry = perms.get(capability)
        if isinstance(entry, dict):
            return str(entry.get("reason", ""))
        return ""


def _safe_relative(root: Path, value: str) -> bool:
    if os.path.isabs(value) or value.startswith("~"):
        return False
    try:
        resolved = (root / value).resolve()
        return resolved.is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def load(plugin_dir: Path) -> Manifest:
    mpath = plugin_dir / "manifest.json"
    m = Manifest(path=mpath)

    if not mpath.is_file():
        m.errors.append("manifest.json not found")
        return m

    try:
        m.data = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        m.errors.append(f"manifest.json is not valid JSON: {exc}")
        return m

    if not isinstance(m.data, dict):
        m.errors.append("manifest.json must contain a JSON object")
        return m

    for field_name in REQUIRED_FIELDS:
        if field_name not in m.data:
            m.errors.append(f"missing required field: '{field_name}'")

    plugin_id = str(m.data.get("id", ""))
    if plugin_id.startswith(RESERVED_ID_PREFIX):
        m.errors.append(f"id '{plugin_id}' uses the reserved 'omarchy.*' namespace")
    if plugin_id and "." not in plugin_id:
        m.warnings.append(f"id '{plugin_id}' is not namespaced; collisions are likely")

    kinds = m.data.get("kinds") or []
    entry_points = m.data.get("entryPoints") or {}
    if not isinstance(kinds, list) or not kinds:
        m.errors.append("'kinds' must be a non-empty array")
        kinds = []
    if not isinstance(entry_points, dict):
        m.errors.append("'entryPoints' must be an object")
        entry_points = {}

    for kind in kinds:
        mapping = KIND_ENTRYPOINTS.get(kind)
        if not mapping:
            m.errors.append(f"unknown plugin kind: '{kind}'")
            continue
        key, _default = mapping
        if key not in entry_points:
            m.errors.append(f"kind '{kind}' requires entryPoints.{key}")

    for key, value in entry_points.items():
        if not isinstance(value, str):
            m.errors.append(f"entryPoints.{key} must be a string")
            continue
        if not _safe_relative(plugin_dir, value):
            m.errors.append(f"entryPoints.{key} is not a safe relative path: '{value}'")
            continue
        if not (plugin_dir / value).is_file():
            m.errors.append(f"entry point file not found: '{value}'")

    for path in plugin_dir.rglob("*"):
        if path.is_symlink():
            rel = path.relative_to(plugin_dir)
            m.errors.append(f"plugin folder contains a symlink: '{rel}'")

    perms = m.data.get("permissions")
    if perms is None:
        m.warnings.append(
            "no 'permissions' block: capabilities cannot be checked against intent"
        )
    elif not isinstance(perms, dict):
        m.errors.append("'permissions' must be an object")
    else:
        for key, entry in perms.items():
            if key not in CAPABILITIES:
                m.errors.append(f"unknown capability in permissions: '{key}'")
                continue
            if not isinstance(entry, dict):
                m.errors.append(f"permissions.{key} must be an object")
                continue
            if not entry.get("reason"):
                m.warnings.append(f"permissions.{key} has no 'reason'")
            cap = CAPABILITIES[key]
            if cap.needs_scope and not entry.get("scope"):
                m.warnings.append(
                    f"permissions.{key} declares no 'scope' ({cap.scope_hint})"
                )

    return m


def suggest_permissions(observed: dict[str, set[str]]) -> dict:
    """Turn a scan result into a permissions block the author can paste."""
    block = {}
    for cap_id in sorted(observed):
        cap = CAPABILITIES[cap_id]
        entry: dict = {"reason": f"TODO: why does this plugin need to {cap.title.lower()}?"}
        if cap.needs_scope:
            entry["scope"] = sorted(observed[cap_id]) or ["TODO"]
        block[cap_id] = entry
    return block

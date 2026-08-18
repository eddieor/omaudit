"""
Static scanner.

Walks a plugin directory, reads every text file, strips comments so commented-out
code and prose don't produce findings, and applies the rule set line by line.

This is deliberately a *lint*, not a proof. It cannot decide whether a plugin is
malicious; it decides what a plugin is capable of, which is the question a
reviewer can actually act on.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .rules import RULES, scope_is_sensitive

TEXT_SUFFIXES = {".qml", ".js", ".mjs", ".json", ".jsonc", ".toml", ".sh",
                 ".bash", ".py", ".conf", ".md", ".lua", ".yml", ".yaml"}
# Behavioral rules run only over code, not metadata. manifest.json and other
# .json/.jsonc/.toml/.yml/.yaml/.conf files are structured data, not behavior —
# scanning them for regex signals just matches prose and config values (a
# meditation-quote plugin's own text containing the word "grim" once graded F
# on that alone). Those files still feed manifest validation elsewhere.
SCANNED_SUFFIXES = {".qml", ".js", ".mjs", ".sh", ".bash", ".py", ".lua"}
# Test code exercises the same APIs a plugin's runtime does (mock servers,
# `new Function` module loaders, stubbed binaries) without ever running inside
# the shell process. Excluding it removed the majority of the rare-capability
# false positives found by hand: 5/6 net.listen and 16/20 code.dynamic hits in
# the first ecosystem census were entirely test-directory code.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv",
             "test", "tests", "testbed", "spec", "specs", "__tests__"}
MAX_BYTES = 2_000_000
ASSET_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico", ".bmp",
    ".ttf", ".otf", ".woff", ".woff2",
    ".wav", ".mp3", ".ogg", ".flac",
)

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"(?<![:\"'\w])//[^\n]*")


@dataclass
class Finding:
    rule_id: str
    capability: str
    file: str
    line: int
    snippet: str
    why: str
    scope: str | None = None


@dataclass
class ScanResult:
    plugin_dir: Path
    findings: list[Finding] = field(default_factory=list)
    binaries: list[str] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def observed(self) -> set[str]:
        caps = {f.capability for f in self.findings}
        if self.binaries:
            caps.add("binary.bundled")
        return caps

    def scopes(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for f in self.findings:
            if f.scope:
                out.setdefault(f.capability, set()).add(f.scope)
        if self.binaries:
            out.setdefault("binary.bundled", set()).update(self.binaries)
        return out

    def by_capability(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.capability, []).append(f)
        return out


def _looks_binary(path: Path) -> bool:
    try:
        chunk = path.open("rb").read(4096)
    except OSError:
        return True
    if b"\x00" in chunk:
        return True
    if chunk[:4] in (b"\x7fELF", b"MZ\x90\x00"):
        return True
    return False


def _strip_comments(text: str) -> str:
    """Blank out comments while preserving line numbering."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    text = BLOCK_COMMENT.sub(blank, text)
    text = LINE_COMMENT.sub(blank, text)
    return text


def scan(plugin_dir: Path) -> ScanResult:
    result = ScanResult(plugin_dir=plugin_dir)
    seen: set[tuple] = set()

    for path in sorted(plugin_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(plugin_dir).parts):
            continue

        rel = str(path.relative_to(plugin_dir))
        suffix = path.suffix.lower()

        if suffix not in TEXT_SUFFIXES:
            if _looks_binary(path) and suffix not in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
                result.binaries.append(rel)
            continue
        if suffix not in SCANNED_SUFFIXES:
            continue
        if path.stat().st_size > MAX_BYTES:
            result.binaries.append(f"{rel} (oversized, not scanned)")
            continue

        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            result.binaries.append(f"{rel} (unreadable as text)")
            continue

        result.files_scanned += 1
        cleaned = _strip_comments(raw)

        for lineno, line in enumerate(cleaned.splitlines(), start=1):
            if not line.strip():
                continue
            for rule in RULES:
                for m in rule.pattern.finditer(line):
                    scope = rule.extract(m) if rule.extract else None
                    capability = rule.capability

                    # A path finding is only interesting if it leaves the
                    # plugin folder; a credential path escalates. A bundled
                    # image/font/sound asset referenced by absolute or ~/$
                    # path is neither — it's not reading the user's files.
                    if capability in ("fs.read", "fs.write") and scope:
                        if scope_is_sensitive(scope):
                            capability = "fs.sensitive"
                        elif not scope.startswith(("~", "/", "$")):
                            continue
                        elif scope.lower().endswith(ASSET_SUFFIXES):
                            continue

                    key = (rule.id, capability, rel, lineno, scope)
                    if key in seen:
                        continue
                    seen.add(key)
                    result.findings.append(Finding(
                        rule_id=rule.id,
                        capability=capability,
                        file=rel,
                        line=lineno,
                        snippet=line.strip()[:160],
                        why=rule.why,
                        scope=scope,
                    ))

    return result

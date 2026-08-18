"""
Detection rules.

Each rule maps a syntactic signal in QML/JS to a capability. Rules are data, not
code, so the set can grow without touching the scanner. `extract` optionally
pulls a scope value (a hostname, a binary name, a path) out of the match so the
report can say *which* host, not just "network".
"""

import re
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Rule:
    id: str
    capability: str
    pattern: re.Pattern
    why: str
    extract: Optional[Callable[[re.Match], Optional[str]]] = None


def _g(n: int) -> Callable[[re.Match], Optional[str]]:
    def inner(m: re.Match) -> Optional[str]:
        try:
            return m.group(n)
        except IndexError:
            return None
    return inner


def _first_quoted_cmd(m: re.Match) -> Optional[str]:
    """First quoted token after the match. `execDetached` is often written
    as a ternary (`execDetached(cond ? ["cmd"] : ["other"])`), so the
    binary isn't the first identifier after `(`."""
    found = re.search(r"""["']([\w./-]+)""", m.string[m.end():])
    return found.group(1) if found else None

# Paths that mean "credentials" on an Omarchy box.
SENSITIVE_PATHS = [
    r"\.ssh", r"\.gnupg", r"\.aws", r"\.kube", r"\.netrc", r"\.npmrc",
    r"\.docker/config", r"\.git-credentials",
    # dotenv *files* only — not "\.env\b", which also matches ordinary
    # property/method access like `Quickshell.env("HOME")` or `process.env`.
    # Lookbehind keeps the prefix out of the match so extracted scope is
    # `.env` / `.env.local`, not `/.env` or ` .env`.
    r"(?:^|(?<=[\"'/\s]))\.env(?:\.[A-Za-z0-9_-]+)?(?=[\"'\s]|$)",
    r"\.config/1Password", r"\.password-store", r"\.local/share/keyrings",
    r"\.mozilla", r"\.config/(?:google-)?chrom(?:e|ium)", r"\.config/BraveSoftware",
    r"\.claude(?:\.json)?", r"\.codex", r"\.config/gh/hosts",
    r"id_rsa", r"id_ed25519", r"credentials\.json", r"secrets?\.(?:json|toml|yaml|yml)",
]

# Commands that reach the network when exec'd.
NET_BINARIES = r"curl|wget|nc\b|ncat|socat|ssh\b|scp\b|rsync|http(?:ie)?\b"

RULES: list[Rule] = [
    # --- execution ---------------------------------------------------------
    Rule("exec.process-object", "process.exec",
         re.compile(r"\bProcess\s*\{"),
         "instantiates a Quickshell Process, which runs a program"),
    Rule("exec.command-prop", "process.exec",
         re.compile(r"\bcommand\s*:\s*\[\s*[\"']([^\"']+)[\"']"),
         "declares a command to execute", extract=_g(1)),
    Rule("exec.command-assign", "process.exec",
         re.compile(r"\bcommand\s*=\s*\[\s*[\"']([^\"']+)[\"']"),
         "assigns a command to execute", extract=_g(1)),
    Rule("exec.detached", "process.exec",
         re.compile(r"\bQuickshell\.execDetached\s*\("),
         "launches a detached process", extract=_first_quoted_cmd),
    Rule("exec.startdetached", "process.exec",
         re.compile(r"\bstartDetached\s*\("),
         "launches a detached process"),
    Rule("exec.shell-c", "process.exec",
         re.compile(r"[\"'](?:/bin/)?(?:ba|z|d)?sh[\"']\s*,\s*[\"']-c[\"']"),
         "runs an arbitrary shell command string"),

    Rule("exec.privileged", "process.privileged",
         re.compile(r"[\"'\s](sudo|pkexec|doas)[\"'\s]"),
         "escalates to root", extract=_g(1)),
    Rule("exec.systemctl", "process.privileged",
         re.compile(r"systemctl\s+(?!--user)(start|stop|enable|disable|mask)"),
         "changes system services", extract=_g(1)),

    # --- dynamic code ------------------------------------------------------
    Rule("code.createqml", "code.dynamic",
         re.compile(r"Qt\.createQmlObject\s*\("),
         "compiles QML from a string at runtime"),
    Rule("code.eval", "code.dynamic",
         re.compile(r"\beval\s*\(|new\s+Function\s*\("),
         "evaluates JavaScript from a string"),
    Rule("code.b64", "code.dynamic",
         re.compile(r"\b(?:atob|base64\s+-d|base64\s+--decode)\b"),
         "decodes base64 payloads, a common way to hide a command"),
    Rule("code.remote-import", "code.dynamic",
         re.compile(r"^\s*import\s+[\"']https?://", re.M),
         "imports QML from a remote URL"),

    # --- filesystem --------------------------------------------------------
    Rule("fs.fileview", "fs.read",
         re.compile(r"\bFileView\s*\{"),
         "reads a file through FileView"),
    Rule("fs.path-prop", "fs.read",
         re.compile(r"\bpath\s*:\s*[\"']([^\"']+)[\"']"),
         "references a filesystem path", extract=_g(1)),
    Rule("fs.xhr-file", "fs.read",
         re.compile(r"[\"']file://([^\"']+)"),
         "reads a file:// URL", extract=_g(1)),
    Rule("fs.write", "fs.write",
         re.compile(r"\b(?:writeAdapter|Qt\.labs\.settings|writeFileSync\s*\("
                    r"|writeFile\s*\(|appendFileSync\s*\(|appendFile\s*\(|saveToFile\s*\()"),
         "writes to disk"),
    Rule("fs.redirect", "fs.write",
         re.compile(r"[\"'][^\"']*\s>>?\s*[~/$][^\"']*[\"']"),
         "redirects command output into a file"),

    Rule("fs.sensitive", "fs.sensitive",
         re.compile(r"(" + "|".join(SENSITIVE_PATHS) + r")"),
         "references a path that normally holds credentials", extract=_g(1)),

    Rule("shell.mutate", "shell.mutate",
         re.compile(r"\.config/omarchy/(shell\.toml|omarchy-menu\.jsonc|plugins|themes)"),
         "writes into Omarchy's own configuration", extract=_g(1)),
    Rule("shell.omarchy-cli", "shell.mutate",
         re.compile(r"[\"']omarchy[\"']\s*,\s*[\"'](plugin|bar|theme|update)[\"']"),
         "invokes the omarchy CLI to change shell state", extract=_g(1)),

    # --- network -----------------------------------------------------------
    Rule("net.xhr", "net.outbound",
         re.compile(r"\bXMLHttpRequest\b|\bfetch\s*\("),
         "makes an HTTP request"),
    Rule("net.url", "net.outbound",
         re.compile(r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
         "contacts a remote host", extract=_g(1)),
    Rule("net.binary", "net.outbound",
         re.compile(r"[\"'\s](?:" + NET_BINARIES + r")[\"'\s]"),
         "runs a network client"),
    Rule("net.socket", "net.outbound",
         re.compile(r"\bSocket\s*\{|\bWebSocket\b"),
         "opens a socket"),
    Rule("net.server", "net.listen",
         re.compile(r"\bSocketServer\s*\{|\blisten\s*\("),
         "listens for incoming connections"),

    # --- capture -----------------------------------------------------------
    Rule("input.global", "input.capture",
         re.compile(r"\bGlobalShortcut\s*\{|grabKeyboard|\bKeyboardFocus\b"),
         "registers a global input grab"),
    Rule("input.evdev", "input.capture",
         re.compile(r"/dev/input/|libinput\s+debug-events"),
         "reads raw input devices"),
    # grabToImage() deliberately excluded: it renders a QML Item you already
    # display to an image (widget export, drag-and-drop preview, transition
    # effects) and can't see anything outside that item. It is not display
    # capture — the tools below are.
    Rule("screen.grab", "screen.capture",
         re.compile(r"\bScreencopy\b|\b(?:grim|slurp|spectacle|flameshot|maim"
                    r"|wf-recorder|wl-screenrec)\b"),
         "captures screen contents"),
    Rule("audio.capture", "audio.capture",
         re.compile(r"\b(?:parecord|arecord|pw-record|ffmpeg[^\"']*-f\s+pulse)\b"),
         "records audio input"),
    Rule("clipboard.read", "clipboard.read",
         re.compile(r"\bwl-paste\b|Quickshell\.clipboardText\b(?!\s*=)"),
         "reads the clipboard"),
    Rule("clipboard.write", "clipboard.write",
         re.compile(r"\bwl-copy\b|Quickshell\.clipboardText\s*="),
         "writes the clipboard"),

    # --- integration -------------------------------------------------------
    Rule("ipc.shell", "ipc.omarchy",
         re.compile(r"\bomarchy-shell\b|\bIpcHandler\s*\{"),
         "uses Omarchy shell IPC"),
]


def scope_is_sensitive(value: str) -> bool:
    return any(re.search(p, value) for p in SENSITIVE_PATHS)

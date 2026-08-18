"""
Capability taxonomy for Omarchy Quattro shell plugins.

Plugins run unsandboxed inside the long-running Omarchy shell process with the
user's full permissions. This module defines the vocabulary used to describe
what a plugin *can* do, so that a declared set (manifest `permissions`) can be
diffed against an observed set (static scan).

The taxonomy is intentionally small. Every capability here answers a question a
reviewer would actually ask before letting code into their bar process.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    question: str          # the plain-language question this answers
    weight: int            # 0-5, contribution to risk score when undeclared
    needs_scope: bool = False   # true => declaration should carry a scope list
    scope_hint: str = ""
    install_phrase: str = ""    # terse narrative form for the `add` gate,
                                 # e.g. "runs programs" — distinct from title
                                 # ("Run programs"), which the scan/verify
                                 # report displays as-is


CAPABILITIES: dict[str, Capability] = {}


def _cap(*args, **kwargs) -> Capability:
    c = Capability(*args, **kwargs)
    CAPABILITIES[c.id] = c
    return c


# --- execution -------------------------------------------------------------
_cap("process.exec", "Run programs",
     "Does this plugin start other programs on my machine?", 3,
     needs_scope=True, scope_hint="list of argv[0] binaries, e.g. [\"nmcli\", \"jq\"]",
     install_phrase="runs programs")

_cap("process.privileged", "Escalate privileges",
     "Does it run anything as root?", 5,
     needs_scope=True, scope_hint="list of privileged commands",
     install_phrase="runs things as root")

_cap("code.dynamic", "Evaluate generated code",
     "Does it build and run code at runtime that isn't in the repo?", 5,
     install_phrase="evaluates generated code")

# --- filesystem ------------------------------------------------------------
_cap("fs.read", "Read files",
     "Which files outside its own folder does it read?", 2,
     needs_scope=True, scope_hint="path globs, e.g. [\"~/.config/omarchy/**\"]",
     install_phrase="reads files")

_cap("fs.write", "Write files",
     "Which files does it create or modify?", 3,
     needs_scope=True, scope_hint="path globs",
     install_phrase="writes files")

_cap("fs.sensitive", "Touch credentials",
     "Does it go near keys, tokens, password stores or browser profiles?", 5,
     needs_scope=True, scope_hint="path globs",
     install_phrase="touches credentials")

_cap("shell.mutate", "Reconfigure Omarchy",
     "Does it rewrite my shell, theme, bar or plugin configuration?", 4,
     needs_scope=True, scope_hint="config files touched",
     install_phrase="reconfigures the shell")

# --- network ---------------------------------------------------------------
_cap("net.outbound", "Talk to the internet",
     "Which hosts does it contact?", 3,
     needs_scope=True, scope_hint="hostnames, e.g. [\"api.github.com\"]",
     install_phrase="talks to internet")

_cap("net.listen", "Accept connections",
     "Does it open a port or socket others can connect to?", 4,
     needs_scope=True, scope_hint="socket paths or ports",
     install_phrase="accepts connections")

# --- capture ---------------------------------------------------------------
_cap("input.capture", "Read input globally",
     "Can it see keystrokes meant for other windows?", 5,
     install_phrase="reads input globally")

_cap("screen.capture", "Capture the screen",
     "Can it take screenshots or record the display?", 4,
     install_phrase="captures the screen")

_cap("audio.capture", "Capture audio",
     "Can it record the microphone?", 5,
     install_phrase="records audio")

_cap("clipboard.read", "Read the clipboard",
     "Can it see what I copy?", 4,
     install_phrase="reads the clipboard")

_cap("clipboard.write", "Write the clipboard",
     "Can it replace what I paste?", 3,
     install_phrase="writes the clipboard")

# --- integration -----------------------------------------------------------
_cap("ipc.omarchy", "Drive the shell",
     "Does it send commands to other parts of the Omarchy shell?", 2,
     needs_scope=True, scope_hint="IPC targets",
     install_phrase="drives the shell")

_cap("binary.bundled", "Ship compiled code",
     "Does the repo contain binaries I can't read?", 4,
     needs_scope=True, scope_hint="relative paths of binary artifacts",
     install_phrase="ships compiled code")


# Capabilities that, combined, describe an exfiltration path. Any plugin
# holding all three legs of a pair gets escalated regardless of individual
# weights, because the risk is in the composition, not the parts.
EXFIL_PAIRS: list[tuple[tuple[str, ...], str]] = [
    (("fs.sensitive", "net.outbound"), "reads credentials and can send them off-box"),
    (("clipboard.read", "net.outbound"), "reads the clipboard and can send it off-box"),
    (("input.capture", "net.outbound"), "sees keystrokes and can send them off-box"),
    (("screen.capture", "net.outbound"), "captures the screen and can send it off-box"),
    (("audio.capture", "net.outbound"), "records audio and can send it off-box"),
    (("code.dynamic", "net.outbound"), "can download and execute new code"),
]

# The "source" leg of every exfil pair — capabilities that are inherently
# worth a red flag on their own, composition or not. `omaudit add` pulls
# these out of the plain capability list into flagged callouts; net.outbound,
# the shared "sink" leg, stays a plain fact line since it's usually expected
# and declared.
FLAGGED_CAPABILITY_IDS: set[str] = {legs[0] for legs, _why in EXFIL_PAIRS}

GRADES = ["A", "B", "C", "D", "F"]


@dataclass
class Verdict:
    score: int = 0
    grade: str = "A"
    reasons: list[str] = field(default_factory=list)


def grade(observed: set[str], undeclared: set[str], unreadable: bool = False,
          schema_adopted: bool = True) -> Verdict:
    """Score a plugin. Declared capabilities still carry weight (a keylogger that
    admits to being a keylogger is still a keylogger) but undeclared ones are
    weighted double, because the author chose not to say.

    `schema_adopted` should be False when the manifest carries no `permissions`
    block at all. Every capability is then trivially "undeclared" — there is
    nothing to have declared into — so doubling the penalty would punish every
    plugin written before the schema existed rather than authors who opted in
    and then under-declared."""
    v = Verdict()
    for cap_id in observed:
        cap = CAPABILITIES.get(cap_id)
        if not cap:
            continue
        penalize = cap_id in undeclared and schema_adopted
        v.score += cap.weight * (2 if penalize else 1)

    for legs, why in EXFIL_PAIRS:
        if all(leg in observed for leg in legs):
            v.score += 6
            v.reasons.append(f"composition: {why}")

    if unreadable:
        v.score += 6
        v.reasons.append("repository contains code that could not be read as text")

    if undeclared:
        v.reasons.append(
            f"{len(undeclared)} capability(ies) exercised but not declared: "
            + ", ".join(sorted(undeclared))
        )

    v.grade = (
        "A" if v.score == 0 else
        "B" if v.score <= 6 else
        "C" if v.score <= 14 else
        "D" if v.score <= 24 else
        "F"
    )
    return v

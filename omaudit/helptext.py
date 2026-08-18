"""User-facing help: command list and how to use each one.

Kept as data so `omaudit`, `omaudit help`, and `omaudit <cmd> --help`
all render the same words.
"""

OVERVIEW = """\
omaudit - what can this Omarchy plugin reach?

Plugins run unsandboxed inside the long-running shell process, with your
full user permissions. omaudit is a lint: it reports capability, not intent.

Everyday
  omaudit add <git-url>       review a plugin, then install it
  omaudit check               re-audit what you already installed
  omaudit check --all         yours plus the plugins that ship with Omarchy
  omaudit help <command>      how to use one command

Look before you install
  omaudit scan <dir>          human report (no Omarchy CLI needed)
  omaudit permissions <dir>   generate a permissions block from the code

Keep a plugin honest
  omaudit baseline <dir>      accept today's capabilities
  omaudit baseline --builtin  same for every first-party plugin
  omaudit report              report card of every tracked plugin
  omaudit census              snapshot the live omarchyplugins.com listing
  omaudit verify <dir>        CI gate: fail on undeclared capabilities

Also
  omaudit badge <dir>         shields.io JSON
  omaudit schema              the capability vocabulary

Grades: A clean  B ordinary  C review it  D know what you're doing  F don't.
Exit:   0 clean  1 findings  2 invalid manifest  3 usage

Run `omaudit help add` (or any command) for flags and a worked example.
"""

# summary is the one-liner in `omaudit help` and argparse -h listings.
# usage / body are the `omaudit help <command>` page (and the --help epilog).
PAGES: dict[str, dict[str, str]] = {
    "add": {
        "summary": "review a plugin's capabilities, then install it",
        "usage": "omaudit add <git-url> [--yes] [--plugin ID]\n"
                 "omaudit add <dir> --local [--yes] [--plugin ID]",
        "body": """\
The install-time gate. Clones the plugin, prints what it actually does
in plain language, and asks before anything is written.

  omaudit add https://github.com/someone/weather-plus

    weather-plus 2.1.0 - grade D

    runs programs         curl, sh
    talks to internet     api.open-meteo.com
    ! reads credentials and can send them off-box

    Install anyway? [y/N]

Yes installs via `omarchy plugin add <url> --yes` and writes
.omaudit-baseline.json next to it, which is what `omaudit check` compares
against later.

--local     treat the argument as an already-checked-out directory
            (review works; install still needs a git URL)
--plugin ID pick one plugin when the source holds several
--yes / -y  skip omaudit's confirmation (still shows the sheet)

Needs the `omarchy` CLI on PATH to install. Scan-only? use `omaudit scan`.
""",
    },
    "check": {
        "summary": "re-audit installed plugins against their approved baseline",
        "usage": "omaudit check [--all] [--builtin] [--dir DIR] [--json] [--yes]",
        "body": """\
You vetted a plugin once; nobody re-reads QML on update. check re-audits
every installed plugin against the baseline you approved it under.

  omaudit check           user plugins in ~/.config/omarchy/plugins
  omaudit check --builtin first-party plugins shipped with Omarchy
  omaudit check --all     both

Anything that grew a new capability gets a menu:

  [d]iff the source  [p]in to old  [r]emove  [a]ccept  [s]kip

First-party plugins refuse pin/remove/diff - they are not a git checkout.
Their baselines live in ~/.config/omaudit/baselines/, not under /usr/share.

--dir DIR   plugins directory (default: ~/.config/omarchy/plugins)
--json      machine-readable report, no prompts
--yes / -y  print the report without prompting (cron / omarchy update hook)

If a plugin has never been baselined, check says so. Start tracking with
`omaudit baseline <dir>` or `omaudit baseline --builtin`.
""",
    },
    "scan": {
        "summary": "audit a plugin directory and print a human report",
        "usage": "omaudit scan <dir> [--json]",
        "body": """\
Static read of one plugin on disk. No install, no Omarchy CLI, no network.

  omaudit scan /tmp/weather-plus
  omaudit scan . --json

Prints the observed capabilities, whether the author declared them, file
and line evidence, the grade, and a permissions block you can paste.

--json  full document (what CI and the census consume)

This is the manual form of `add`. Use it in CI, or before add existed.
""",
    },
    "verify": {
        "summary": "CI gate: non-zero exit on undeclared capabilities or a worse grade",
        "usage": "omaudit verify <dir> [--max-grade B] [--allow-undeclared]\n"
                 "                    [--baseline FILE] [--json]",
        "body": """\
Same audit as scan, but the exit code is the point.

  omaudit verify . --max-grade B

Fails (exit 1) when capabilities are undeclared or the grade is worse
than --max-grade. Fails (exit 2) on an invalid manifest.

A plugin written before the permissions convention will fail on day one
against its own accumulated capabilities. Snapshot instead:

  omaudit baseline .
  omaudit verify . --baseline .omaudit-baseline.json

CI then catches capability drift, not capability existence.

--max-grade G       worst acceptable grade (default: B)
--allow-undeclared  do not fail on an undeclared capability
--baseline FILE     accept the capabilities in FILE; fail only on new ones
--json              full document on stdout (errors still go to stderr)
""",
    },
    "baseline": {
        "summary": "snapshot current capabilities as accepted",
        "usage": "omaudit baseline <dir> [--out FILE]\n"
                 "omaudit baseline --builtin [--out DIR]",
        "body": """\
Write down what this plugin can do today, so the next check or verify
only fails on what is added after this point.

  omaudit baseline ~/.config/omarchy/plugins/eddieor.control-center
  omaudit baseline --builtin

A directory of plugins (no manifest.json at the root) snapshots every
plugin inside it. --builtin is that, pointed at Omarchy's first-party
tree.

User plugins write .omaudit-baseline.json next to the plugin.
First-party plugins write ~/.config/omaudit/baselines/<id>.json - the
package tree under /usr/share is not writable and would vanish on update.

--out FILE   write this path instead (a directory, when snapshotting many)
--builtin    every first-party plugin shipped with Omarchy
""",
    },
    "census": {
        "summary": "snapshot the live omarchyplugins.com marketplace listing",
        "usage": "omaudit census [--fetch-only] [--render] [--limit N]\n"
                 "               [--out DIR] [--keep-clones DIR] [--local DIR]",
        "body": """\
The website is growing. This command pulls HANCORE's live registry
(the same JSON behind omarchyplugins.com), pins each source to the
commit the marketplace validated, and audits that tree.

  omaudit census --fetch-only   refresh the list; say what is new
  omaudit census --limit 5      smoke-test five sources
  omaudit census                fetch + clone + audit (uses a clone cache)
  omaudit census --render       re-summarize the last corpus

This is a dated snapshot you run on purpose. It is not a timer, and it
is not mixed into `omaudit report` — report is what you installed,
census is what the site is listing.

Clones persist in ~/.cache/omaudit/clones so a re-run only fetches
sources whose listingValidatedCommit changed. Output lands in
~/.config/omaudit/census/.

Aggregates only. Naming a plugin from this output follows DISCLOSURE.md.
Do not put this on a daily cron: five hundred clones a day is rude.
""",
    },
    "report": {
        "summary": "print a report card of every plugin already on this machine",
        "usage": "omaudit report [--all] [--builtin] [--dir DIR] [--out FILE] [--json]",
        "body": """\
Re-scans every plugin you have already installed or baselined and writes
a dated report card: grade, capabilities, drift, composition. This is
what you keep so you can verify later without walking QML again.

  omaudit report              yours plus first-party (the default)
  omaudit report --builtin    first-party only
  omaudit report --dir DIR    one tree
  omaudit report --json       machine-readable
  omaudit report --out FILE   write here instead of the default

The card is printed and saved to ~/.config/omaudit/report-card.txt.
Exit 1 if anything drifted since its baseline; 0 if everything matches.

`check` is the interactive menu. `report` is the sheet you file.
""",
    },
    "permissions": {
        "summary": "generate a manifest permissions block from the code",
        "usage": "omaudit permissions <dir>",
        "body": """\
Print a permissions object the author can paste into manifest.json.

  omaudit permissions .

Replace the TODO reasons, commit, done. Then `omaudit verify .` holds
you to what you declared.

Adopting the block is how an honest plugin goes from "undeclared" to
"declared" without changing any QML.
""",
    },
    "badge": {
        "summary": "emit shields.io endpoint JSON for the grade",
        "usage": "omaudit badge <dir>",
        "body": """\
  omaudit badge . > omaudit-badge.json

{"schemaVersion": 1, "label": "omaudit", "message": "B · 2 caps", "color": "green"}

Point a shields.io endpoint badge at that file. A drop-in GitHub Action
that runs verify and publishes this lives in .github/workflows/omaudit.yml.
""",
    },
    "schema": {
        "summary": "print the capability vocabulary as JSON",
        "usage": "omaudit schema",
        "body": """\
Sixteen capabilities, each a question a reviewer would actually ask.
Machine-readable: id, title, question, weight, whether a scope is needed.

See also: omaudit help grades
""",
    },
    "help": {
        "summary": "show commands and how to use them",
        "usage": "omaudit help [command]",
        "body": """\
  omaudit              the command list
  omaudit help         the same list
  omaudit help add     flags and a worked example for one command
  omaudit help grades  how A-F is scored
""",
    },
    "grades": {
        "summary": "how a plugin is scored A through F",
        "usage": "omaudit help grades",
        "body": """\
Every observed capability has a weight (0-5). Declared capabilities still
count - a keylogger that admits to being a keylogger is still a keylogger.
Undeclared ones count double, but only if the manifest has a permissions
block at all. Plugins written before the schema are not punished for
having nothing to declare into.

Composition pairs add +6 regardless of justification. The ones that
matter: credentials, clipboard, keystrokes, screen, or audio, plus a
network path off-box; or dynamic code plus a network path.

  0      A  clean - this plugin only draws
  1-6    B  ordinary
  7-14   C  review it
  15-24  D  know what you're doing
  25+    F  don't

A grade is not a verdict on an author. Most low grades are honest
plugins that predate the declaration convention.
""",
    },
}


def overview() -> str:
    return OVERVIEW.rstrip() + "\n"


def page(topic: str | None) -> str | None:
    if topic is None or topic in ("commands", "topics"):
        return overview()
    entry = PAGES.get(topic)
    if not entry:
        return None
    parts = [
        f"omaudit {topic} - {entry['summary']}",
        "",
        "Usage",
        *(f"  {line}" for line in entry["usage"].splitlines()),
        "",
        entry["body"].rstrip(),
        "",
    ]
    return "\n".join(parts)


def topics() -> list[str]:
    return sorted(PAGES)

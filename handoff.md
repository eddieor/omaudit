# omaudit — session handoff

**Written:** 18 Aug 2026 · **Repo:** `D:\github\omaudit` · **Status:** working tool, census run once, rules need tuning before anything is published

---

## 1. What this project is

`omaudit` is a static capability auditor for Omarchy Quattro shell plugins.

Omarchy 4 ("Quattro", released 14 Aug 2026 by DHH / 37signals) rewrote the entire
desktop shell in Quickshell. The bar, launcher, menus, notifications, panels,
lock screen and polkit agent are now plugins inside **one long-running process**,
and third-party plugins install from arbitrary git URLs via
`omarchy plugin add <git-url>`.

The official plugin development guide states the risk directly:

> Plugins share the long-running Omarchy shell process. They run unsandboxed
> with your user permissions.

So arbitrary QML, from arbitrary git URLs, runs in the process that owns the bar
and the lock screen, on a machine that also holds SSH keys, a password manager,
and a coding agent with live API credentials.

**omaudit's thesis:** you cannot answer "is this plugin safe?", but you *can*
answer "does this plugin reach things its author didn't disclose?" — mechanically,
by diffing a declared capability set (from `manifest.json`) against an observed
one (from static analysis of the QML).

Two deliverables:
1. **`SPEC.md`** — a proposal to add an optional `permissions` block to Omarchy's
   `manifest.json`. Additive, no sandbox, no runtime enforcement, no new shell
   dependency. Intended as an upstream PR to `basecamp/omarchy`.
2. **`omaudit`** — the reference implementation that makes the schema checkable.

---

## 2. Current state

### Works and is verified

All six subcommands run clean on Windows (Python 3.11) and Linux:

| Command | Purpose | Verified |
|---|---|---|
| `omaudit scan <dir>` | human report, `--json` for full doc | ✅ |
| `omaudit verify <dir>` | CI gate, non-zero exit | ✅ |
| `omaudit verify <dir> --baseline F` | fail only on *new* capabilities | ✅ |
| `omaudit baseline <dir>` | snapshot accepted capabilities | ✅ |
| `omaudit permissions <dir>` | generate a permissions block | ✅ |
| `omaudit badge <dir>` | shields.io endpoint JSON | ✅ |
| `omaudit schema` | capability vocabulary as JSON | ✅ |

Exit codes: `0` clean · `1` findings · `2` invalid manifest · `3` usage.

`pytest tests -q` → 3 passed. Zero runtime dependencies, Python 3.11+.

Fixtures: `tests/fixtures/good-clock` (grade A, no capabilities — this is the
worked example from the official docs) and `tests/fixtures/sketchy-weather`
(grade F, score 67, both composition rules firing).

### Repo layout

```
omaudit/
├── README.md              usage, adoption path, census instructions
├── SPEC.md                the upstream proposal — read before touching capabilities.py
├── DISCLOSURE.md          responsible disclosure policy (written BEFORE findings, deliberately)
├── LICENSE                MIT
├── PKGBUILD               AUR package (has YOURNAME placeholders — fix before publishing)
├── pyproject.toml         PyPI package (no repository URL yet)
├── .gitignore
├── census.py              ecosystem-wide audit runner
├── fetch_registry.py      pulls the live marketplace registry
├── .github/workflows/omaudit.yml   drop-in CI gate for plugin repos
├── omaudit/
│   ├── capabilities.py    16-capability taxonomy, composition pairs, grading
│   ├── rules.py           regex detectors → capabilities  ← THE FILE THAT NEEDS WORK
│   ├── scan.py            file walk, comment stripping, reclassification, dedupe
│   ├── manifest.py        structural validation + permissions block handling
│   ├── report.py          human / JSON / badge rendering
│   └── cli.py             argparse + subcommands
└── tests/
    ├── test_fixtures.py
    └── fixtures/{good-clock,sketchy-weather}/
```

### How the pipeline works

```
manifest.json ──> declared set ─┐
                                ├──> diff ──> composition rules ──> grade ──> scan/verify/badge
*.qml, *.js ────> observed set ─┘
```

- `manifest.py` re-implements Omarchy's own structural checks (required fields,
  kind↔entryPoint agreement, no `omarchy.*` IDs, no symlinks, safe relative
  paths) so omaudit runs in CI with no Omarchy installed. It also reads the
  proposed `permissions` block.
- `scan.py` walks the tree, blanks comments (preserving line numbers), applies
  every rule per line, then does two things the rules can't: **reclassifies**
  `fs.read`/`fs.write` to `fs.sensitive` when the path matches the credential
  list (and drops paths that don't leave the plugin folder), and **dedupes** on
  `(rule, capability, file, line, scope)`.
- `capabilities.py` scores it. Each capability has a weight; **undeclared ones
  count double**. Composition pairs (e.g. `fs.sensitive` + `net.outbound`) add a
  flat +6 regardless of justification. Grades: 0=A, ≤6=B, ≤14=C, ≤24=D, else F.

---

## 3. Verified external facts

These were confirmed by direct fetch on 18 Aug 2026. Don't re-derive from memory.

### Omarchy plugin system

- Plugin kinds and entry points:
  `bar-widget`→`barWidget`/`BarWidget.qml`, `panel`→`panel`/`Panel.qml`,
  `overlay`→`overlay`/`Overlay.qml`, `menu`→`menu`/`Menu.qml`,
  `service`→`service`/`Service.qml`, `bar`→`bar`/`Bar.qml`
- CLI: `omarchy plugin add|clone|validate|list --json|remove`,
  `omarchy bar put|move`, `omarchy-shell shell rescanPlugins|summon|hide`
- Lint: `qmllint -I "$OMARCHY_PATH/shell" <files>`
- Plugins live in `~/.config/omarchy/plugins/<id>/`
- Third-party IDs cannot use the `omarchy.*` namespace; plugin folders cannot
  contain symlinks
- Official shell reference: `basecamp/omarchy/blob/quattro/shell/README.md`
- Built-in examples: `basecamp/omarchy/tree/quattro/shell/plugins`

### The community marketplace — IMPORTANT

`omarchyplugins.com`, built by **HANCORE** (`HANCORE-linux`), independent, MIT,
not affiliated with 37signals. Launched ~late July 2026. Submissions via a
GitHub issue template (`submit-plugin.yml`).

**HANCORE has already built a security baseline. Do not claim nobody has.**

Live registry: `https://raw.githubusercontent.com/HANCORE-linux/omarchy-plugin-marketplace/main/registry.json`

Top-level keys: `retiredPluginIds` (5), `sources` (414), `builtInSources` (1),
`placeholders` (0).

Each source entry:
```json
{
  "repo": "https://github.com/...",
  "type": "plugin-source",              // 412 plugin-source, 2 suite
  "addedAt": "2026-07-28",
  "listingValidatedCommit": "37f5bfb...",   // present on ALL 414
  "listingValidatedBranch": "master",
  "plugins": { "<plugin-id>": { "category": ..., "tags": [...] } },
  "automatedSecurityBaseline": { ... },      // on 331 of 414
  "maintainerVerificationReview": { ... }    // on 9
}
```

`automatedSecurityBaseline` (schemaVersion 1, version "3"):
```json
{ "outcome": "passed", "enforcementMode": "selective",
  "findings": [], "capabilities": [], "commit": "...", "checkedAt": "..." }
```

Upstream outcomes: **passed 208, review-required 122, needs-fixes 1.**
Enforcement modes: selective 321, review-only 10.

**Upstream capability vocabulary — all seven terms:**

```
  52  installer                 44  service-management
  49  privilege                 41  remote-build
  48  package-manager            1  bundled-executable-binary
                                 1  sudoers-modification
```

Total findings across the entire 414-source registry: **2**
(`remote-git-execution-unpinned`, `cargo-git-unpinned`). 123 of 331 baselines
list any capability at all.

### Why omaudit still has a reason to exist

Every one of HANCORE's seven terms describes the **install path** — what the
install script does, what it sudoes, what it pulls, what services it registers.

**None describe runtime behavior inside the shell process.** No network egress,
no filesystem reads, no credential paths, no clipboard, no input capture, no
screen capture, no dynamic code evaluation. Of omaudit's 16 capabilities, 3
overlap (`process.exec`≈privilege, `process.privileged`, `binary.bundled`) and
13 do not.

HANCORE says so himself, in a callout on `omarchyplugins.com/publish.html`:

> The marketplace validates listings, not plugin security. Plugins run
> unsandboxed.

And his `manifest.json` field reference has **no `permissions` field** — the
concept has vocabulary demand (his site tells users to "review the plugin's
requested capabilities") with no schema behind it.

**Positioning: complement, not compete.** "Your baseline covers the install path,
here's the runtime half, they compose." His `capabilities` field is a flat string
array and `findings` an array of objects — omaudit can emit into that shape, so
integration is a data feed into fields that already exist.

---

## 4. THE CENSUS RESULT — and why it must not be published yet

Ran `fetch_registry.py` + `census.py` over all 414 sources at their pinned
`listingValidatedCommit`. Output is in `census/` (`corpus.json` ~2.9 MB,
`summary.json`, `registry-entries.json`, `upstream-baseline.json`).

```
audited 481 | declaring 0
grades: A 15 · B 42 · C 60 · D 117 · F 247
composition risks: 138

process.exec        415      shell.mutate         71
fs.sensitive        293      clipboard.write      44
ipc.omarchy         277      process.privileged   42
fs.read             217      binary.bundled       36
fs.write            210      code.dynamic         20
net.outbound        196      clipboard.read       13
                             screen.capture        8
                             net.listen            6
                             input.capture         5
```

**51% grade F is a bug report about the rules, not a finding about the
ecosystem.** Do not publish, post, tweet, or share these numbers. Diagnosis:

1. **`fs.sensitive` (293, weight 5) is mostly false.** `SENSITIVE_PATHS` in
   `rules.py` contains `\.env\b`, which matches `Quickshell.env("HOME")` and
   `process.env` — ordinary environment access, routine in a QML shell.
2. **`net.outbound` (196) is inflated by metadata.** `scan.py` scans `.json`
   files, so `manifest.json`'s repository/homepage URLs trip the `net.url` rule.
   Metadata is not behavior.
3. **`fs.write` (210) is inflated by `setText`.** The `fs.write` rule pattern
   includes `setText` and a bare `.write(` — `setText` is a generic QML property
   setter used all over UI code.
4. **`composition risks: 138` is therefore worthless** — it's almost entirely
   `fs.sensitive` × `net.outbound`, and both legs are inflated.
5. **The doubling rule is unfair pre-adoption.** `declaring: 0 of 481` because
   *there is no field to declare in*. Every observed capability is therefore
   "undeclared" and weighted ×2, which pushes even honest plugins to D/F. With
   `process.exec` alone at 86% of plugins, ×2 = +6 baseline for nearly everyone.

### What IS real and defensible

- **`declaring: 0 of 481`.** Does not depend on any single rule being correct.
  This is the entire argument for the SPEC PR and it is clean.
- **The rare capabilities.** `input.capture` 5, `net.listen` 6,
  `screen.capture` 8, `code.dynamic` 20. Least likely to over-fire, most
  interesting if real, and small enough to verify by hand.

**The better story is not "half the ecosystem is dangerous" (nobody believes it)
but "here are the ~19 plugins doing something unusual, here's what each one is,
and here's why you currently have no way to know before installing."**

---

## 5. Immediate work queue

### A. Hand-verify the rare capabilities (do this first, before code)

Pull the plugin IDs for `input.capture`, `net.listen`, `screen.capture`, and
`code.dynamic` out of `census/corpus.json` and read the actual source of each.
~19 plugins. Outcome either way is useful: real findings become the launch story,
false positives become rule fixes. If `input.capture` turns out to be five
legitimate hotkey widgets, that's worth knowing too.

### B. Five rule fixes in `rules.py` / `capabilities.py` / `scan.py`

1. Remove `\.env\b` from `SENSITIVE_PATHS` (`rules.py`). Consider replacing with
   patterns for actual dotenv *files* (`/.env`, `.env.local`) rather than the
   bare token.
2. Restrict behavioral rules to `.qml`/`.js`/`.sh`/`.py` — exclude `.json`,
   `.jsonc`, `.toml` from `net.url` and friends in `scan.py`. Metadata files
   should feed manifest validation only.
3. Drop `setText` and bare `.write(` from the `fs.write` rule; keep
   `writeAdapter` and `Qt.labs.settings`, add file-specific write signals.
4. Tighten `fs.path-prop` further — currently only requires `~`, `/`, `$`
   prefix; should also exclude image/asset extensions and `qrc:`/`Qt.resolvedUrl`.
5. **Make the ×2 undeclared multiplier conditional** on the manifest having a
   `permissions` block at all. If an author opted into the schema, hold them to
   it; if the schema doesn't exist upstream yet, don't punish them for it. Add a
   `--pre-adoption` mode or make it automatic in `capabilities.grade()`.

### C. Build real fixtures

The rules were tuned against two fixtures I wrote by hand, i.e. tuned to my
imagination rather than real QML. Pull 5–10 real plugins from the corpus into
`tests/fixtures/` (vendored, with attribution and licenses) covering the common
shapes: a Process-using bar widget, a FileView config reader, a network fetcher,
a service plugin.

### D. Add `--keep-clones` to `census.py`

Re-running costs ~30 min of cloning on Windows. A `--keep-clones` flag pointing
at a persistent cache dir makes each tuning iteration instant. This is the
highest-leverage small feature right now.

### E. Known bugs

- `census.py --render-only` still requires a dummy positional arg (argparse
  wart). Make `source` optional when `--render-only` is set.
- Windows: `shutil.rmtree` can't delete `.git/objects` (read-only), so temp
  clones leak into `%TEMP%\omaudit-census-*`. Add an `onerror` handler that
  chmods and retries.
- `PKGBUILD` has `YOURNAME` and a placeholder maintainer email.
- `pyproject.toml` has no repository URL.
- README install instructions reference a PyPI package that doesn't exist yet.
- `report.py` `human()` can raise `BrokenPipeError` when piped to `head`.
- FIXED but note the class of bug: `census.py` used `█` in the histogram and
  wrote without an explicit encoding, which crashed on Windows cp1252. **Every
  file write needs `encoding="utf-8"` and output should stay ASCII-safe.**

---

## 6. Strategy — read before doing any outreach

### Sequencing

The census runs **before** the announcement, and the census is what gets
announced. "I built a tool" is a request for attention; "here is what is running
inside your bar process" is information people want.

1. **Talk to HANCORE first.** He moved from week-3 audience to week-1
   collaborator the moment we found his baseline. Lead with the complement
   framing and the fact that his own vocabulary covers install and not runtime.
   Offer the badge feed free, as a PR to his repo.
2. **Fix the rules, re-run, hand-verify.** No numbers leave the machine until the
   F count is believable (expect 20–40, not 247).
3. **Private notifications before publication.** Every plugin with a real finding
   gets a private issue with file and line, plus an offer to open the PR that
   adds their `permissions` block. This is the step everyone skips and it decides
   whether you're a contributor or a vulture.
4. **Publish the census, not the tool.** Aggregates only, no plugin named without
   permission, per `DISCLOSURE.md` — which was written before any findings
   existed, deliberately, and that's what makes it read as good faith.
5. **Then the SPEC PR to `basecamp/omarchy`,** now backed by measured evidence.
   DHH responds to working code and concrete numbers; he rejects abstraction and
   ceremony. Keep the PR readable in 90 seconds.

### Channels, in order

Omarchy Discord (`discord.gg/tXFUdasqhY`) → HANCORE's marketplace repo →
`basecamp/omarchy` Discussions → Hacker News (title it as the census, not the
tool) → X (a reply on the Quattro thread beats a standalone post).

### Install paths

AUR is the front door (`yay -S omaudit`) — Omarchy is Arch, and telling that
audience to `pipx install` marks you as an outsider. PyPI is the CI door.
Git clone is the audit door: security tooling that can't be read before it's run
is a contradiction.

### Two failure modes to actively avoid

**Being the security scold.** This community is built on opinionated simplicity
and low ceremony. Anyone implying the ecosystem is dangerous gets tuned out.
Frame everything as "raising the floor for authors," and ship every finding with
the fix already written.

**Monetizing too early.** Individual use stays free and visibly so. The fleet /
org product doesn't get mentioned for months. The moment the scanner looks like a
funnel, the badge stops meaning anything.

### Do NOT build yet

Signing infrastructure, `omarchy-pack` with lockfiles, a hosted badge service,
any web UI, the fleet product. All downstream of a question the corpus hasn't
answered yet. If the corrected census shows the runtime gap is small, the
interesting product is compatibility CI and auto-generated preview images
instead — and that's a cheap thing to learn before building the wrong layer.

---

## 7. Environment notes

- Windows, PowerShell, Python 3.11 at
  `C:\Users\eddie\AppData\Local\Programs\Python\Python311`
- Use `python`, not `python3`
- `git` must be on PATH for `census.py`
- Census took ~30–40 min on Windows (Defender scanning each cloned file)
- ~2% real clone failure rate across 414 repos (`census/errors.log` also contains
  the cp1252 traceback, so its line count overstates failures)
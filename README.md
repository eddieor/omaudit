# omaudit

Capability audit for [Omarchy Quattro](https://omarchy.org) shell plugins.

<video src="https://github.com/eddieor/omaudit/raw/master/videos/omauditVideo.mp4" controls width="100%"></video>

Omarchy plugins run **unsandboxed inside the long-running shell process**, with
your full user permissions, installed from arbitrary git URLs. `omaudit` tells
you what a plugin can reach before you let it into that process — and tells plugin
authors what they're about to ask for.

It is a lint, not a proof. It reports capability, not intent.

## Install

With pip, so `omaudit` is on your PATH:

```sh
git clone <this-repo>
cd omaudit
pip install -e .
```

(`pipx install omaudit` once it's published to PyPI — not yet.)

Without pip — clone the repo and run the package directly. Python 3.11+,
no dependencies:

```sh
git clone <this-repo>
cd omaudit
python3 -m omaudit              # command list
python3 -m omaudit scan ./path/to/plugin
python3 -m omaudit help add
```

`scan`/`verify`/`baseline`/`badge`/`permissions`/`schema` need no Omarchy —
they run in CI on a bare Linux box. `add` and `check` do need the `omarchy`
CLI on PATH, since they hand off to `omarchy plugin add`/`remove`.

The `tests/` directory is for development only. You do not need it to run
the tool.

## Use

```sh
omaudit              # command list
omaudit help add     # flags and a worked example
```

**The install-time gate:**

```sh
omaudit add https://github.com/someone/weather-plus
```

Clones the plugin, shows what it actually does in plain language, and asks
before installing anything:

```
  weather-plus 2.1.0 - grade D

  runs programs         curl, sh
  reads files           ~/.config/omarchy/shell.toml
  talks to internet     api.open-meteo.com, metrics.weather-plus.dev
  ships compiled code   helper

  ! reads credentials and can send them off-box
    BarWidget.qml:24  references a path that normally holds credentials

  the author declared: talks to internet
  everything else is undeclared

Install anyway? [y/N]
```

Say yes and it installs via `omarchy plugin add` and writes
`.omaudit-baseline.json` next to it — which is what makes the next command
possible.

**Living with what's already installed:**

```sh
omaudit check
```

Re-audits every installed plugin against the baseline you approved it
under. You vetted it once; nobody re-reads QML on update. Anything that
grew new capabilities since then gets a menu: `[d]iff the source`,
`[p]in` back to the approved commit, `[r]emove`, or `[a]ccept` the change.
Run it with `--yes --json` from a timer or an `omarchy update` hook for a
headless report instead of a prompt.

**Before installing something from a stranger, the manual way** (no
`omarchy` CLI required — useful in CI, or before `add` existed):

```sh
git clone https://github.com/someone/weather-plus /tmp/wp
omaudit scan /tmp/wp
```

```
io.github.someone.weather-plus  2.1.0
2 files scanned - grade F (score 67)

capabilities
  x fs.sensitive         Touch credentials        UNDECLARED  -> .ssh, id_ed25519
      BarWidget.qml:24  references a path that normally holds credentials
  + net.outbound         Talk to the internet     declared  -> api.open-meteo.com
      BarWidget.qml:13  contacts a remote host
  x process.exec         Run programs             UNDECLARED  -> curl, sh

why this grade
  - composition: reads credentials and can send them off-box
  - 6 capability(ies) exercised but not declared
```

**As a plugin author, adopting the declaration:**

```sh
omaudit permissions .   # generates the block from your existing code
```

Paste it into `manifest.json`, replace the `TODO` reasons, done. Then gate your
own repo:

```sh
omaudit verify . --max-grade B    # non-zero exit on undeclared capabilities
```

A ready-to-copy GitHub Action lives in `.github/workflows/omaudit.yml`.

## Commands

| Command | Does |
|---|---|
| `omaudit help [command]` | Command list, or how to use one command |
| `omaudit add <source>` | Review a plugin's capabilities, then install it via `omarchy plugin add` |
| `omaudit check` | Re-audit installed plugins against their approved baseline |
| `omaudit check --builtin` | Same, for first-party plugins shipped with Omarchy |
| `omaudit check --all` | User-installed and first-party together |
| `omaudit report` | Report card of every tracked plugin (saved under `~/.config/omaudit/`) |
| `omaudit census` | Snapshot the live omarchyplugins.com listing (not on a timer) |
| `omaudit scan <dir>` | Human report; `--json` for the full document |
| `omaudit verify <dir>` | CI gate; fails on undeclared capabilities or grade drop |
| `omaudit permissions <dir>` | Generate a `permissions` block from the code |
| `omaudit badge <dir>` | shields.io endpoint JSON |
| `omaudit schema` | The capability vocabulary, machine-readable |
| `omaudit baseline <dir>` | Snapshot current capabilities as accepted |
| `omaudit baseline --builtin` | Snapshot every first-party plugin (stored in `~/.config/omaudit/baselines/`) |

Exit codes: `0` clean · `1` findings · `2` invalid manifest · `3` usage.

### Adopting this on a plugin that already exists

A plugin written before the declaration convention will fail the gate on day one
against its own accumulated capabilities, and the author will just delete the
Action. Snapshot instead:

```sh
omaudit baseline .                                  # accept what's there today
omaudit verify . --baseline .omaudit-baseline.json  # fail only on what's added next
```

Commit the baseline file. CI now catches capability *drift* rather than
capability *existence*, which is the thing that actually matters on update.

## Auditing the whole ecosystem

```sh
omaudit census --fetch-only    # refresh the live listing, say what is new
omaudit census                 # then clone + audit; clones stay cached
```

(`python3 fetch_registry.py` / `python3 census.py` still work; they call the same code.)

`fetch_registry.py` reads the community marketplace registry and writes a source
list pinned to each entry's `listingValidatedCommit` — the exact commit the
marketplace validated at listing time — so a census is reproducible and can't be
gamed by pushing after listing. It also extracts the marketplace's own
`automatedSecurityBaseline`, whose vocabulary covers the *install path*
(installer, privilege, package-manager, service-management, remote-build).
omaudit covers the *runtime* side, so the two compose rather than compete.

`census.py` fetches each pinned commit, audits it, and writes `corpus.json`,
`summary.json`, and a `summary.txt` grade histogram. Nothing is executed — it is
a static read.

## How grading works

Every capability carries a weight. Undeclared ones count double — a keylogger that
admits to being a keylogger is still a keylogger, but choosing not to say is its
own signal.

The real weight is on **composition**. `fs.sensitive` alone is a plugin reading a
config file. `net.outbound` alone is a weather widget. Together they're an
exfiltration path, and no bar widget needs both. Those pairs escalate regardless
of how each leg is justified.

`A` clean · `B` ordinary · `C` review it · `D` know what you're doing · `F` don't.

## What it does not do

- **It cannot detect a determined attacker.** String-built commands, indirection
  through a helper, and anything downloaded at runtime will slip past a static
  pass. It raises the floor; it is not a security boundary.
- **It does not sandbox anything.** Quickshell plugins share a process by design.
- **It will produce false positives.** A plugin that legitimately execs `nmcli` is
  flagged as running programs, because it does. Declaring it is the fix, and the
  point.

## The schema

`omaudit` implements the capability vocabulary proposed in [`SPEC.md`](./SPEC.md)
for upstream `manifest.json`. The proposal is one optional object, additive,
with no runtime enforcement — the value is in the diff between what an author
declares and what the code reaches.

## License

MIT.

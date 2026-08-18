# Proposal: capability declarations in `manifest.json`

**Status:** draft · **Target:** `basecamp/omarchy` (quattro) · **Schema:** `manifest.json` v1, additive

## The problem

The plugin docs state the situation plainly:

> Plugins share the long-running Omarchy shell process. They run unsandboxed with
> your user permissions.

`omarchy plugin add <git-url>` clones arbitrary QML into the process that owns the
bar, the lock screen, and the polkit agent, on a machine that also holds SSH keys,
a password manager, and a coding agent with live API credentials. Quattro already
had to close three code-execution paths a malicious theme could take through
install — the same class of problem, one layer down.

Today a user deciding whether to install a plugin has exactly two options: read
every QML file themselves, or trust a stranger's README. Neither scales past the
first dozen plugins, and the ecosystem is four days old.

## What this proposes

One optional object in `manifest.json`. Nothing else.

```json
{
  "schemaVersion": 1,
  "id": "io.github.someone.weather-plus",
  "kinds": ["bar-widget"],
  "entryPoints": { "barWidget": "BarWidget.qml" },

  "permissions": {
    "net.outbound": {
      "reason": "Fetches the hourly forecast.",
      "scope": ["api.open-meteo.com"]
    },
    "process.exec": {
      "reason": "Reads the configured location from the Omarchy weather settings.",
      "scope": ["omarchy"]
    }
  }
}
```

That is the whole change. A plugin that only draws declares nothing and is
unaffected.

### Explicit non-goals

- **No sandbox.** Quickshell plugins share a process by design. Confining them is
  a different, much larger project and this proposal does not pretend otherwise.
- **No runtime enforcement in v1.** Nothing is blocked, hooked, or intercepted.
  There is no policy engine and no measurable runtime cost.
- **No new dependency in the shell.** Rendering a declaration is string display.
- **No mandatory field.** Existing plugins stay valid.

The declaration is a **statement of intent by the author**, and its value comes
from being checkable against the code — not from being enforced.

## Why a declaration is worth anything if nothing enforces it

Because it converts an unanswerable question into a mechanical one.

"Is this plugin safe?" cannot be answered. "Does this plugin do things its author
didn't disclose?" can be — a static scan of the QML produces an observed
capability set, and the diff against the declared set is the signal. An honest
author's diff is empty. A plugin that declares `net.outbound` for weather and also
reads `~/.ssh/id_ed25519` produces a diff that a reviewer, a CI job, or a
marketplace can act on without anyone reading a line of QML.

This is the npm `engines` / Android manifest pattern: the declaration is cheap,
the diff is the product.

## The vocabulary

Sixteen capabilities, each phrased as a question a reviewer would actually ask.
Scoped capabilities carry a `scope` array; the rest are boolean.

| Capability | Question it answers | Scope |
|---|---|---|
| `process.exec` | Does it start other programs? | binaries |
| `process.privileged` | Does it run anything as root? | commands |
| `code.dynamic` | Does it run code that isn't in the repo? | — |
| `fs.read` | Which files outside its folder does it read? | path globs |
| `fs.write` | Which files does it modify? | path globs |
| `fs.sensitive` | Does it go near keys, tokens, or browser profiles? | path globs |
| `shell.mutate` | Does it rewrite my Omarchy configuration? | config files |
| `net.outbound` | Which hosts does it contact? | hostnames |
| `net.listen` | Does it accept connections? | ports/sockets |
| `input.capture` | Can it see keystrokes meant for other windows? | — |
| `screen.capture` | Can it screenshot or record the display? | — |
| `audio.capture` | Can it record the microphone? | — |
| `clipboard.read` | Can it see what I copy? | — |
| `clipboard.write` | Can it replace what I paste? | — |
| `ipc.omarchy` | Does it drive other parts of the shell? | IPC targets |
| `binary.bundled` | Does the repo contain code I can't read? | paths |

Individually these are mostly benign — half the built-in widgets exec something.
The signal is in **composition**: `fs.sensitive` plus `net.outbound` is an
exfiltration path regardless of how each leg is justified, and no legitimate bar
widget needs both.

## Suggested integration points

Ordered by cost. Each stands alone; the first two are the ones that matter.

1. **`omarchy plugin validate`** — validate the block's shape when present.
   Reject unknown capability keys and malformed scopes. Roughly the same amount
   of code as the existing entry-point checks.

2. **`Setup > Plugins`, before install** — render the declaration on the confirm
   step, one line per capability, author's `reason` beside it. A plugin with no
   block shows "this plugin has not declared what it can reach," which is itself
   informative and creates the incentive to declare.

3. **`omarchy plugin list --json`** — include `permissions` in the output, so
   external tooling can audit an installed set without re-reading manifests.

4. **On update** — when a plugin's declaration grows between versions, say so
   before applying. "Weather Plus now also reads files" is the single highest-value
   moment in the whole design, and it costs one set comparison.

Runtime enforcement, if it is ever wanted, layers on later without a schema
change: the declared scope is already the allowlist.

## Reference implementation

`omaudit` ships alongside this proposal:

- `omaudit scan <dir>` — observed capability set with file/line evidence
- `omaudit verify <dir>` — CI gate, non-zero exit on undeclared capabilities
- `omaudit permissions <dir>` — generates the block from existing code, so
  adopting this is a paste, not an audit
- `omaudit schema` — the vocabulary as machine-readable JSON

It runs without Omarchy installed, so it works in plugin CI. It is a lint, not a
proof: it reports what a plugin *can reach*, and deliberately makes no claim about
intent.

## Open questions

- **Scope syntax for paths.** Globs are proposed. `~` expansion and `$HOME` need
  a stated normalization rule.
- **Transitive capability.** A plugin that execs `omarchy` inherits a lot. Worth
  deciding whether `process.exec` scoped to first-party binaries is treated as a
  distinct, lower-weight thing.
- **Should `omarchy.*` built-ins declare too?** Arguably yes, as the worked
  examples every third-party author copies from.
- **Where the reason text lives** if it needs translating.

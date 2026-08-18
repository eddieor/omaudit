First, a correction that matters: **omaudit isn't a plugin.** Omarchy plugins are QML widgets that load into the shell process — making an auditor one would mean the thing checking for unsandboxed code would itself be unsandboxed code inside the process it's auditing. It's a CLI tool that runs outside the shell, plus a schema. There's a case for a small companion bar widget much later, but that's a notification surface, not the product.

Here's the lifecycle it wraps:Only the third track exists today. Tracks one and two are what you build next.

## Track 1 — installing

```console
$ omaudit add https://github.com/someone/weather-plus

fetching someone/weather-plus @ 8f3a1c2

  weather-plus 2.1.0 · grade D

  runs programs         curl, sh
  reads files           ~/.config/omarchy/shell.toml
  talks to internet     api.open-meteo.com, metrics.weather-plus.dev
  ships compiled code   helper

  ! reads credentials and can send them off-box
    BarWidget.qml:24  ~/.ssh/id_ed25519 piped to curl

  the author declared: talks to internet
  everything else is undeclared

Install anyway? [y/N] n
aborted — nothing was written
```

That's the entire product in one screen. Someone who's never heard of a capability schema still understands the fourth line. On `y`, it shells out to `omarchy plugin add` and writes `.omaudit-baseline.json` alongside the install — which is what makes track 2 possible.

## Track 2 — living with it

```console
$ omaudit check

12 plugins installed · 11 unchanged

  weather-plus 2.1.0 → 2.4.0
    + reads the clipboard     BarWidget.qml:61
    + captures the screen     Panel.qml:14

  These are new since you approved this plugin in September.

  [d]iff the source  [p]in to 2.1.0  [r]emove  [a]ccept
```

This is the function that gives the project a reason to exist after launch week. You vetted it once; nobody re-reads QML on update. It's one set comparison against a file you already have, and `--baseline` already does the comparison — `check` just runs it across everything installed and remembers what you approved.

`omaudit watch` is the same thing on a timer or hooked into `omarchy update`.

## Track 3 — authoring (built, works now)

```console
$ omaudit permissions .        # generates the block from your code
$ omaudit baseline .           # accept what exists today
$ omaudit verify . --baseline .omaudit-baseline.json
```

Then the GitHub Action gates every PR, and `omaudit badge` emits the shields JSON.

## Where the website fits

Nowhere in those three tracks — and that's the point. The permalink page exists so the badge has somewhere to link and so someone googling a plugin name lands on the capability sheet before installing. It's reference material generated statically from `corpus.json`. The census report is a dated document. Neither is a place people return to.

The thing people return to is `omaudit check`.

## Build order

`add` first — it's the gate, and it's mostly wiring commands you already have. Then `check`, which is `--baseline` plus a loop over the plugins directory. Then the static site generator from the corpus. Then, much later, the bar widget that surfaces `check` results without you having to run it.

Right now none of that is the priority. The rules still over-fire, and `add` is only as good as the capability sheet it prints — a gate that cries wolf on half the ecosystem is worse than no gate, because people learn to type `y` without reading.
Vendored from https://github.com/lerd-env/lerd-omarchy-glance at commit
`15b988ec581c2210f7d558fd6784b8ebc9d4fd61` (pinned by the Omarchy plugin
marketplace registry as of 18 Aug 2026). MIT licensed — see `LICENSE`.

Included as a real-world example of a network fetcher (`net.outbound` via
`XMLHttpRequest` in `BarWidget.qml` and a bare URL in `Panel.qml`). The
repo's own `test/` directory was intentionally not vendored — it exercises
the same false-positive pattern (a `new Function(...)` module loader) that
motivated excluding test directories from behavioral scanning.

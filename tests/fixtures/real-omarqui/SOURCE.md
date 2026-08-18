Vendored from https://github.com/MarcusPelo/omarqui at commit
`50120a62781fce8e60bcc35e32306ce05683c365` (pinned by the Omarchy plugin
marketplace registry as of 18 Aug 2026). MIT licensed — see `LICENSE`.

Included as a real-world composition-risk example: a qBittorrent remote
control widget that reads its API key from `~/.config/omarqui/.env`
(`fs.sensitive`) and then makes outbound `curl` calls (`net.outbound`) to
the configured Qui instance. The intent is legitimate (the widget needs its
own API key to talk to the user's own qBittorrent instance), but it is
exactly the "reads credentials, can send them off-box" shape the composition
rule exists to surface — and a real test that the fixed `.env` pattern still
catches a genuine dotenv file path while ignoring the `Quickshell.env("HOME")`
call one token earlier on the same line.

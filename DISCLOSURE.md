# Disclosure policy

omaudit reports what a plugin *can reach*. Sometimes that surfaces something a
plugin author did not intend, or did not disclose. This is how that gets
handled.

## For findings in third-party plugins

1. **The author hears first.** A private issue or email to the plugin's
   maintainer, with the omaudit output and the specific file and line. No public
   post, no Discord message, no census entry naming them.
2. **90 days, or until it's fixed.** Whichever comes first. If the author ships a
   fix or adds an honest `permissions` block, the finding closes quietly and the
   plugin's grade updates on the next census run.
3. **Actively malicious code is different.** Credential exfiltration, hidden
   remote payloads, or anything that looks deliberately concealed goes to the
   Omarchy maintainers and the marketplace immediately, in parallel with
   notifying the author. Users installing it today outrank the author's dignity.
4. **The census publishes aggregates, not accusations.** "31% of plugins exec
   something they don't declare" is a statement about the ecosystem. "Plugin X
   steals your SSH key" is an accusation about a person, and it doesn't get made
   until step 1 and 2 have run.

## For findings in omaudit itself

A scanner that can be trivially evaded is worse than no scanner, because it
launders trust. Evasions are bugs and are treated as such.

Open an issue with the QML that slips past. Include the construct, not just the
claim. Bypasses get fixed and credited; there is no bounty and no embargo,
because the tool is a lint, not a security boundary, and pretending otherwise
would be the actual dishonesty.

## What omaudit does not claim

A grade is not a verdict on an author. `F` means "this reaches a lot and said
little about it," not "this person is hostile." Most low grades are honest
plugins that predate the declaration convention. Say so, every time.

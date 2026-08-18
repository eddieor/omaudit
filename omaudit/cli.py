"""omaudit — capability audit for Omarchy Quattro shell plugins."""

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import corpus as corpus_mod
from . import helptext
from . import manifest as manifest_mod
from . import paths as paths_mod
from . import registry as registry_mod
from . import report as report_mod
from .capabilities import CAPABILITIES
from .scan import scan
from .source import clone, current_commit, find_plugin_roots, rmtree_force

GRADE_ORDER = ["A", "B", "C", "D", "F"]

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_MANIFEST = 2
EXIT_USAGE = 3


def _audit(plugin_dir: Path) -> dict:
    m = manifest_mod.load(plugin_dir)
    result = scan(plugin_dir)
    return report_mod.build(m, result)


def _resolve(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_dir():
        print(f"omaudit: not a directory: {p}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    return p


def cmd_scan(args) -> int:
    doc = _audit(_resolve(args.plugin_dir))
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print(report_mod.human(doc))
    if not doc["manifest"]["valid"]:
        return EXIT_MANIFEST
    return EXIT_OK


def _load_baseline(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"omaudit: cannot read baseline {path}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    return set(data.get("acceptedCapabilities") or [])


def _read_baseline(path: Path) -> dict | None:
    """Tolerant reader for `check`, which must keep going across a whole
    plugins directory even if one baseline is missing or corrupt — unlike
    `_load_baseline`, which backs `verify` on a single plugin and can afford
    to hard-fail."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _baseline_snapshot(doc: dict, plugin_dir: Path | None = None) -> dict:
    observed = sorted(k for k, v in doc["capabilities"].items() if v["observed"])
    commit = current_commit(plugin_dir) if plugin_dir else None
    snapshot = {
        "omauditSchemaVersion": report_mod.SCHEMA_VERSION,
        "plugin": doc["plugin"]["id"],
        "version": doc["plugin"].get("version"),
        "recordedAt": doc["scannedAt"],
        "grade": doc["verdict"]["grade"],
        "acceptedCapabilities": observed,
        # only present when plugin_dir is a git checkout; lets `check` offer
        # [d]iff/[p]in against exactly the commit that was approved
        "commit": commit,
        "note": "Capabilities accepted as of this commit. verify --baseline "
                "fails only on capabilities added after this point.",
    }
    if plugin_dir and paths_mod.is_builtin(plugin_dir):
        snapshot["source"] = "builtin"
        snapshot["omarchyVersion"] = paths_mod.omarchy_version()
    return snapshot


def _write_baseline(out: Path, doc: dict, plugin_dir: Path) -> dict:
    snapshot = _baseline_snapshot(doc, plugin_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def _baseline_dest(plugin_dir: Path, plugin_id: str, out: str | None) -> Path:
    if out:
        return Path(out)
    return paths_mod.baseline_path(plugin_dir, plugin_id)


def _baseline_tree(root: Path, out_dir: Path | None) -> int:
    if not root.is_dir():
        print(f"omaudit: no plugins directory at {root}", file=sys.stderr)
        return EXIT_USAGE
    roots = find_plugin_roots(root)
    if not roots:
        print(f"omaudit: no plugins found in {root}", file=sys.stderr)
        return EXIT_USAGE
    n = 0
    for plugin_dir in roots:
        doc = _audit(plugin_dir)
        plugin_id = doc["plugin"]["id"]
        dest = (out_dir / f"{plugin_id}.json") if out_dir else paths_mod.baseline_path(
            plugin_dir, plugin_id)
        snapshot = _write_baseline(dest, doc, plugin_dir)
        print(f"  {plugin_id}: accepted {len(snapshot['acceptedCapabilities'])} "
              f"capability(ies) -> {dest}")
        n += 1
    print(f"omaudit: baselined {n} plugin(s)")
    return EXIT_OK


def cmd_baseline(args) -> int:
    """Snapshot today's capabilities as accepted, so verify only fails on drift.

    This is what makes the gate adoptable by a plugin that already exists: the
    author accepts what they have, and CI catches what they add next.
    `baseline --builtin` does the same for every first-party plugin shipped
    with Omarchy, writing to ~/.config/omaudit/baselines/ (the package tree
    is not writable).
    """
    if args.builtin:
        out_dir = Path(args.out) if args.out else None
        return _baseline_tree(paths_mod.builtin_plugins_dir(), out_dir)

    if not args.plugin_dir:
        print("omaudit: plugin directory required (or pass --builtin)",
              file=sys.stderr)
        return EXIT_USAGE

    plugin_dir = _resolve(args.plugin_dir)
    if not (plugin_dir / "manifest.json").is_file():
        out_dir = Path(args.out) if args.out else None
        return _baseline_tree(plugin_dir, out_dir)

    doc = _audit(plugin_dir)
    out = _baseline_dest(plugin_dir, doc["plugin"]["id"], args.out)
    snapshot = _write_baseline(out, doc, plugin_dir)
    print(f"omaudit: accepted {len(snapshot['acceptedCapabilities'])} capability(ies) -> {out}")
    return EXIT_OK


def cmd_verify(args) -> int:
    """CI gate: fail when capabilities are undeclared or the grade slips."""
    doc = _audit(_resolve(args.plugin_dir))
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print(report_mod.human(doc))

    if not doc["manifest"]["valid"]:
        return EXIT_MANIFEST

    failed = False

    if args.baseline:
        accepted = _load_baseline(Path(args.baseline))
        observed = {k for k, v in doc["capabilities"].items() if v["observed"]}
        added = observed - accepted
        if added:
            print("omaudit: capabilities added since the baseline: "
                  + ", ".join(sorted(added)), file=sys.stderr)
            failed = True
        removed = accepted - observed
        if removed:
            print("omaudit: note - baseline lists capabilities no longer "
                  "present: " + ", ".join(sorted(removed)), file=sys.stderr)
        return EXIT_FINDINGS if failed else EXIT_OK

    if doc["undeclared"] and not args.allow_undeclared:
        print(f"omaudit: {len(doc['undeclared'])} undeclared capability(ies)",
              file=sys.stderr)
        failed = True

    got, want = doc["verdict"]["grade"], args.max_grade.upper()
    if want not in GRADE_ORDER:
        print(f"omaudit: --max-grade must be one of {GRADE_ORDER}", file=sys.stderr)
        return EXIT_USAGE
    if GRADE_ORDER.index(got) > GRADE_ORDER.index(want):
        print(f"omaudit: grade {got} is worse than the {want} threshold",
              file=sys.stderr)
        failed = True

    return EXIT_FINDINGS if failed else EXIT_OK


def cmd_badge(args) -> int:
    doc = _audit(_resolve(args.plugin_dir))
    print(json.dumps(report_mod.badge(doc), indent=2))
    return EXIT_OK


def cmd_permissions(args) -> int:
    """Print a permissions block the author can paste into manifest.json."""
    doc = _audit(_resolve(args.plugin_dir))
    print(json.dumps({"permissions": doc["suggestedPermissions"]}, indent=2))
    return EXIT_OK


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def cmd_add(args) -> int:
    """Fetch a plugin, show what it actually does, and only install on
    explicit confirmation. This is the gate — `verify`/`baseline` are for
    plugins already on disk, `add` is for before they ever get there."""
    if args.local:
        root = Path(args.source).expanduser()
        if not root.is_dir():
            print(f"omaudit: not a directory: {root}", file=sys.stderr)
            return EXIT_USAGE
        tmp = None
    else:
        tmp = Path(tempfile.mkdtemp(prefix="omaudit-add-"))
        got = clone(args.source, tmp / "src")
        if not got:
            rmtree_force(tmp)
            print(f"omaudit: could not fetch {args.source}", file=sys.stderr)
            return EXIT_USAGE
        root = got

    try:
        roots = find_plugin_roots(root)
        if not roots:
            print(f"omaudit: no plugin found in {args.source}", file=sys.stderr)
            return EXIT_USAGE

        by_id = {manifest_mod.load(r).id: r for r in roots}
        if args.plugin:
            if args.plugin not in by_id:
                print(f"omaudit: no plugin '{args.plugin}' here. found: "
                      + ", ".join(sorted(by_id)), file=sys.stderr)
                return EXIT_USAGE
            plugin_root = by_id[args.plugin]
        elif len(roots) == 1:
            plugin_root = roots[0]
        else:
            print(f"omaudit: this source has {len(roots)} plugins - pick one "
                  "with --plugin\n  " + ", ".join(sorted(by_id)), file=sys.stderr)
            return EXIT_USAGE

        doc = _audit(plugin_root)
        if not doc["manifest"]["valid"]:
            print(report_mod.human(doc))
            return EXIT_MANIFEST

        print(report_mod.install_summary(doc))

        if not (args.yes or _confirm("Install anyway? [y/N] ")):
            print("aborted - nothing was written")
            return EXIT_OK

        return _install(args.source, doc)
    finally:
        if tmp:
            rmtree_force(tmp)


def _install(source: str, doc: dict) -> int:
    plugin_id = doc["plugin"]["id"]
    try:
        # omaudit already showed the capability sheet and got confirmation
        # (interactive or --yes). omarchy-plugin-add has its own prompt and
        # refuses without --yes when stdin isn't a tty — so we always pass it.
        subprocess.run(["omarchy", "plugin", "add", source, "--yes"], check=True)
    except FileNotFoundError:
        print("omaudit: 'omarchy' not found on PATH - could not install. "
              "Clone the plugin yourself and run `omaudit baseline <dir>`.",
              file=sys.stderr)
        return EXIT_USAGE
    except subprocess.CalledProcessError as exc:
        print(f"omaudit: omarchy plugin add failed (exit {exc.returncode})",
              file=sys.stderr)
        return EXIT_USAGE

    install_dir = Path.home() / ".config" / "omarchy" / "plugins" / plugin_id
    if not install_dir.is_dir():
        print(f"omaudit: installed, but could not find it at {install_dir} "
              "to write a baseline. Run `omaudit baseline <dir>` manually.",
              file=sys.stderr)
        return EXIT_OK

    installed_doc = _audit(install_dir)
    snapshot = _write_baseline(install_dir / ".omaudit-baseline.json", installed_doc, install_dir)
    print(f"omaudit: installed {plugin_id} - accepted "
          f"{len(snapshot['acceptedCapabilities'])} capability(ies)")
    return EXIT_OK


def _check_plugin(plugin_dir: Path) -> dict:
    doc = _audit(plugin_dir)
    plugin_id = doc["plugin"]["id"]
    first_party = (paths_mod.is_builtin(plugin_dir)
                   or plugin_id.startswith("omarchy."))
    observed = sorted(k for k, v in doc["capabilities"].items() if v["observed"])
    result = {
        "id": plugin_id,
        "name": doc["plugin"].get("name"),
        "dir": str(plugin_dir),
        "version": doc["plugin"].get("version"),
        "kinds": doc["plugin"].get("kinds") or [],
        "grade": doc["verdict"]["grade"],
        "score": doc["verdict"]["score"],
        "observed": observed,
        "composition": [r for r in doc["verdict"]["reasons"]
                        if r.startswith("composition:")],
        "firstParty": first_party,
        "baseline": None,
        "added": [],
        "evidence": {},
    }

    dest = paths_mod.baseline_path(plugin_dir, plugin_id)
    baseline = _read_baseline(dest) if dest.is_file() else None
    if baseline is None:
        result["status"] = "not-tracked"
        return result

    result["baseline"] = baseline
    accepted = set(baseline.get("acceptedCapabilities") or [])
    added = sorted(set(observed) - accepted)

    if not added:
        result["status"] = "unchanged"
        return result

    result["status"] = "changed"
    result["added"] = added
    for cap_id in added:
        evidence = doc["capabilities"][cap_id]["evidence"]
        if evidence:
            result["evidence"][cap_id] = (evidence[0]["file"], evidence[0]["line"])
    return result


def _prompt_menu() -> str:
    try:
        answer = input("  [d]iff the source  [p]in to old  [r]emove  [a]ccept  [s]kip  ")
    except EOFError:
        return "s"
    answer = answer.strip().lower()
    return answer if answer in ("d", "p", "r", "a", "s") else "s"


def _diff_source(plugin_dir: Path, baseline: dict) -> None:
    if paths_mod.is_builtin(plugin_dir):
        print("  can't diff: first-party plugins ship with Omarchy, not as a git checkout")
        return
    commit = baseline.get("commit")
    if not commit:
        print("  can't diff: no commit was recorded when this was approved")
        return
    try:
        subprocess.run(["git", "-C", str(plugin_dir), "diff", commit])
    except FileNotFoundError:
        print("  can't diff: git not found on PATH")


def _pin_source(plugin_dir: Path, baseline: dict) -> bool:
    if paths_mod.is_builtin(plugin_dir):
        print("  can't pin: first-party plugins ship with Omarchy, not as a git checkout")
        return False
    commit = baseline.get("commit")
    if not commit:
        print("  can't pin: no commit was recorded when this was approved")
        return False
    if not _confirm(f"  Roll back to {commit[:7]}? This checks out that commit "
                     f"in place. [y/N] "):
        print("  not pinned")
        return False
    try:
        subprocess.run(["git", "-C", str(plugin_dir), "checkout", "--quiet", commit],
                       check=True)
        print(f"  pinned to {commit[:7]}")
        return True
    except FileNotFoundError:
        print("  can't pin: git not found on PATH")
        return False
    except subprocess.CalledProcessError as exc:
        print(f"  pin failed (exit {exc.returncode})")
        return False


def _remove_plugin(plugin_id: str, plugin_dir: Path | None = None) -> bool:
    if (plugin_dir and paths_mod.is_builtin(plugin_dir)) or plugin_id.startswith("omarchy."):
        print("  can't remove: first-party plugins are part of Omarchy")
        return False
    try:
        subprocess.run(["omarchy", "plugin", "remove", plugin_id, "--yes"], check=True)
        print(f"  removed {plugin_id}")
        return True
    except FileNotFoundError:
        print("  can't remove: 'omarchy' not found on PATH")
        return False
    except subprocess.CalledProcessError as exc:
        print(f"  remove failed (exit {exc.returncode})")
        return False


def _resolve_change(plugin_dir: Path, result: dict) -> bool:
    """Walk the user through one changed plugin's options. Returns True once
    it's resolved (accepted, removed, or pinned back); False if skipped."""
    baseline = result["baseline"]
    while True:
        action = _prompt_menu()

        if action == "d":
            _diff_source(plugin_dir, baseline)
            continue

        if action == "p":
            return _pin_source(plugin_dir, baseline)

        if action == "r":
            return _remove_plugin(result["id"], plugin_dir)

        if action == "a":
            doc = _audit(plugin_dir)
            dest = paths_mod.baseline_path(plugin_dir, result["id"])
            _write_baseline(dest, doc, plugin_dir)
            print(f"  accepted - {result['id']} baseline updated")
            return True

        return False  # skip


def _check_roots(args) -> list[Path]:
    """Which plugin trees `check` should walk.

    check                -> ~/.config/omarchy/plugins
    check --dir X        -> X
    check --builtin      -> $OMARCHY_PATH/shell/plugins
    check --all          -> user + first-party
    check --dir X --all  -> X + first-party
    """
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(root: Path) -> None:
        key = root.expanduser()
        if key in seen:
            return
        seen.add(key)
        roots.append(key)

    if args.dir:
        add(Path(args.dir))
    if args.all and not args.dir:
        add(paths_mod.user_plugins_dir())
    if args.builtin or args.all:
        add(paths_mod.builtin_plugins_dir())
    if not roots:
        add(paths_mod.user_plugins_dir())
    return roots


def _collect_plugin_dirs(roots: list[Path]) -> tuple[list[Path], list[Path]]:
    """Return (existing roots, plugin dirs). Missing roots stay in the
    first list so the caller can say which path wasn't there."""
    existing = [r for r in roots if r.is_dir()]
    plugin_dirs: list[Path] = []
    seen: set[Path] = set()
    for root in existing:
        for plugin_dir in find_plugin_roots(root):
            if plugin_dir not in seen:
                seen.add(plugin_dir)
                plugin_dirs.append(plugin_dir)
    plugin_dirs.sort()
    return existing, plugin_dirs


def cmd_check(args) -> int:
    """Re-audit every installed plugin against the baseline you approved it
    under. You vetted it once; nobody re-reads QML on update — this is what
    catches drift without you having to."""
    roots = _check_roots(args)
    existing, plugin_dirs = _collect_plugin_dirs(roots)
    if not existing:
        print("omaudit: no plugins directory at " + ", ".join(str(r) for r in roots))
        return EXIT_OK

    results = [_check_plugin(p) for p in plugin_dirs]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(report_mod.check_summary(results))

    changed = [r for r in results if r["status"] == "changed"]
    if not changed:
        return EXIT_OK
    if args.json or args.yes:
        return EXIT_FINDINGS

    unresolved = [r for r in changed if not _resolve_change(Path(r["dir"]), r)]
    return EXIT_FINDINGS if unresolved else EXIT_OK


def cmd_report(args) -> int:
    """Re-scan every tracked plugin and write a report card: grades,
    capabilities, drift against the baseline you already approved. This is
    the thing you keep so you can verify later without walking QML again."""
    if not args.dir and not args.builtin:
        args.all = True
    roots = _check_roots(args)
    existing, plugin_dirs = _collect_plugin_dirs(roots)
    if not existing:
        print("omaudit: no plugins directory at " + ", ".join(str(r) for r in roots))
        return EXIT_OK

    results = [_check_plugin(p) for p in plugin_dirs]
    scanned_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    version = paths_mod.omarchy_version()

    if args.json:
        doc = report_mod.report_card_json(results, scanned_at, version)
        text = json.dumps(doc, indent=2) + "\n"
    else:
        text = report_mod.report_card(results, scanned_at, version)

    print(text, end="" if text.endswith("\n") else "\n")

    dest = Path(args.out).expanduser() if args.out else paths_mod.report_card_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    print(f"wrote {dest}")

    if any(r["status"] == "changed" for r in results):
        return EXIT_FINDINGS
    return EXIT_OK


def _print_registry_delta(stats: dict, delta: dict) -> None:
    added, removed = delta["added"], delta["removed"]
    print(f"{stats['sources']} sources on omarchyplugins.com"
          f"  ({stats['withUpstreamBaseline']} with an install-path baseline)")
    if delta.get("first"):
        print("  first fetch of the live listing")
    elif added or removed:
        print(f"  +{len(added)} new   -{len(removed)} gone since last fetch")
        for spec in sorted(added)[:8]:
            print(f"    + {spec.partition('@')[0]}")
        if len(added) > 8:
            print(f"    + ... {len(added) - 8} more")
    else:
        print("  no listing changes since last fetch")
    print(f"upstream findings: {stats['baselineFindingCount']}")


def cmd_census(args) -> int:
    """Pull the live marketplace registry and (unless --fetch-only) audit
    every listed plugin. This is a dated snapshot you run on purpose —
    not a timer, and not mixed into `report`."""
    out = Path(args.out).expanduser() if args.out else paths_mod.census_dir()

    if args.render:
        corpus = out / "corpus.json"
        if not corpus.is_file():
            print(f"omaudit: no corpus at {corpus} - run `omaudit census` first",
                  file=sys.stderr)
            return EXIT_USAGE
        docs = json.loads(corpus.read_text(encoding="utf-8"))
        summary = corpus_mod.write_corpus(out, docs)
        print(corpus_mod.render(summary))
        print(f"wrote {out}/summary.json, summary.txt")
        return EXIT_OK

    if args.local:
        docs = corpus_mod.run_local(Path(args.local).expanduser())
        summary = corpus_mod.write_corpus(out, docs)
        print(corpus_mod.render(summary))
        print(f"wrote {out}/corpus.json, summary.json, summary.txt")
        return EXIT_OK

    url = args.url or registry_mod.REGISTRY_URL
    print(f"fetching {url}")
    try:
        registry = registry_mod.fetch(url)
    except registry_mod.RegistryError as exc:
        print(f"omaudit: {exc}", file=sys.stderr)
        return EXIT_USAGE

    entries, stats = registry_mod.extract(registry)
    delta = registry_mod.write_listing(out, entries, stats)
    _print_registry_delta(stats, delta)
    print(f"wrote {out}/plugins.txt")

    if args.fetch_only:
        return EXIT_OK

    specs = corpus_mod.load_specs(out / "plugins.txt")
    if args.limit:
        specs = specs[: args.limit]
        print(f"limiting to first {len(specs)} source(s)")
    clones = (Path(args.keep_clones).expanduser() if args.keep_clones
              else paths_mod.clone_cache_dir())
    print(f"clones: {clones}")
    docs = corpus_mod.run_from_specs(specs, clones)

    summary = corpus_mod.write_corpus(out, docs)
    print(corpus_mod.render(summary))
    print(f"wrote {out}/corpus.json, summary.json, summary.txt")
    print("aggregates only - do not name a plugin from this output "
          "without following DISCLOSURE.md")
    return EXIT_OK


def cmd_schema(args) -> int:
    """Emit the capability vocabulary as machine-readable JSON."""
    print(json.dumps({
        "omauditSchemaVersion": report_mod.SCHEMA_VERSION,
        "capabilities": {
            c.id: {
                "title": c.title,
                "question": c.question,
                "weight": c.weight,
                "needsScope": c.needs_scope,
                "scopeHint": c.scope_hint,
            } for c in CAPABILITIES.values()
        },
    }, indent=2))
    return EXIT_OK


def cmd_help(args) -> int:
    text = helptext.page(args.topic)
    if text is None:
        known = ", ".join(helptext.topics())
        print(f"omaudit: no help for '{args.topic}'. try one of: {known}",
              file=sys.stderr)
        return EXIT_USAGE
    print(text, end="" if text.endswith("\n") else "\n")
    return EXIT_OK


class _Parser(argparse.ArgumentParser):
    """Bare `omaudit` and `omaudit --help` show the command list, not
    argparse's default dump. Unknown commands point at `omaudit help`."""

    def format_help(self) -> str:
        # Subparsers are the same class; only the root command list
        # replaces argparse's default dump.
        if self.prog == "omaudit":
            return helptext.overview()
        return super().format_help()

    def error(self, message: str) -> None:
        if "invalid choice" in message:
            print("omaudit: unknown command. try `omaudit help`", file=sys.stderr)
            raise SystemExit(EXIT_USAGE)
        self.print_usage(sys.stderr)
        print(f"omaudit: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _sub(sub: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    page = helptext.PAGES[name]
    return sub.add_parser(
        name,
        help=page["summary"],
        description=page["summary"],
        epilog=page["body"],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="omaudit",
        description=helptext.PAGES["help"]["summary"],
    )
    sub = p.add_subparsers(dest="command", required=False)

    s = _sub(sub, "scan")
    s.add_argument("plugin_dir")
    s.add_argument("--json", action="store_true", help="emit the full JSON report")
    s.set_defaults(func=cmd_scan)

    v = _sub(sub, "verify")
    v.add_argument("plugin_dir")
    v.add_argument("--max-grade", default="B", help="worst acceptable grade (default: B)")
    v.add_argument("--allow-undeclared", action="store_true")
    v.add_argument("--baseline", metavar="FILE",
                   help="accept the capabilities in FILE; fail only on new ones")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_verify)

    b = _sub(sub, "badge")
    b.add_argument("plugin_dir")
    b.set_defaults(func=cmd_badge)

    pm = _sub(sub, "permissions")
    pm.add_argument("plugin_dir")
    pm.set_defaults(func=cmd_permissions)

    bl = _sub(sub, "baseline")
    bl.add_argument("plugin_dir", nargs="?", default=None)
    bl.add_argument("--builtin", action="store_true",
                    help="snapshot every first-party plugin shipped with Omarchy")
    bl.add_argument("--out", help="output path (default: sidecar, or "
                    "~/.config/omaudit/baselines/ for first-party plugins)")
    bl.set_defaults(func=cmd_baseline)

    sc = _sub(sub, "schema")
    sc.set_defaults(func=cmd_schema)

    a = _sub(sub, "add")
    a.add_argument("source", help="git URL, or a directory with --local")
    a.add_argument("--local", action="store_true",
                   help="treat source as an already-checked-out directory")
    a.add_argument("--plugin", metavar="ID",
                   help="which plugin to install, if source holds more than one")
    a.add_argument("-y", "--yes", action="store_true",
                   help="skip the confirmation prompt")
    a.set_defaults(func=cmd_add)

    c = _sub(sub, "check")
    c.add_argument("--dir", metavar="DIR",
                   help="plugins directory (default: ~/.config/omarchy/plugins)")
    c.add_argument("--builtin", action="store_true",
                   help="audit first-party plugins shipped with Omarchy")
    c.add_argument("--all", action="store_true",
                   help="audit user-installed and first-party plugins")
    c.add_argument("--json", action="store_true", help="machine-readable report, no prompts")
    c.add_argument("-y", "--yes", action="store_true",
                   help="print the report without prompting (for cron/omarchy update hooks)")
    c.set_defaults(func=cmd_check)

    rp = _sub(sub, "report")
    rp.add_argument("--dir", metavar="DIR",
                    help="plugins directory (default: user + first-party)")
    rp.add_argument("--builtin", action="store_true",
                    help="first-party plugins only")
    rp.add_argument("--all", action="store_true",
                    help="user-installed and first-party (the default)")
    rp.add_argument("--out", metavar="FILE",
                    help="write the card here (default: ~/.config/omaudit/report-card.txt)")
    rp.add_argument("--json", action="store_true", help="machine-readable card")
    rp.set_defaults(func=cmd_report)

    ce = _sub(sub, "census")
    ce.add_argument("--fetch-only", action="store_true",
                    help="refresh the source list, do not clone or audit")
    ce.add_argument("--render", action="store_true",
                    help="re-summarize an existing corpus.json")
    ce.add_argument("--out", metavar="DIR",
                    help="output directory (default: ~/.config/omaudit/census)")
    ce.add_argument("--keep-clones", metavar="DIR",
                    help="clone cache (default: ~/.cache/omaudit/clones)")
    ce.add_argument("--limit", type=int, metavar="N",
                    help="audit only the first N sources (for a smoke run)")
    ce.add_argument("--local", metavar="DIR",
                    help="audit an already-checked-out tree instead of cloning")
    ce.add_argument("--url", help="registry URL (default: HANCORE's live feed)")
    ce.set_defaults(func=cmd_census)

    h = _sub(sub, "help")
    h.add_argument("topic", nargs="?", default=None,
                   help="command name, or 'grades'")
    h.set_defaults(func=cmd_help)

    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if not getattr(args, "func", None):
            print(helptext.overview(), end="")
            return EXIT_OK
        return args.func(args)
    except BrokenPipeError:
        # `omaudit scan ... | head` closes stdout mid-write.
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass
        return EXIT_OK
    except SystemExit as exc:
        # argparse --help / error() raise SystemExit; keep one return path
        # so `main(["help"])` and `main(["--help"])` both just return 0.
        if exc.code in (None, 0):
            return EXIT_OK
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())

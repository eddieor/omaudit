"""omaudit — capability audit for Omarchy Quattro shell plugins."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import manifest as manifest_mod
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
    return {
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


def _write_baseline(out: Path, doc: dict, plugin_dir: Path) -> dict:
    snapshot = _baseline_snapshot(doc, plugin_dir)
    out.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def cmd_baseline(args) -> int:
    """Snapshot today's capabilities as accepted, so verify only fails on drift.

    This is what makes the gate adoptable by a plugin that already exists: the
    author accepts what they have, and CI catches what they add next.
    """
    plugin_dir = _resolve(args.plugin_dir)
    doc = _audit(plugin_dir)
    out = Path(args.out) if args.out else plugin_dir / ".omaudit-baseline.json"
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
        subprocess.run(["omarchy", "plugin", "add", source], check=True)
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
    result = {
        "id": doc["plugin"]["id"],
        "name": doc["plugin"].get("name"),
        "dir": str(plugin_dir),
        "version": doc["plugin"].get("version"),
        "grade": doc["verdict"]["grade"],
        "baseline": None,
        "added": [],
        "evidence": {},
    }

    baseline_path = plugin_dir / ".omaudit-baseline.json"
    baseline = _read_baseline(baseline_path) if baseline_path.is_file() else None
    if baseline is None:
        result["status"] = "not-tracked"
        return result

    result["baseline"] = baseline
    accepted = set(baseline.get("acceptedCapabilities") or [])
    observed = {k for k, v in doc["capabilities"].items() if v["observed"]}
    added = sorted(observed - accepted)

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
    commit = baseline.get("commit")
    if not commit:
        print("  can't diff: no commit was recorded when this was approved")
        return
    try:
        subprocess.run(["git", "-C", str(plugin_dir), "diff", commit])
    except FileNotFoundError:
        print("  can't diff: git not found on PATH")


def _pin_source(plugin_dir: Path, baseline: dict) -> bool:
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


def _remove_plugin(plugin_id: str) -> bool:
    try:
        subprocess.run(["omarchy", "plugin", "remove", plugin_id], check=True)
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
            return _remove_plugin(result["id"])

        if action == "a":
            doc = _audit(plugin_dir)
            _write_baseline(plugin_dir / ".omaudit-baseline.json", doc, plugin_dir)
            print(f"  accepted - {result['id']} baseline updated")
            return True

        return False  # skip


def cmd_check(args) -> int:
    """Re-audit every installed plugin against the baseline you approved it
    under. You vetted it once; nobody re-reads QML on update — this is what
    catches drift without you having to."""
    root = (Path(args.dir).expanduser() if args.dir
            else Path.home() / ".config" / "omarchy" / "plugins")
    if not root.is_dir():
        print(f"omaudit: no plugins directory at {root}")
        return EXIT_OK

    plugin_dirs = sorted(p for p in root.iterdir()
                         if p.is_dir() and (p / "manifest.json").is_file())
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omaudit",
        description="Capability audit for Omarchy Quattro shell plugins. "
                    "Plugins run unsandboxed in the shell process; this tells "
                    "you what one can reach before you install it.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="audit a plugin directory")
    s.add_argument("plugin_dir")
    s.add_argument("--json", action="store_true", help="emit the full JSON report")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("verify", help="CI gate: non-zero exit on undeclared capabilities")
    v.add_argument("plugin_dir")
    v.add_argument("--max-grade", default="B", help="worst acceptable grade (default: B)")
    v.add_argument("--allow-undeclared", action="store_true")
    v.add_argument("--baseline", metavar="FILE",
                   help="accept the capabilities in FILE; fail only on new ones")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_verify)

    b = sub.add_parser("badge", help="emit a shields.io endpoint JSON")
    b.add_argument("plugin_dir")
    b.set_defaults(func=cmd_badge)

    pm = sub.add_parser("permissions", help="suggest a manifest permissions block")
    pm.add_argument("plugin_dir")
    pm.set_defaults(func=cmd_permissions)

    bl = sub.add_parser("baseline",
                        help="snapshot current capabilities as accepted")
    bl.add_argument("plugin_dir")
    bl.add_argument("--out", help="output path (default: <dir>/.omaudit-baseline.json)")
    bl.set_defaults(func=cmd_baseline)

    sc = sub.add_parser("schema", help="print the capability vocabulary")
    sc.set_defaults(func=cmd_schema)

    a = sub.add_parser("add", help="review a plugin's capabilities, then install it")
    a.add_argument("source", help="git URL, or a directory with --local")
    a.add_argument("--local", action="store_true",
                   help="treat source as an already-checked-out directory")
    a.add_argument("--plugin", metavar="ID",
                   help="which plugin to install, if source holds more than one")
    a.add_argument("-y", "--yes", action="store_true",
                   help="skip the confirmation prompt")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("check", help="re-audit installed plugins against their baseline")
    c.add_argument("--dir", metavar="DIR",
                   help="plugins directory (default: ~/.config/omarchy/plugins)")
    c.add_argument("--json", action="store_true", help="machine-readable report, no prompts")
    c.add_argument("-y", "--yes", action="store_true",
                   help="print the report without prompting (for cron/omarchy update hooks)")
    c.set_defaults(func=cmd_check)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

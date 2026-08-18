#!/usr/bin/env python3
"""
Ecosystem census.

Shallow-clones every plugin repo in a list, audits it, and emits both a JSON
corpus and a summary table. This is the thing that turns omaudit from "a tool I
made" into "here is what is actually running in Omarchy bars today" — which is
news, and travels, in a way that a tool announcement does not.

Usage:
    python3 census.py plugins.txt --out census/
    python3 census.py plugins.txt --out census/ --local   # skip cloning

plugins.txt: one git URL per line, '#' comments allowed. Or point --local at a
directory of already-checked-out plugins.
"""

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from omaudit.cli import _audit  # noqa: E402
from omaudit.source import clone, find_plugin_roots, is_cached, rmtree_force  # noqa: E402

GRADES = ["A", "B", "C", "D", "F"]


def audit_all(sources: list[tuple[str, Path]]) -> list[dict]:
    docs = []
    for label, path in sources:
        for plugin_root in find_plugin_roots(path) or []:
            try:
                doc = _audit(plugin_root)
            except Exception as exc:  # a broken plugin must not kill the run
                print(f"  ! audit failed: {label} ({exc})", file=sys.stderr)
                continue
            doc["source"] = label
            docs.append(doc)
            print(f"  {doc['verdict']['grade']}  {doc['plugin']['id']}")
    return docs


def summarize(docs: list[dict]) -> dict:
    grades = Counter(d["verdict"]["grade"] for d in docs)
    caps = Counter()
    undeclared = Counter()
    for d in docs:
        for cap, info in d["capabilities"].items():
            if info["observed"]:
                caps[cap] += 1
        for cap in d["undeclared"]:
            undeclared[cap] += 1

    declaring = sum(1 for d in docs if any(
        i["declared"] for i in d["capabilities"].values()))

    return {
        "pluginsAudited": len(docs),
        "declaringPermissions": declaring,
        "grades": {g: grades.get(g, 0) for g in GRADES},
        "capabilityFrequency": dict(caps.most_common()),
        "undeclaredFrequency": dict(undeclared.most_common()),
        "compositionRisks": [
            {"plugin": d["plugin"]["id"], "reasons": d["verdict"]["reasons"]}
            for d in docs
            if any("composition" in r for r in d["verdict"]["reasons"])
        ],
    }


def render(summary: dict) -> str:
    n = summary["pluginsAudited"] or 1
    out = ["", f"{summary['pluginsAudited']} plugins audited", ""]
    out.append("grades")
    for g in GRADES:
        c = summary["grades"][g]
        bar = "#" * round(40 * c / n)
        out.append(f"  {g}  {c:>4}  {bar}")
    out.append("")
    out.append(f"declaring permissions: {summary['declaringPermissions']} "
               f"of {summary['pluginsAudited']}")
    out.append("")
    out.append("most common capabilities")
    for cap, c in list(summary["capabilityFrequency"].items())[:10]:
        out.append(f"  {c:>4}  {cap}")
    if summary["compositionRisks"]:
        out.append("")
        out.append(f"composition risks: {len(summary['compositionRisks'])}")
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit the whole plugin ecosystem")
    ap.add_argument("source", nargs="?", default=None,
                    help="file of git URLs, or a directory with --local "
                         "(omit when using --render-only)")
    ap.add_argument("--out", default="census", help="output directory")
    ap.add_argument("--local", action="store_true",
                    help="treat source as a directory of checked-out plugins")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the summary from an existing corpus.json")
    ap.add_argument("--keep-clones", metavar="DIR", default=None,
                    help="persistent clone cache instead of a throwaway temp dir; "
                         "repeat runs skip the network for any source whose pinned "
                         "commit is already checked out there")
    args = ap.parse_args()

    if not args.render_only and args.source is None:
        ap.error("source is required unless --render-only is set")

    if args.render_only:
        out = Path(args.out)
        docs = json.loads((out / "corpus.json").read_text(encoding="utf-8"))
        summary = summarize(docs)
        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (out / "summary.txt").write_text(render(summary), encoding="utf-8")
        print(render(summary))
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.local:
        root = Path(args.source)
        sources = [(p.name, p) for p in sorted(root.iterdir()) if p.is_dir()]
        docs = audit_all(sources)
    else:
        urls = [ln.strip() for ln in Path(args.source).read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
        if args.keep_clones:
            tmp = Path(args.keep_clones)
            tmp.mkdir(parents=True, exist_ok=True)
        else:
            tmp = Path(tempfile.mkdtemp(prefix="omaudit-census-"))
        try:
            sources = []
            for url in urls:
                name = url.partition("@")[0].rstrip("/").split("/")[-1].removesuffix(".git")
                dest = tmp / name
                print(f"{'cached' if is_cached(url, dest) else 'cloning'} {name}")
                got = clone(url, dest)
                if got:
                    sources.append((url, got))
            docs = audit_all(sources)
        finally:
            if not args.keep_clones:
                rmtree_force(tmp)

    summary = summarize(docs)
    (out / "corpus.json").write_text(json.dumps(docs, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(render(summary), encoding="utf-8")
    print(render(summary))
    print(f"wrote {out}/corpus.json, summary.json, summary.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

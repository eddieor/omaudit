"""Ecosystem census: clone the marketplace listing and audit each plugin.

This is a dated snapshot, not a live feed. `omaudit report` is what you
installed. This is what the website is listing.
"""

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

from . import manifest as manifest_mod
from . import report as report_mod
from .scan import scan
from .source import clone, find_plugin_roots, is_cached, rmtree_force

GRADES = ["A", "B", "C", "D", "F"]


def _audit(plugin_dir: Path) -> dict:
    return report_mod.build(manifest_mod.load(plugin_dir), scan(plugin_dir))


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


def clone_name(spec: str) -> str:
    return spec.partition("@")[0].rstrip("/").split("/")[-1].removesuffix(".git")


def load_specs(path: Path) -> list[str]:
    return [
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def write_corpus(out: Path, docs: list[dict]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(docs)
    (out / "corpus.json").write_text(json.dumps(docs, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(render(summary), encoding="utf-8")
    return summary


def run_from_specs(specs: list[str], clones: Path | None) -> list[dict]:
    if clones:
        tmp = clones
        tmp.mkdir(parents=True, exist_ok=True)
        ephemeral = False
    else:
        tmp = Path(tempfile.mkdtemp(prefix="omaudit-census-"))
        ephemeral = True
    try:
        sources = []
        for spec in specs:
            name = clone_name(spec)
            dest = tmp / name
            print(f"{'cached' if is_cached(spec, dest) else 'cloning'} {name}")
            got = clone(spec, dest)
            if got:
                sources.append((spec, got))
        return audit_all(sources)
    finally:
        if ephemeral:
            rmtree_force(tmp)


def run_local(root: Path) -> list[dict]:
    sources = [(p.name, p) for p in sorted(root.iterdir()) if p.is_dir()]
    return audit_all(sources)

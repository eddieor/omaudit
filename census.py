#!/usr/bin/env python3
"""Thin wrapper — prefer `omaudit census`."""

import argparse
import json
from pathlib import Path

from omaudit.corpus import (
    load_specs, render, run_from_specs, run_local, write_corpus,
)


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
                    help="persistent clone cache instead of a throwaway temp dir")
    args = ap.parse_args()

    if not args.render_only and args.source is None:
        ap.error("source is required unless --render-only is set")

    out = Path(args.out)
    if args.render_only:
        docs = json.loads((out / "corpus.json").read_text(encoding="utf-8"))
        summary = write_corpus(out, docs)
        print(render(summary))
        return 0

    if args.local:
        docs = run_local(Path(args.source))
    else:
        specs = load_specs(Path(args.source))
        clones = Path(args.keep_clones) if args.keep_clones else None
        docs = run_from_specs(specs, clones)

    summary = write_corpus(out, docs)
    print(render(summary))
    print(f"wrote {out}/corpus.json, summary.json, summary.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

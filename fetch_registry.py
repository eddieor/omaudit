#!/usr/bin/env python3
"""Thin wrapper — prefer `omaudit census --fetch-only`."""

import argparse
import sys
from pathlib import Path

from omaudit.registry import REGISTRY_URL, RegistryError, extract, fetch, write_listing


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch the marketplace registry")
    ap.add_argument("--url", default=REGISTRY_URL)
    ap.add_argument("--out", default="census")
    ap.add_argument("--unpinned", action="store_true",
                    help="emit bare repo URLs instead of repo@commit")
    args = ap.parse_args()

    out = Path(args.out)
    print(f"fetching {args.url}")
    try:
        registry = fetch(args.url)
    except RegistryError as exc:
        print(f"fetch_registry: {exc}", file=sys.stderr)
        return 1

    entries, stats = extract(registry)
    write_listing(out, entries, stats, unpinned=args.unpinned)

    print(f"\n{stats['sources']} sources, "
          f"{stats['withUpstreamBaseline']} with an upstream security baseline")
    print(f"upstream outcomes: {stats['baselineOutcomes']}")
    print(f"upstream findings across the whole registry: "
          f"{stats['baselineFindingCount']}")
    print("\nupstream capability vocabulary (install-path coverage):")
    for cap, n in stats["baselineCapabilityFrequency"].items():
        print(f"  {n:>4}  {cap}")
    print(f"\nwrote {out}/plugins.txt, registry-entries.json, "
          f"upstream-baseline.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Report rendering: human, JSON, and badge."""

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from .capabilities import (
    CAPABILITIES, EXFIL_PAIRS, FLAGGED_CAPABILITY_IDS, GRADE_GLOSS,
    GRADE_RANGE, grade, grade_gloss,
)
from .manifest import Manifest, suggest_permissions
from .scan import ScanResult

SCHEMA_VERSION = 1

BADGE_COLOR = {"A": "brightgreen", "B": "green", "C": "yellow", "D": "orange", "F": "red"}


def _tty() -> bool:
    return sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


def build(manifest: Manifest, result: ScanResult) -> dict:
    observed = result.observed
    declared = manifest.declared
    undeclared = observed - declared
    overdeclared = declared - observed
    scopes = result.scopes()
    unreadable = bool(result.binaries)
    verdict = grade(observed, undeclared, unreadable,
                     schema_adopted=manifest.has_permissions_block)

    capabilities = {}
    for cap_id in sorted(observed | declared):
        cap = CAPABILITIES.get(cap_id)
        evidence = [
            {"file": f.file, "line": f.line, "rule": f.rule_id,
             "why": f.why, "snippet": f.snippet}
            for f in result.by_capability().get(cap_id, [])
        ][:12]
        capabilities[cap_id] = {
            "title": cap.title if cap else cap_id,
            "observed": cap_id in observed,
            "declared": cap_id in declared,
            "declaredScope": manifest.declared_scope(cap_id),
            "observedScope": sorted(scopes.get(cap_id, set())),
            "reason": manifest.reason(cap_id),
            "evidence": evidence,
        }

    return {
        "omauditSchemaVersion": SCHEMA_VERSION,
        "plugin": {
            "id": manifest.id,
            "name": manifest.data.get("name"),
            "version": manifest.data.get("version"),
            "kinds": manifest.data.get("kinds", []),
        },
        "scannedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filesScanned": result.files_scanned,
        "manifest": {
            "valid": manifest.ok,
            "errors": manifest.errors,
            "warnings": manifest.warnings,
        },
        "capabilities": capabilities,
        "undeclared": sorted(undeclared),
        "overdeclared": sorted(overdeclared),
        "unreadableArtifacts": result.binaries,
        "verdict": {
            "grade": verdict.grade,
            "score": verdict.score,
            "reasons": verdict.reasons,
        },
        "suggestedPermissions": suggest_permissions(
            {c: scopes.get(c, set()) for c in observed}
        ),
    }


def badge(doc: dict) -> dict:
    g = doc["verdict"]["grade"]
    return {
        "schemaVersion": 1,
        "label": "omaudit",
        "message": f"{g} · {len(doc['capabilities'])} caps",
        "color": BADGE_COLOR[g],
    }


def install_summary(doc: dict) -> str:
    """The `omaudit add` gate screen: what a plugin does, in plain language,
    before you install it. Deliberately narrower than `human()` — this is
    meant to be read in the ten seconds before an install prompt, not
    studied. See functionality.md for the worked example this renders."""
    out: list[str] = []
    p = doc["plugin"]
    name = p.get("name") or p["id"]
    version = p.get("version") or ""
    out.append("")
    letter = doc["verdict"]["grade"]
    gloss = grade_gloss(letter)
    label = f"grade {letter} - {gloss}" if gloss else f"grade {letter}"
    out.append(f"  {name} {version} - {label}".rstrip())
    out.append("")

    caps = doc["capabilities"]
    if not caps:
        out.append("  no capabilities detected - this plugin only draws.")
        out.append("")
        return "\n".join(out)

    plain = {cid: info for cid, info in caps.items()
             if info["observed"] and cid not in FLAGGED_CAPABILITY_IDS}
    flagged = {cid: info for cid, info in caps.items()
               if info["observed"] and cid in FLAGGED_CAPABILITY_IDS}

    for cid, info in plain.items():
        cap = CAPABILITIES.get(cid)
        phrase = cap.install_phrase if cap else cid
        scope = ", ".join(info["observedScope"][:6])
        gap = " " * max(1, 22 - len(phrase))
        out.append(f"  {phrase}{gap}{scope}".rstrip())
    if plain:
        out.append("")

    if flagged:
        fired = {legs[0]: why for legs, why in EXFIL_PAIRS
                 if f"composition: {why}" in doc["verdict"]["reasons"]}
        for cid, info in flagged.items():
            cap = CAPABILITIES.get(cid)
            why = fired.get(cid) or (cap.install_phrase if cap else cid)
            out.append(f"  ! {why}")
            for ev in info["evidence"][:1]:
                out.append(f"    {ev['file']}:{ev['line']}  {ev['why']}")
        out.append("")

    declared_ids = sorted(cid for cid, info in caps.items() if info["declared"])
    if declared_ids:
        phrases = ", ".join(
            CAPABILITIES[c].install_phrase if c in CAPABILITIES else c
            for c in declared_ids
        )
        out.append(f"  the author declared: {phrases}")
    else:
        out.append("  the author declared nothing")
    out.append("  everything else is undeclared" if doc["undeclared"] and declared_ids
                else "  everything is undeclared" if doc["undeclared"]
                else "  everything is declared")
    out.append("")
    return "\n".join(out)


def check_summary(results: list[dict]) -> str:
    """`omaudit check`'s report: what changed on installed plugins since you
    last approved them. See functionality.md for the worked example."""
    out: list[str] = []
    unchanged = sum(1 for r in results if r["status"] == "unchanged")
    out.append(f"{len(results)} plugin(s) installed - {unchanged} unchanged")
    out.append("")

    for r in (r for r in results if r["status"] == "changed"):
        name = r.get("name") or r["id"]
        old_v = (r.get("baseline") or {}).get("version")
        new_v = r.get("version")
        version_txt = f"{old_v} -> {new_v}" if old_v and old_v != new_v else (new_v or "")
        out.append(f"  {name} {version_txt}".rstrip())
        for cap_id in r["added"]:
            cap = CAPABILITIES.get(cap_id)
            phrase = cap.install_phrase if cap else cap_id
            gap = " " * max(1, 22 - len(phrase))
            loc = r["evidence"].get(cap_id)
            loc_txt = f"{loc[0]}:{loc[1]}" if loc else ""
            out.append(f"    + {phrase}{gap}{loc_txt}".rstrip())
        approved_at = (r.get("baseline") or {}).get("recordedAt")
        out.append("")
        if approved_at:
            out.append(f"  These are new since you approved this plugin on {approved_at[:10]}.")
            out.append("")

    not_tracked = [r for r in results if r["status"] == "not-tracked"]
    first_party = [r for r in not_tracked if r.get("firstParty")]
    third_party = [r for r in not_tracked if not r.get("firstParty")]
    if third_party:
        out.append(f"{len(third_party)} plugin(s) have never been baselined: "
                   + ", ".join(r["id"] for r in third_party))
        out.append("  run `omaudit baseline <dir>` to start tracking them")
        out.append("")
    if first_party:
        out.append(f"{len(first_party)} first-party plugin(s) have never been baselined: "
                   + ", ".join(r["id"] for r in first_party))
        out.append("  run `omaudit baseline --builtin` to start tracking them")
        out.append("")

    return "\n".join(out)


GRADE_ORDER = ["A", "B", "C", "D", "F"]

# Extra half-line on the report-card key only — the letter + gloss already
# carry the rating; this is "why a shell plugin is allowed to be a C".
GRADE_HINT = {
    "A": "",
    "B": "a Process, a FileView",
    "C": "several reach-outs; normal for a shell",
    "D": "privilege, credentials, or a lot of both",
    "F": "",
}


def grade_legend() -> str:
    """The key that belongs on the report card. Not on `add` — that
    screen has ten seconds and the English capability lines already
    do the work."""
    lines = ["Grades"]
    for letter in GRADE_ORDER:
        hint = GRADE_HINT[letter]
        pad = " " * max(1, 24 - len(GRADE_GLOSS[letter]))
        extra = f"    {hint}" if hint else ""
        lines.append(f"  {letter}  {GRADE_GLOSS[letter]}{pad}"
                     f"{GRADE_RANGE[letter]:<6}{extra}".rstrip())
    lines.extend([
        "",
        "Score is how much the plugin can reach, not a count of files.",
        "First-party B/C is expected: the bar is supposed to exec helpers.",
        "Composition = a private source plus a network path off-box.",
        "See: omaudit help grades",
        "",
    ])
    return "\n".join(lines)


def report_card_json(results: list[dict], scanned_at: str,
                     omarchy_version: str | None) -> dict:
    grades = {g: 0 for g in GRADE_ORDER}
    for r in results:
        g = r.get("grade")
        if g in grades:
            grades[g] += 1
    return {
        "omauditSchemaVersion": SCHEMA_VERSION,
        "kind": "report-card",
        "scannedAt": scanned_at,
        "omarchyVersion": omarchy_version,
        "grades": grades,
        "unchanged": sum(1 for r in results if r["status"] == "unchanged"),
        "changed": sum(1 for r in results if r["status"] == "changed"),
        "notTracked": sum(1 for r in results if r["status"] == "not-tracked"),
        "compositionRisks": sum(1 for r in results if r.get("composition")),
        "plugins": results,
    }


def report_card(results: list[dict], scanned_at: str,
                omarchy_version: str | None) -> str:
    """A dated sheet of every plugin we already know about: grade,
    capabilities, and whether anything drifted since the baseline."""
    doc = report_card_json(results, scanned_at, omarchy_version)
    out: list[str] = []
    out.append("omaudit report card")
    head = scanned_at
    if omarchy_version:
        head += f"  Omarchy {omarchy_version}"
    out.append(head)
    out.append("")

    n = len(results)
    grade_bits = "  ".join(f"{g} {doc['grades'][g]}" for g in GRADE_ORDER)
    out.append(f"{n} plugin(s)   {grade_bits}")
    out.append(f"{doc['unchanged']} unchanged   {doc['changed']} changed   "
               f"{doc['notTracked']} not tracked")
    out.append(f"{doc['compositionRisks']} composition risk(s)")
    out.append("")

    if not results:
        out.append("no plugins found")
        out.append("")
        return "\n".join(out)

    user = [r for r in results if not r.get("firstParty")]
    builtin = [r for r in results if r.get("firstParty")]
    worst_first = lambda r: (-GRADE_ORDER.index(r["grade"]), r["id"])

    def _section(title: str, rows: list[dict]) -> None:
        if not rows:
            return
        out.append(title)
        for r in sorted(rows, key=worst_first):
            name = r["id"]
            version = r.get("version") or ""
            caps = ", ".join(r.get("observed") or []) or "-"
            mark = {"changed": "!", "not-tracked": "?"}.get(r["status"], " ")
            out.append(f"{mark}{r['grade']} {r.get('score', 0):>3}  "
                       f"{name:<32} {version:<8} {caps}")
        out.append("")

    _section("User", user)
    _section("First-party", builtin)

    changed = [r for r in results if r["status"] == "changed"]
    out.append("Drift")
    if not changed:
        out.append("  none")
    else:
        for r in changed:
            added = ", ".join(r.get("added") or [])
            out.append(f"  {r['id']}: + {added}")
    out.append("")

    risks = [r for r in results if r.get("composition")]
    out.append("Composition")
    if not risks:
        out.append("  none")
    else:
        for r in risks:
            for why in r["composition"]:
                out.append(f"  {r['id']}: {why.removeprefix('composition: ')}")
    out.append("")
    out.append(grade_legend().rstrip())
    out.append("")
    return "\n".join(out)


def human(doc: dict) -> str:
    out: list[str] = []
    p = doc["plugin"]
    g = doc["verdict"]["grade"]
    head = f"{p['id']}  {p.get('version') or ''}".strip()
    out.append("")
    out.append(_c("1", head))
    gloss = grade_gloss(g)
    gloss_txt = f" {gloss}" if gloss else ""
    out.append(f"{doc['filesScanned']} files scanned - grade "
               + _c("1;32" if g in "AB" else "1;33" if g == "C" else "1;31", g)
               + f"{gloss_txt} (score {doc['verdict']['score']})")
    out.append("")

    m = doc["manifest"]
    if m["errors"]:
        out.append(_c("1;31", "manifest errors"))
        for e in m["errors"]:
            out.append(f"  x {e}")
        out.append("")
    if m["warnings"]:
        out.append(_c("33", "manifest warnings"))
        for w in m["warnings"]:
            out.append(f"  ! {w}")
        out.append("")

    if not doc["capabilities"]:
        out.append(_c("32", "no capabilities detected - this plugin only draws."))
        out.append("")
        return "\n".join(out)

    out.append(_c("1", "capabilities"))
    for cap_id, info in doc["capabilities"].items():
        if info["observed"] and not info["declared"]:
            mark, colour = "x", "1;31"
            tag = "UNDECLARED"
        elif info["observed"]:
            mark, colour = "+", "32"
            tag = "declared"
        else:
            mark, colour = ".", "33"
            tag = "declared, not observed"
        scope = info["observedScope"] or info["declaredScope"]
        scope_txt = ("  -> " + ", ".join(scope[:6])) if scope else ""
        out.append(f"  {_c(colour, mark)} {cap_id:<20} {info['title']:<24} "
                   f"{_c('2', tag)}{scope_txt}")
        for ev in info["evidence"][:2]:
            out.append(_c("2", f"      {ev['file']}:{ev['line']}  {ev['why']}"))
    out.append("")

    if doc["unreadableArtifacts"]:
        out.append(_c("1;31", "unreadable artifacts"))
        for b in doc["unreadableArtifacts"]:
            out.append(f"  x {b}")
        out.append("")

    if doc["verdict"]["reasons"]:
        out.append(_c("1", "why this grade"))
        for r in doc["verdict"]["reasons"]:
            out.append(f"  - {r}")
        out.append("")

    if doc["undeclared"]:
        out.append(_c("1", "add this to manifest.json to declare intent"))
        block = json.dumps({"permissions": doc["suggestedPermissions"]}, indent=2)
        out.append("\n".join("  " + ln for ln in block.splitlines()))
        out.append("")

    return "\n".join(out)

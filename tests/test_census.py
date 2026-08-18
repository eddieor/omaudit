"""omaudit census: marketplace snapshot, not a live feed."""
import json
from pathlib import Path

from omaudit.cli import EXIT_OK, EXIT_USAGE, build_parser
from omaudit.registry import extract, write_listing


def _run(args_list):
    return build_parser().parse_args(["census", *args_list]).func(
        build_parser().parse_args(["census", *args_list])
    )


def _plugin(dir_: Path, plugin_id: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "manifest.json").write_text(
        json.dumps({
            "schemaVersion": 1, "id": plugin_id, "name": plugin_id,
            "version": "1.0.0", "kinds": ["bar-widget"],
            "entryPoints": {"barWidget": "BarWidget.qml"},
        }),
        encoding="utf-8",
    )
    (dir_ / "BarWidget.qml").write_text("Item { }\n", encoding="utf-8")
    return dir_


def test_extract_skips_retired_and_pins_commit():
    registry = {
        "retiredPluginIds": ["gone.one"],
        "sources": [
            {"repo": "https://github.com/a/keep",
             "listingValidatedCommit": "abc",
             "plugins": {"keep.one": {}},
             "automatedSecurityBaseline": {"outcome": "passed", "capabilities": []}},
            {"repo": "https://github.com/a/gone",
             "listingValidatedCommit": "def",
             "plugins": {"gone.one": {}}},
        ],
    }
    entries, stats = extract(registry)
    assert [e["repo"] for e in entries] == ["https://github.com/a/keep"]
    assert stats["sources"] == 1
    assert stats["withUpstreamBaseline"] == 1


def test_write_listing_reports_delta(tmp_path):
    entries = [
        {"repo": "https://github.com/a/one", "commit": "aaa",
         "pluginIds": [], "hasBaseline": False,
         "baselineCapabilities": [], "baselineFindings": []},
    ]
    stats = {"sources": 1, "withUpstreamBaseline": 0,
             "baselineOutcomes": {}, "baselineCapabilityFrequency": {},
             "baselineFindingCount": 0, "sourcesWithAnyBaselineCapability": 0}
    first = write_listing(tmp_path, entries, stats)
    assert first["first"]
    entries.append({"repo": "https://github.com/a/two", "commit": "bbb",
                    "pluginIds": [], "hasBaseline": False,
                    "baselineCapabilities": [], "baselineFindings": []})
    stats["sources"] = 2
    second = write_listing(tmp_path, entries, stats)
    assert not second["first"]
    assert any(s.endswith("@bbb") for s in second["added"])
    assert not second["removed"]


def test_census_local_writes_corpus(tmp_path, capsys):
    tree = tmp_path / "tree"
    _plugin(tree / "alpha", "test.alpha")
    _plugin(tree / "beta", "test.beta")
    out = tmp_path / "out"
    code = _run(["--local", str(tree), "--out", str(out)])
    assert code == EXIT_OK
    assert (out / "corpus.json").is_file()
    assert (out / "summary.txt").is_file()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["pluginsAudited"] == 2
    assert summary["grades"]["A"] == 2
    assert "2 plugins audited" in capsys.readouterr().out


def test_census_render_requires_corpus(tmp_path, capsys):
    code = _run(["--render", "--out", str(tmp_path / "empty")])
    assert code == EXIT_USAGE
    assert "no corpus" in capsys.readouterr().err


def test_census_fetch_only_uses_injected_registry(tmp_path, monkeypatch, capsys):
    from omaudit import registry as registry_mod

    def fake_fetch(url=""):
        return {"retiredPluginIds": [], "sources": [
            {"repo": "https://github.com/a/keep",
             "listingValidatedCommit": "abc123",
             "plugins": {"keep.one": {}},
             "automatedSecurityBaseline": {"outcome": "passed",
                                           "capabilities": [], "findings": []}},
        ]}

    monkeypatch.setattr(registry_mod, "fetch", fake_fetch)
    out = tmp_path / "c"
    code = _run(["--fetch-only", "--out", str(out)])
    assert code == EXIT_OK
    text = (out / "plugins.txt").read_text(encoding="utf-8")
    assert "keep@abc123" in text
    printed = capsys.readouterr().out
    assert "1 sources" in printed
    assert "first fetch" in printed

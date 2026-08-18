"""omaudit report: a dated report card of every tracked plugin."""
import json
from pathlib import Path

from omaudit.cli import EXIT_FINDINGS, EXIT_OK, build_parser
from omaudit.report import report_card


def _run(args_list):
    args = build_parser().parse_args(["report", *args_list])
    return args.func(args)


def _plugin(dir_: Path, plugin_id: str, qml: str, *, first_party: bool = False) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "manifest.json").write_text(
        json.dumps({
            "schemaVersion": 1, "id": plugin_id, "name": plugin_id,
            "version": "1.0.0", "kinds": ["bar-widget"],
            "entryPoints": {"barWidget": "BarWidget.qml"},
        }),
        encoding="utf-8",
    )
    (dir_ / "BarWidget.qml").write_text(qml, encoding="utf-8")
    return dir_


def _baseline(dir_: Path, plugin_id: str, accepted: list) -> None:
    (dir_ / ".omaudit-baseline.json").write_text(json.dumps({
        "omauditSchemaVersion": 1, "plugin": plugin_id, "version": "1.0.0",
        "recordedAt": "2026-07-01T00:00:00+00:00", "grade": "A",
        "acceptedCapabilities": accepted, "commit": None, "note": "",
    }), encoding="utf-8")


def test_report_lists_grades_and_writes_file(tmp_path, capsys):
    user = tmp_path / "user"
    _plugin(user / "clean", "eddieor.clean", "Item { }")
    _baseline(user / "clean", "eddieor.clean", [])
    busy = _plugin(user / "busy", "eddieor.busy",
                   'Process { command: ["sensors"] }\n')
    _baseline(busy, "eddieor.busy", ["process.exec"])

    out = tmp_path / "card.txt"
    code = _run(["--dir", str(user), "--out", str(out)])
    assert code == EXIT_OK
    printed = capsys.readouterr().out
    assert "omaudit report card" in printed
    assert "eddieor.clean" in printed
    assert "eddieor.busy" in printed
    assert "process.exec" in printed
    assert "Drift" in printed
    assert "none" in printed
    assert f"wrote {out}" in printed
    saved = out.read_text(encoding="utf-8")
    assert "eddieor.clean" in saved
    assert "A 2" in saved or "A     1" in saved or "A 1" in saved


def test_report_flags_drift(tmp_path, capsys):
    d = _plugin(tmp_path / "p", "test.drifted",
                'Quickshell.clipboardText = "x"\n')
    _baseline(d, "test.drifted", [])
    code = _run(["--dir", str(tmp_path), "--out", str(tmp_path / "card.txt")])
    assert code == EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "test.drifted: + clipboard.write" in out
    assert "1 changed" in out


def test_report_json_shape(tmp_path, capsys):
    _plugin(tmp_path / "p", "test.clean", "Item { }")
    code = _run(["--dir", str(tmp_path), "--json", "--out", str(tmp_path / "card.json")])
    assert code == EXIT_OK
    # stdout is JSON then "wrote ..."
    raw = capsys.readouterr().out
    json_text = raw[:raw.rfind("wrote")].strip()
    doc = json.loads(json_text)
    assert doc["kind"] == "report-card"
    assert doc["grades"]["A"] == 1
    assert doc["plugins"][0]["id"] == "test.clean"
    assert doc["plugins"][0]["status"] == "not-tracked"
    assert doc["notTracked"] == 1


def test_report_defaults_to_all(tmp_path, monkeypatch, capsys):
    from omaudit import paths as paths_mod

    user = tmp_path / "user"
    builtin = tmp_path / "builtin"
    _plugin(user / "mine", "eddieor.mine", "Item { }")
    _plugin(builtin / "clock", "omarchy.clock", "Item { }")
    monkeypatch.setattr(paths_mod, "user_plugins_dir", lambda: user)
    monkeypatch.setattr(paths_mod, "builtin_plugins_dir", lambda: builtin)
    monkeypatch.setattr(paths_mod, "report_card_path",
                        lambda: tmp_path / "default-card.txt")

    code = _run([])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "eddieor.mine" in out
    assert "omarchy.clock" in out
    assert "User" in out
    assert "First-party" in out
    assert (tmp_path / "default-card.txt").is_file()


def test_report_card_renderer_sorts_worst_first():
    text = report_card([
        {"id": "a.ok", "grade": "A", "score": 0, "status": "unchanged",
         "observed": [], "firstParty": False, "version": "1", "composition": []},
        {"id": "z.bad", "grade": "D", "score": 16, "status": "unchanged",
         "observed": ["process.privileged"], "firstParty": False,
         "version": "1", "composition": []},
    ], "2026-08-18T00:00:00+00:00", None)
    assert text.index("z.bad") < text.index("a.ok")
    assert "Grades" in text
    assert "know what you're doing" in text
    assert "First-party B/C is expected" in text
    assert "omaudit help grades" in text

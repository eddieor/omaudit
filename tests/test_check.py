"""omaudit check: drift detection against a previously accepted baseline."""
import json
from pathlib import Path

from omaudit import cli
from omaudit.cli import EXIT_FINDINGS, EXIT_OK, build_parser


def _run_check(args_list):
    args = build_parser().parse_args(["check", *args_list])
    return args.func(args)


def _make_plugin(dir_: Path, plugin_id: str, qml_body: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "manifest.json").write_text(
        json.dumps({
            "schemaVersion": 1, "id": plugin_id, "name": plugin_id,
            "version": "1.0.0", "kinds": ["bar-widget"],
            "entryPoints": {"barWidget": "BarWidget.qml"},
        }),
        encoding="utf-8",
    )
    (dir_ / "BarWidget.qml").write_text(qml_body, encoding="utf-8")
    return dir_


def _write_baseline(dir_: Path, plugin_id: str, accepted: list, **extra) -> None:
    snapshot = {
        "omauditSchemaVersion": 1, "plugin": plugin_id, "version": "1.0.0",
        "recordedAt": "2026-07-01T00:00:00+00:00", "grade": "A",
        "acceptedCapabilities": accepted, "commit": None, "note": "",
    }
    snapshot.update(extra)
    (dir_ / ".omaudit-baseline.json").write_text(json.dumps(snapshot), encoding="utf-8")


def test_no_plugins_directory(tmp_path, capsys):
    code = _run_check(["--dir", str(tmp_path / "nowhere")])
    assert code == EXIT_OK
    assert "no plugins directory" in capsys.readouterr().out


def test_not_tracked_is_reported_not_silently_skipped(tmp_path, capsys):
    _make_plugin(tmp_path / "untracked", "test.untracked", "BarWidget { }")
    code = _run_check(["--dir", str(tmp_path), "--json"])
    assert code == EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert results[0]["status"] == "not-tracked"


def test_unchanged_plugin_produces_no_findings(tmp_path, capsys):
    d = _make_plugin(tmp_path / "clean", "test.clean",
                      'Process { command: ["sensors"] }')
    _write_baseline(d, "test.clean", ["process.exec"])
    code = _run_check(["--dir", str(tmp_path), "--json"])
    assert code == EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert results[0]["status"] == "unchanged"
    assert results[0]["added"] == []


def test_changed_plugin_reports_new_capability_with_evidence(tmp_path, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Process { command: ["sensors"] }\n'
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", ["process.exec"])  # clipboard.write not accepted

    code = _run_check(["--dir", str(tmp_path), "--yes"])
    assert code == EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "writes the clipboard" in out
    assert "BarWidget.qml:2" in out


def test_accept_resolves_and_rewrites_baseline(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [])

    monkeypatch.setattr("builtins.input", lambda prompt: "a")
    code = _run_check(["--dir", str(tmp_path)])
    assert code == EXIT_OK
    assert "accepted" in capsys.readouterr().out

    baseline = json.loads((d / ".omaudit-baseline.json").read_text(encoding="utf-8"))
    assert "clipboard.write" in baseline["acceptedCapabilities"]

    # re-run: should now be unchanged
    code2 = _run_check(["--dir", str(tmp_path), "--json"])
    assert code2 == EXIT_OK
    assert json.loads(capsys.readouterr().out)[0]["status"] == "unchanged"


def test_skip_leaves_it_unresolved(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [])

    monkeypatch.setattr("builtins.input", lambda prompt: "s")
    code = _run_check(["--dir", str(tmp_path)])
    assert code == EXIT_FINDINGS


def test_remove_action_shells_out_and_resolves(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [])

    calls = []
    monkeypatch.setattr(cli.subprocess, "run",
                         lambda cmd, **k: calls.append(cmd) or _Ok())
    monkeypatch.setattr("builtins.input", lambda prompt: "r")

    code = _run_check(["--dir", str(tmp_path)])
    assert code == EXIT_OK
    assert calls == [["omarchy", "plugin", "remove", "test.drifted", "--yes"]]
    assert "removed test.drifted" in capsys.readouterr().out


def test_diff_is_non_terminal_then_skip(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [], commit="abc1234")

    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    answers = iter(["d", "s"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    code = _run_check(["--dir", str(tmp_path)])
    assert code == EXIT_FINDINGS  # skipped after the diff, still unresolved
    assert calls == [["git", "-C", str(d), "diff", "abc1234"]]


def test_pin_without_recorded_commit_is_graceful(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [])  # commit: None

    def fail_if_called(*a, **k):
        raise AssertionError("git should not be invoked without a recorded commit")
    monkeypatch.setattr(cli.subprocess, "run", fail_if_called)
    monkeypatch.setattr("builtins.input", lambda prompt: "p")

    code = _run_check(["--dir", str(tmp_path)])
    assert code == EXIT_FINDINGS
    assert "can't pin: no commit was recorded" in capsys.readouterr().out


def test_pin_with_commit_checks_out_and_resolves(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [], commit="abc1234")

    calls = []
    monkeypatch.setattr(cli.subprocess, "run",
                         lambda cmd, **k: calls.append(cmd) or _Ok())
    answers = iter(["p", "y"])  # menu choice, then the roll-back confirmation
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    code = _run_check(["--dir", str(tmp_path)])
    assert code == EXIT_OK
    assert calls == [["git", "-C", str(d), "checkout", "--quiet", "abc1234"]]
    assert "pinned to abc1234" in capsys.readouterr().out


def test_json_never_prompts(tmp_path, monkeypatch, capsys):
    d = _make_plugin(tmp_path / "drifted", "test.drifted",
                      'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "test.drifted", [])

    def fail_if_called(prompt):
        raise AssertionError("--json must not prompt")
    monkeypatch.setattr("builtins.input", fail_if_called)

    code = _run_check(["--dir", str(tmp_path), "--json"])
    assert code == EXIT_FINDINGS
    results = json.loads(capsys.readouterr().out)
    assert results[0]["status"] == "changed"


def test_nested_plugin_tree_is_discovered(tmp_path, capsys):
    """First-party layout: top-level plugins next to panels/<id>/."""
    _make_plugin(tmp_path / "clipboard", "omarchy.clipboard", "Item { }")
    _make_plugin(tmp_path / "panels" / "weather", "omarchy.weather", "Item { }")
    code = _run_check(["--dir", str(tmp_path), "--json"])
    assert code == EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in results} == {"omarchy.clipboard", "omarchy.weather"}
    assert all(r["firstParty"] for r in results)


def test_unwritable_plugin_uses_baseline_store(tmp_path, monkeypatch, capsys):
    from omaudit import paths as paths_mod

    plugin = _make_plugin(tmp_path / "sys" / "tailscale", "omarchy.tailscale",
                          'Process { command: ["tailscale"] }\n')
    store = tmp_path / "xdg" / "omaudit" / "baselines"
    monkeypatch.setattr(paths_mod, "baseline_store_dir", lambda: store)
    monkeypatch.setattr(paths_mod, "sidecar_writable", lambda _p: False)
    monkeypatch.setattr(paths_mod, "is_builtin", lambda _p: True)
    monkeypatch.setattr(paths_mod, "omarchy_version", lambda: "4.0.0.test")

    args = build_parser().parse_args(["baseline", str(plugin)])
    assert args.func(args) == EXIT_OK
    capsys.readouterr()
    dest = store / "omarchy.tailscale.json"
    assert dest.is_file()
    snap = json.loads(dest.read_text(encoding="utf-8"))
    assert snap["acceptedCapabilities"] == ["process.exec"]
    assert snap["source"] == "builtin"
    assert snap["omarchyVersion"] == "4.0.0.test"
    assert not (plugin / ".omaudit-baseline.json").exists()

    code = _run_check(["--dir", str(tmp_path / "sys"), "--json"])
    assert code == EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert results[0]["id"] == "omarchy.tailscale"
    assert results[0]["status"] == "unchanged"


def test_baseline_builtin_snapshots_the_tree(tmp_path, monkeypatch, capsys):
    from omaudit import paths as paths_mod

    tree = tmp_path / "omarchy" / "shell" / "plugins"
    _make_plugin(tree / "clock", "omarchy.clock", "Item { }")
    _make_plugin(tree / "panels" / "weather", "omarchy.weather",
                 'Process { command: ["sensors"] }\n')
    store = tmp_path / "store"
    monkeypatch.setattr(paths_mod, "builtin_plugins_dir", lambda: tree)
    monkeypatch.setattr(paths_mod, "baseline_store_dir", lambda: store)
    monkeypatch.setattr(paths_mod, "sidecar_writable", lambda _p: False)
    monkeypatch.setattr(paths_mod, "is_builtin", lambda _p: True)
    monkeypatch.setattr(paths_mod, "omarchy_version", lambda: "4.0.0.test")

    args = build_parser().parse_args(["baseline", "--builtin"])
    assert args.func(args) == EXIT_OK
    assert (store / "omarchy.clock.json").is_file()
    weather = json.loads((store / "omarchy.weather.json").read_text(encoding="utf-8"))
    assert weather["acceptedCapabilities"] == ["process.exec"]
    assert weather["source"] == "builtin"
    assert "baselined 2 plugin(s)" in capsys.readouterr().out


def test_check_builtin_flag_uses_omarchy_tree(tmp_path, monkeypatch, capsys):
    from omaudit import paths as paths_mod

    tree = tmp_path / "omarchy" / "shell" / "plugins"
    _make_plugin(tree / "clock", "omarchy.clock", "Item { }")
    _make_plugin(tree / "panels" / "weather", "omarchy.weather", "Item { }")
    monkeypatch.setattr(paths_mod, "builtin_plugins_dir", lambda: tree)
    monkeypatch.setattr(paths_mod, "user_plugins_dir",
                        lambda: tmp_path / "nowhere-user")

    code = _run_check(["--builtin", "--json"])
    assert code == EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in results} == {"omarchy.clock", "omarchy.weather"}


def test_check_all_combines_user_and_builtin(tmp_path, monkeypatch, capsys):
    from omaudit import paths as paths_mod

    user = tmp_path / "user"
    builtin = tmp_path / "builtin"
    _make_plugin(user / "eddieor.active-app", "eddieor.active-app", "Item { }")
    _make_plugin(builtin / "clock", "omarchy.clock", "Item { }")
    monkeypatch.setattr(paths_mod, "user_plugins_dir", lambda: user)
    monkeypatch.setattr(paths_mod, "builtin_plugins_dir", lambda: builtin)

    code = _run_check(["--all", "--json"])
    assert code == EXIT_OK
    results = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in results} == {"eddieor.active-app", "omarchy.clock"}


def test_cannot_pin_or_remove_first_party(tmp_path, monkeypatch, capsys):
    from omaudit import paths as paths_mod

    d = _make_plugin(tmp_path / "tailscale", "omarchy.tailscale",
                     'Quickshell.clipboardText = "x"\n')
    _write_baseline(d, "omarchy.tailscale", [])
    monkeypatch.setattr(paths_mod, "is_builtin", lambda _p: True)

    def fail_if_run(*a, **k):
        raise AssertionError("must not shell out for first-party pin/remove")
    monkeypatch.setattr(cli.subprocess, "run", fail_if_run)

    monkeypatch.setattr("builtins.input", lambda prompt: "p")
    assert _run_check(["--dir", str(tmp_path)]) == EXIT_FINDINGS
    assert "can't pin: first-party" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt: "r")
    assert _run_check(["--dir", str(tmp_path)]) == EXIT_FINDINGS
    assert "can't remove: first-party" in capsys.readouterr().out


class _Ok:
    returncode = 0

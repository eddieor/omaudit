"""Rule extraction edge cases against small inline plugins."""
from pathlib import Path

from omaudit.cli import _audit


def _plugin(tmp_path: Path, qml: str) -> Path:
    d = tmp_path / "p"
    d.mkdir()
    (d / "manifest.json").write_text(
        '{"schemaVersion": 1, "id": "test.rules", "name": "rules", '
        '"version": "1.0.0", "kinds": ["bar-widget"], '
        '"entryPoints": {"barWidget": "BarWidget.qml"}}',
        encoding="utf-8",
    )
    (d / "BarWidget.qml").write_text(qml, encoding="utf-8")
    return d


def test_quickshell_env_is_not_fs_sensitive(tmp_path):
    doc = _audit(_plugin(tmp_path, 'Item { path: Quickshell.env("HOME") + "/foo" }\n'))
    assert not doc["capabilities"].get("fs.sensitive", {}).get("observed")


def test_dotenv_file_scope_is_clean(tmp_path):
    doc = _audit(_plugin(
        tmp_path,
        'FileView { path: Quickshell.env("HOME") + "/.config/app/.env" }\n',
    ))
    assert doc["capabilities"]["fs.sensitive"]["observed"]
    assert doc["capabilities"]["fs.sensitive"]["observedScope"] == [".env"]


def test_exec_detached_ternary_extracts_binary_not_qml_id(tmp_path):
    doc = _audit(_plugin(
        tmp_path,
        'Item {\n'
        '  function go() {\n'
        '    Quickshell.execDetached(root.reminderCount > 0 '
        '? ["omarchy-reminder", "show"] : ["omarchy-reminder", "-i"])\n'
        '  }\n'
        '}\n',
    ))
    scope = doc["capabilities"]["process.exec"]["observedScope"]
    assert "omarchy-reminder" in scope
    assert "root.reminderCount" not in scope


def test_command_assignment_extracts_binary(tmp_path):
    doc = _audit(_plugin(
        tmp_path,
        'Process { id: p }\n'
        'Item { Component.onCompleted: p.command = ["curl", "-s", url] }\n',
    ))
    assert "curl" in doc["capabilities"]["process.exec"]["observedScope"]
    assert doc["capabilities"]["net.outbound"]["observed"]

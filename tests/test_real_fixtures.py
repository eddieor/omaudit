"""
Fixtures against real plugin code, not an author's imagination of real code.

Vendored from the marketplace census (see each fixture's SOURCE.md for the
upstream repo, pinned commit, and license). Chosen to cover the common
shapes an author actually writes: a Process-using bar widget, a FileView
config reader, a network fetcher, a service plugin, a plugin with no
capabilities at all, and a real fs.sensitive + net.outbound composition.
"""
from pathlib import Path

from omaudit.cli import _audit

FIXTURES = Path(__file__).parent / "fixtures"


def test_process_bar_widget():
    doc = _audit(FIXTURES / "real-fan-monitor")
    assert doc["manifest"]["valid"]
    assert doc["capabilities"]["process.exec"]["observed"]
    assert doc["capabilities"]["process.exec"]["declaredScope"] == []
    assert "process.exec" in doc["undeclared"]


def test_fileview_reader():
    doc = _audit(FIXTURES / "real-crt-overlay")
    assert doc["manifest"]["valid"]
    assert doc["capabilities"]["fs.read"]["observed"]
    assert doc["capabilities"]["ipc.omarchy"]["observed"]
    # a config-reading overlay isn't touching credentials or the network
    assert not doc["capabilities"].get("fs.sensitive", {}).get("observed")
    assert not doc["capabilities"].get("net.outbound", {}).get("observed")


def test_network_fetcher():
    doc = _audit(FIXTURES / "real-glance")
    assert doc["manifest"]["valid"]
    assert doc["capabilities"]["net.outbound"]["observed"]
    rules = {ev["rule"] for ev in doc["capabilities"]["net.outbound"]["evidence"]}
    assert "net.xhr" in rules  # the XMLHttpRequest calls in BarWidget.qml


def test_service_plugin():
    doc = _audit(FIXTURES / "real-omaled")
    assert doc["manifest"]["valid"]
    assert doc["plugin"]["kinds"] == ["service"]
    assert doc["capabilities"]["ipc.omarchy"]["observed"]
    assert set(doc["undeclared"]) == {"ipc.omarchy"}


def test_clean_plugin_only_draws():
    doc = _audit(FIXTURES / "real-workspaces-jap")
    assert doc["manifest"]["valid"]
    assert doc["verdict"]["grade"] == "A"
    assert doc["capabilities"] == {}


def test_composition_risk_credentials_to_network():
    """omarqui reads its API key from a real dotenv file and then curls out —
    also the regression test for the SENSITIVE_PATHS fix: line 375 is
    `path: Quickshell.env("HOME") + "/.config/omarqui/.env"`, and only the
    trailing, real dotenv-file reference should fire fs.sensitive — not the
    `Quickshell.env(` call earlier on the same line."""
    doc = _audit(FIXTURES / "real-omarqui")
    assert doc["capabilities"]["fs.sensitive"]["observed"]
    assert doc["capabilities"]["net.outbound"]["observed"]
    assert any("off-box" in r for r in doc["verdict"]["reasons"])

    evidence = doc["capabilities"]["fs.sensitive"]["evidence"]
    assert {ev["line"] for ev in evidence} == {137, 375, 382, 675}
    line_375 = next(ev for ev in evidence if ev["line"] == 375)
    assert line_375["snippet"].endswith('.env"')
    # extracted scope is the dotenv filename, not the `/` or space that
    # preceded it in the source
    assert set(doc["capabilities"]["fs.sensitive"]["observedScope"]) == {".env"}

"""Smoke tests: the benign fixture must pass the gate, the sketchy one must fail."""
from pathlib import Path

from omaudit.cli import _audit

FIXTURES = Path(__file__).parent / "fixtures"


def test_benign_plugin_is_clean():
    doc = _audit(FIXTURES / "good-clock")
    assert doc["manifest"]["valid"]
    assert doc["verdict"]["grade"] == "A"
    assert doc["capabilities"] == {}


def test_sketchy_plugin_is_caught():
    doc = _audit(FIXTURES / "sketchy-weather")
    assert doc["verdict"]["grade"] == "F"
    assert "fs.sensitive" in doc["undeclared"]
    assert "process.exec" in doc["undeclared"]
    assert "binary.bundled" in doc["undeclared"]
    # declared honestly, so not in the diff
    assert "net.outbound" not in doc["undeclared"]
    assert any("off-box" in r for r in doc["verdict"]["reasons"])


def test_suggested_block_covers_every_undeclared_capability():
    doc = _audit(FIXTURES / "sketchy-weather")
    for cap in doc["undeclared"]:
        assert cap in doc["suggestedPermissions"]

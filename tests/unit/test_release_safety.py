import importlib.util
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    spec = importlib.util.spec_from_file_location("release_helper", ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scanner_detects_secrets_without_echoing_them(tmp_path):
    scanner = load("scripts/check_release.py")
    secret = "gh" + "p_" + "a" * 40
    (tmp_path / "sample.txt").write_text(secret)
    failures = scanner.scan(tmp_path)
    assert len(failures) == 1
    assert secret not in failures[0]
    assert "sample.txt:1:" in failures[0]


def test_scanner_itself_is_not_exempt_from_secret_checks(tmp_path):
    scanner = load("scripts/check_release.py")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/check_release.py").write_text("AK" + "IA" + "A" * 16)
    assert scanner.scan(tmp_path)


def test_scanner_rejects_private_hosts_and_binary_assets(tmp_path):
    scanner = load("scripts/check_release.py")
    (tmp_path / "sample.txt").write_text("https://deployment." + "dotmatics.net")
    (tmp_path / "asset.bin").write_bytes(bytes([255]))
    assert len(scanner.scan(tmp_path)) == 2


def test_scanner_checks_archives_and_allows_reviewed_attribution(tmp_path):
    scanner = load("scripts/check_release.py")
    archive = tmp_path / "package.whl"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("pkg/licenses/LICENSE", next(iter(scanner.ALLOW["LICENSE"])))
    assert scanner.scan(archive) == []
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr("pkg/key.txt", "AK" + "IA" + "A" * 16)
    assert len(scanner.scan(archive)) == 1


def test_live_cleanup_refuses_unowned_ids(monkeypatch):
    helper = load("tests/integration/conftest.py")
    monkeypatch.setenv("DOTMATICS_TEST_MUTATIONS", "isolated-test-instance")
    client = Mock()
    client.create_layout.return_value = {"id": 123}
    inventory = helper.OwnedInventory(client)
    with pytest.raises(ValueError, match="not created"):
        inventory.delete_layout(456)
    client.delete_layout.assert_not_called()
    inventory.create_layout({"name": "test"})
    inventory.delete_layout(123)
    client.delete_layout.assert_called_once_with(123)
    inventory.cleanup()
    client.delete_layout.assert_called_once_with(123)


def test_live_cleanup_tracks_only_created_records(monkeypatch):
    helper = load("tests/integration/conftest.py")
    monkeypatch.setenv("DOTMATICS_TEST_MUTATIONS", "isolated-test-instance")
    client = Mock()
    client.create_layout.return_value = {"data": {"id": 123}}
    inventory = helper.OwnedInventory(client)
    inventory.create_layout({"name": "test"})
    inventory.cleanup()
    client.delete_layout.assert_called_once_with(123)

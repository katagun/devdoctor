"""Tests for the shared on-disk layout helpers in ``devdoctor._storage``."""

from __future__ import annotations

from pathlib import Path

import pytest

from devdoctor._storage import default_data_dir


def test_default_data_dir_uses_devdoctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / "devdoctor"


def test_default_data_dir_falls_back_to_legacy_diskdoctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    legacy = tmp_path / "diskdoctor"
    legacy.mkdir()
    assert default_data_dir() == legacy


def test_default_data_dir_prefers_new_dir_over_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "diskdoctor").mkdir()
    (tmp_path / "devdoctor").mkdir()
    assert default_data_dir() == tmp_path / "devdoctor"

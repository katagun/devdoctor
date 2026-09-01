from __future__ import annotations

from pathlib import Path

from devdoctor.config import (
    AppSettings,
    default_app_settings,
    default_config_path,
    load_app_settings,
    save_app_settings,
)


def test_default_app_settings_use_isolated_xdg_dirs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    settings = default_app_settings()

    assert settings.storage_backend == "filesystem"
    assert settings.data_dir == tmp_path / "data" / "devdoctor"
    assert settings.sqlite_path == tmp_path / "data" / "devdoctor" / "devdoctor.sqlite3"
    assert default_config_path() == tmp_path / "config" / "devdoctor" / "config.json"


def test_save_and_load_app_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    expected = AppSettings(
        storage_backend="sqlite",
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "devdoctor.sqlite3",
    )

    save_app_settings(expected, path)

    assert load_app_settings(path) == expected


def test_load_app_settings_ignores_invalid_backend(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"storage_backend": "postgres"}')

    assert load_app_settings(path).storage_backend == "filesystem"

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from diskdoctor._storage import default_data_dir

logger = logging.getLogger(__name__)

StorageBackendName = Literal["filesystem", "sqlite"]
_BACKENDS: set[str] = {"filesystem", "sqlite"}


@dataclass(frozen=True)
class AppSettings:
    storage_backend: StorageBackendName
    data_dir: Path
    sqlite_path: Path


def default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "devdoctor"


def default_config_path() -> Path:
    return default_config_dir() / "config.json"


def default_app_settings() -> AppSettings:
    data_dir = default_data_dir()
    return AppSettings(
        storage_backend="filesystem",
        data_dir=data_dir,
        sqlite_path=data_dir / "devdoctor.sqlite3",
    )


def load_app_settings(path: Path | None = None) -> AppSettings:
    target = path or default_config_path()
    defaults = default_app_settings()
    if not target.is_file():
        return defaults
    try:
        parsed = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "config: could not read/parse %s (%s); falling back to defaults", target, exc
        )
        return defaults
    if not isinstance(parsed, dict):
        logger.warning("config: %s is not a JSON object; falling back to defaults", target)
        return defaults

    backend = parsed.get("storage_backend")
    storage_backend: StorageBackendName = defaults.storage_backend
    if isinstance(backend, str) and backend in _BACKENDS:
        storage_backend = cast(StorageBackendName, backend)
    data_dir = _path_value(parsed.get("data_dir"), defaults.data_dir)
    sqlite_path = _path_value(parsed.get("sqlite_path"), data_dir / "devdoctor.sqlite3")
    return AppSettings(
        storage_backend=storage_backend,
        data_dir=data_dir,
        sqlite_path=sqlite_path,
    )


def save_app_settings(settings: AppSettings, path: Path | None = None) -> None:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "storage_backend": settings.storage_backend,
        "data_dir": str(settings.data_dir),
        "sqlite_path": str(settings.sqlite_path),
    }
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def update_app_settings(
    settings: AppSettings,
    *,
    storage_backend: StorageBackendName | None = None,
    data_dir: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> AppSettings:
    next_data_dir = _path_value(data_dir, settings.data_dir)
    return replace(
        settings,
        storage_backend=storage_backend or settings.storage_backend,
        data_dir=next_data_dir,
        sqlite_path=_path_value(sqlite_path, next_data_dir / "devdoctor.sqlite3")
        if sqlite_path is not None
        else settings.sqlite_path,
    )


def _path_value(value: object, fallback: Path) -> Path:
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return fallback

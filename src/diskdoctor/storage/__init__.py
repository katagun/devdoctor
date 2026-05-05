from __future__ import annotations

from diskdoctor.config import AppSettings, load_app_settings
from diskdoctor.storage.base import StorageBackend
from diskdoctor.storage.filesystem import FilesystemStorage
from diskdoctor.storage.sqlite import SQLiteStorage


def build_storage(settings: AppSettings | None = None) -> StorageBackend:
    resolved = settings or load_app_settings()
    if resolved.storage_backend == "sqlite":
        return SQLiteStorage(resolved.sqlite_path)
    return FilesystemStorage(data_dir=resolved.data_dir)


__all__ = [
    "FilesystemStorage",
    "SQLiteStorage",
    "StorageBackend",
    "build_storage",
]

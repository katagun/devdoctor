from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from diskdoctor.config import AppSettings, save_app_settings, update_app_settings
from diskdoctor.storage import FilesystemStorage, SQLiteStorage, build_storage
from diskdoctor.web.models import AppSettingsInfo, AppSettingsPatch

router = APIRouter(prefix="/api")


@router.get("/settings", response_model=AppSettingsInfo)
def get_settings(request: Request) -> AppSettingsInfo:
    return _settings_to_info(request.app.state.app_settings)


@router.patch("/settings", response_model=AppSettingsInfo)
def patch_settings(body: AppSettingsPatch, request: Request) -> AppSettingsInfo:
    current: AppSettings = request.app.state.app_settings
    next_settings = update_app_settings(
        current,
        storage_backend=body.storage_backend,
        data_dir=body.data_dir,
        sqlite_path=body.sqlite_path,
    )

    try:
        next_storage = build_storage(next_settings)
        if isinstance(next_storage, SQLiteStorage):
            next_storage.import_filesystem(FilesystemStorage(data_dir=next_settings.data_dir))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"could not initialize {next_settings.storage_backend} storage: {exc}",
        ) from exc

    save_app_settings(next_settings)
    request.app.state.app_settings = next_settings
    request.app.state.storage = next_storage
    return _settings_to_info(next_settings)


def _settings_to_info(settings: AppSettings) -> AppSettingsInfo:
    return AppSettingsInfo(
        storage_backend=settings.storage_backend,
        data_dir=str(settings.data_dir),
        sqlite_path=str(settings.sqlite_path),
        available_backends=["filesystem", "sqlite"],
    )

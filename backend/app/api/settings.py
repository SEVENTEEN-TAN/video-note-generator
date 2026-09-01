from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..settings import (
    SettingsStorageError,
    UserSettings,
    UserSettingsUpdate,
    clear_user_settings,
    load_user_settings,
    save_user_settings,
)


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
def get_settings() -> UserSettings:
    try:
        return load_user_settings(strict=True)
    except SettingsStorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("", response_model=UserSettings)
def update_settings(update: UserSettingsUpdate) -> UserSettings:
    try:
        return save_user_settings(update.model_dump(mode="json", exclude_none=True))
    except SettingsStorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("", response_model=UserSettings)
def delete_settings() -> UserSettings:
    try:
        return clear_user_settings()
    except SettingsStorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

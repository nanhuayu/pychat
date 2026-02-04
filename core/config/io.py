from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.config.schema import AppConfig, ProjectConfig


_APP_CACHE: AppConfig | None = None


def _get_app_data_dir() -> Path:
    app_data = os.getenv("APPDATA", os.path.expanduser("~"))
    return Path(app_data) / "PyChat"


def get_settings_path() -> Path:
    return _get_app_data_dir() / "settings.json"


def get_user_modes_json_path() -> Path:
    """User-level modes config path.

    Stored next to settings.json so modes are global across all projects.
    """
    return _get_app_data_dir() / "modes.json"


def load_user_modes_dict() -> Dict[str, Any]:
    path = get_user_modes_json_path()
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def save_user_modes_dict(data: Dict[str, Any]) -> bool:
    path = get_user_modes_json_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def load_settings_dict() -> Dict[str, Any]:
    path = get_settings_path()
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def save_settings_dict(settings: Dict[str, Any]) -> bool:
    path = get_settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def load_app_config(*, refresh: bool = False) -> AppConfig:
    global _APP_CACHE
    if refresh or _APP_CACHE is None:
        _APP_CACHE = AppConfig.from_dict(load_settings_dict())
    return _APP_CACHE


def set_cached_app_config(app_config: AppConfig | None) -> None:
    global _APP_CACHE
    _APP_CACHE = app_config


def set_cached_settings_dict(settings: Dict[str, Any] | None) -> None:
    set_cached_app_config(AppConfig.from_dict(settings or {}))


def save_app_config(app_config: AppConfig, *, refresh_cache: bool = True) -> bool:
    ok = save_settings_dict(app_config.to_dict())
    if refresh_cache and ok:
        set_cached_app_config(app_config)
    return ok


def get_modes_json_path(work_dir: str) -> Optional[Path]:
    wd = (work_dir or "").strip()
    if not wd:
        return None
    try:
        p = Path(wd)
    except Exception:
        return None
    if not p.exists() or not p.is_dir():
        return None
    return p / "modes.json"


def load_project_config(work_dir: str) -> ProjectConfig:
    p = get_modes_json_path(work_dir)
    if not p or not p.exists() or not p.is_file():
        return ProjectConfig(work_dir=str(work_dir or ""), modes=[])

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raw = None

    return ProjectConfig.from_modes_json(str(work_dir or ""), raw)


def save_project_config(project: ProjectConfig) -> bool:
    p = get_modes_json_path(project.work_dir)
    if not p:
        return False

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(project.to_modes_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

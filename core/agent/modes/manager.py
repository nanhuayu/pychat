from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from core.config.io import get_user_modes_json_path
from core.agent.modes.defaults import get_default_modes
from core.agent.modes.types import GroupOptions, ModeConfig, normalize_mode_slug


class ModeManager:
    """Loads and provides mode configs.

    Design goals:
    - Simple: built-in defaults first
    - Extensible: optional user-level modes.json in APPDATA/PyChat
    """

    def __init__(self, work_dir: str | None = None):
        self.work_dir = str(work_dir or ".")
        self._cache: Optional[Dict[str, ModeConfig]] = None

    def list_modes(self) -> List[ModeConfig]:
        self._ensure_loaded()
        assert self._cache is not None
        return list(self._cache.values())

    def get(self, slug: str) -> ModeConfig:
        self._ensure_loaded()
        assert self._cache is not None
        key = normalize_mode_slug(slug)
        return self._cache.get(key) or self._cache["chat"]

    def _ensure_loaded(self) -> None:
        if self._cache is not None:
            return

        modes: Dict[str, ModeConfig] = {m.slug: m for m in get_default_modes()}

        # Optional user override
        try:
            user_path = get_user_modes_json_path()
            if user_path.exists() and user_path.is_file():
                loaded = self._load_modes_json(user_path, source="global")
                for m in loaded:
                    modes[m.slug] = m
        except Exception:
            pass

        # Ensure required base modes exist
        if "chat" not in modes:
            modes["chat"] = get_default_modes()[0]

        self._cache = modes

    def _load_modes_json(self, path: Path, *, source: str) -> List[ModeConfig]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("modes") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []

        out: List[ModeConfig] = []
        for it in items:
            if not isinstance(it, dict):
                continue

            slug = normalize_mode_slug(str(it.get("slug", "")))
            name = str(it.get("name", slug))
            role_definition = str(it.get("roleDefinition") or it.get("role_definition") or "").strip()
            if not slug:
                continue

            groups = it.get("groups") or []
            parsed_groups = []
            if isinstance(groups, list):
                for g in groups:
                    if isinstance(g, str):
                        parsed_groups.append(g)
                    elif isinstance(g, list) and len(g) == 2 and isinstance(g[0], str) and isinstance(g[1], dict):
                        parsed_groups.append((g[0], GroupOptions(
                            file_regex=str(g[1].get("fileRegex") or g[1].get("file_regex") or "") or None,
                            description=str(g[1].get("description") or "") or None,
                        )))

            out.append(
                ModeConfig(
                    slug=slug,
                    name=name,
                    role_definition=role_definition,
                    when_to_use=(it.get("whenToUse") or it.get("when_to_use")),
                    description=(it.get("description")),
                    custom_instructions=(it.get("customInstructions") or it.get("custom_instructions")),
                    groups=tuple(parsed_groups),
                    source=source,
                )
            )

        # Deduplicate by slug, keep last
        dedup: Dict[str, ModeConfig] = {}
        for m in out:
            dedup[m.slug] = m
        return list(dedup.values())

"""Skill system — load reusable prompt/instruction files.

Skills are Markdown files stored in:
- ``~/.PyChat/skills/``  (global, user-level)
- ``.pychat/skills/``    (project-level, in workspace root)

Each ``.md`` file is a skill.  The filename (without extension) is the
skill name.  The file content is injected into the conversation as
additional instructions when the skill is activated.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A loaded skill definition."""

    name: str
    content: str
    source: str  # file path
    tags: List[str] = field(default_factory=list)


class SkillsManager:
    """Discover and load skills from configured directories."""

    def __init__(self, work_dir: str = ".") -> None:
        self._work_dir = work_dir
        self._skills: Dict[str, Skill] = {}
        self._loaded = False

    @property
    def skills(self) -> Dict[str, Skill]:
        if not self._loaded:
            self.reload()
        return self._skills

    def reload(self) -> None:
        """Reload skills from all configured directories."""
        self._skills.clear()
        for d in self._skill_dirs():
            self._load_from_dir(d)
        self._loaded = True
        logger.debug("Loaded %d skills", len(self._skills))

    def get(self, name: str) -> Optional[Skill]:
        return self.skills.get(name.lower())

    def list_skills(self) -> List[Skill]:
        return list(self.skills.values())

    def get_content(self, name: str) -> Optional[str]:
        skill = self.get(name)
        return skill.content if skill else None

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _skill_dirs(self) -> List[Path]:
        dirs: List[Path] = []

        root = Path(self._work_dir).resolve()

        # Project: .pychat/skills/ overrides global definitions when names collide.
        project_dir = root / ".pychat" / "skills"
        if project_dir.is_dir():
            dirs.append(project_dir)

        # Global: ~/.PyChat/skills/
        home = Path.home()
        global_dir = home / ".PyChat" / "skills"
        if global_dir.is_dir():
            dirs.append(global_dir)

        # Legacy: .skills/
        legacy_dir = root / ".skills"
        if legacy_dir.is_dir():
            dirs.append(legacy_dir)

        return dirs

    def _load_from_dir(self, directory: Path) -> None:
        try:
            for entry in sorted(directory.iterdir()):
                if entry.is_file() and entry.suffix.lower() in (".md", ".txt"):
                    name = entry.stem.lower()
                    if name in self._skills:
                        continue
                    try:
                        content = entry.read_text(encoding="utf-8")
                        tags = self._extract_tags(content)
                        self._skills[name] = Skill(
                            name=name,
                            content=content,
                            source=str(entry),
                            tags=tags,
                        )
                    except Exception as e:
                        logger.warning("Failed to load skill %s: %s", entry, e)
        except Exception as e:
            logger.warning("Failed to scan skill directory %s: %s", directory, e)

    @staticmethod
    def _extract_tags(content: str) -> List[str]:
        """Extract tags from frontmatter-like ``tags: [a, b]`` line."""
        for line in content.splitlines()[:10]:
            stripped = line.strip()
            if stripped.lower().startswith("tags:"):
                raw = stripped[5:].strip().strip("[]")
                return [t.strip() for t in raw.split(",") if t.strip()]
        return []


def resolve_active_skills(
    names: Iterable[str],
    *,
    work_dir: str = ".",
) -> List[Skill]:
    """Resolve a list of active skill names using the workspace-aware skill manager."""
    mgr = SkillsManager(work_dir)
    resolved: List[Skill] = []
    seen: set[str] = set()
    for raw_name in names:
        name = str(raw_name or "").strip().lower()
        if not name or name in seen:
            continue
        skill = mgr.get(name)
        if skill:
            resolved.append(skill)
            seen.add(name)
    return resolved

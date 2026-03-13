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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.config import get_global_subdir

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A loaded skill definition."""

    name: str
    content: str
    source: str  # file path
    description: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


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
        global_dir = get_global_subdir("skills")
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
                skill = None
                try:
                    skill = self._load_skill_entry(entry)
                except Exception as e:
                    logger.warning("Failed to load skill %s: %s", entry, e)
                if not skill:
                    continue
                if skill.name in self._skills:
                    continue
                self._skills[skill.name] = skill
        except Exception as e:
            logger.warning("Failed to scan skill directory %s: %s", directory, e)

    def _load_skill_entry(self, entry: Path) -> Optional[Skill]:
        if entry.is_dir():
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                return None
            return self._load_skill_file(skill_file, default_name=entry.name)

        if entry.is_file() and entry.suffix.lower() in (".md", ".txt"):
            if entry.name.lower() == "skill.md":
                return None
            return self._load_skill_file(entry, default_name=entry.stem)
        return None

    def _load_skill_file(self, path: Path, *, default_name: str) -> Optional[Skill]:
        content = path.read_text(encoding="utf-8")
        metadata, body = self._parse_frontmatter(content)
        raw_name = str(metadata.get("name") or default_name or "").strip().lower()
        if not raw_name:
            return None
        tags = self._extract_tags(body)
        frontmatter_tags = metadata.get("tags")
        if isinstance(frontmatter_tags, list):
            tags = [str(tag).strip() for tag in frontmatter_tags if str(tag).strip()] or tags
        return Skill(
            name=raw_name,
            content=body.strip() or content.strip(),
            source=str(path),
            description=str(metadata.get("description") or "").strip(),
            tags=tags,
            metadata=metadata,
        )

    @staticmethod
    def _parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        stripped = content.lstrip()
        if not stripped.startswith("---"):
            return {}, content

        lines = stripped.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, content

        closing_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            return {}, content

        raw_meta = lines[1:closing_index]
        body = "\n".join(lines[closing_index + 1:])
        metadata: Dict[str, Any] = {}
        for raw_line in raw_meta:
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
                value = value[1:-1]
            if value.startswith("[") and value.endswith("]"):
                metadata[key] = [
                    item.strip().strip("'\"")
                    for item in value[1:-1].split(",")
                    if item.strip()
                ]
                continue
            lowered = value.lower()
            if lowered in {"true", "false"}:
                metadata[key] = lowered == "true"
                continue
            metadata[key] = value
        return metadata, body

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


def suggest_skills_for_query(
    query: str,
    *,
    work_dir: str = ".",
    limit: int = 3,
) -> List[Skill]:
    text = str(query or "").strip().lower()
    if not text:
        return []

    mgr = SkillsManager(work_dir)
    query_tokens = _tokenize_skill_text(text)
    expanded_tokens = set(query_tokens)
    if any(token in expanded_tokens for token in {"playwright", "browser", "web", "website", "page", "google", "search", "截图", "网页", "浏览器", "网站", "表单", "登录"}):
        expanded_tokens.update({"browser", "web", "website", "page", "automation", "form", "login", "screenshot"})

    ranked: List[Tuple[int, Skill]] = []
    for skill in mgr.list_skills():
        haystack = " ".join([
            skill.name,
            skill.description,
            " ".join(skill.tags),
            str(skill.metadata.get("argument-hint") or ""),
        ]).strip().lower()
        if not haystack:
            continue
        skill_tokens = _tokenize_skill_text(haystack)
        overlap = len(expanded_tokens & skill_tokens)
        if overlap <= 0:
            continue
        score = overlap
        if skill.name in text:
            score += 10
        if "browser" in skill_tokens and any(token in expanded_tokens for token in {"browser", "playwright", "web", "website", "page"}):
            score += 3
        ranked.append((score, skill))

    ranked.sort(key=lambda item: (-item[0], item[1].name))
    return [skill for _score, skill in ranked[:max(0, int(limit))]]


def _tokenize_skill_text(value: str) -> set[str]:
    tokens: List[str] = []
    current: List[str] = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_"}:
            current.append(ch)
            continue
        if current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return {token for token in tokens if len(token) >= 2}

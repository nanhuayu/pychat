import json
import os
from pathlib import Path
from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult

class SkillTool(BaseTool):
    @property
    def name(self) -> str:
        return "skill"

    @property
    def description(self) -> str:
        return "Manage and retrieve skills (reusable capabilities/prompts) from the .skills directory."

    @property
    def category(self) -> str:
        return "read"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string", 
                    "description": "Name of the skill to use"
                },
                "args": {
                    "type": "string",
                    "description": "Arguments for the skill (optional)"
                }
            },
            "required": ["skill"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        skill_name = arguments.get("skill")
        args = arguments.get("args", "")
        
        # Define skills directory
        # We assume skills are stored in .skills/ or .roocode/skills/ in the workspace
        root = Path(context.work_dir).resolve()
        skills_dirs = [root / ".skills", root / ".roocode" / "skills"]
        
        valid_skills_dir = None
        for d in skills_dirs:
            if d.exists() and d.is_dir():
                valid_skills_dir = d
                break
        
        if not valid_skills_dir:
             # Backward compatibility / fallback: list skills if no skill_name provided or "list" action was used
             # But here schema requires "skill".
             # If no dir, fail.
             return ToolResult("No .skills/ or .roocode/skills/ directory found in workspace.", is_error=True)
            
        # Try extensions
        target_file = None
        for ext in [".md", ".json", ".txt"]:
            candidate = valid_skills_dir / f"{skill_name}{ext}"
            if candidate.exists():
                target_file = candidate
                break
        
        if not target_file:
             # List available
            skills = []
            for f in valid_skills_dir.glob("*.md"):
                skills.append(f.stem)
            for f in valid_skills_dir.glob("*.json"):
                skills.append(f.stem)
            available = ", ".join(sorted(list(set(skills))))
            return ToolResult(f"Skill '{skill_name}' not found. Available skills: {available}", is_error=True)
            
        try:
            content = target_file.read_text(encoding="utf-8")
            
            result = f"Skill: {skill_name}"
            if args:
                result += f"\nProvided arguments: {args}"
            result += f"\n\n--- Skill Instructions ---\n\n{content}"
            
            return ToolResult(result)
        except Exception as e:
            return ToolResult(f"Error reading skill file: {e}", is_error=True)

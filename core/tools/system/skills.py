from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult
from core.skills import SkillsManager

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
        mgr = SkillsManager(context.work_dir or ".")
        skill = mgr.get(str(skill_name or ""))
        if not skill:
            available = ", ".join(sorted(item.name for item in mgr.list_skills()))
            return ToolResult(
                f"Skill '{skill_name}' not found. Available skills: {available or '(none)'}",
                is_error=True,
            )

        result = f"Skill: {skill.name}"
        if args:
            result += f"\nProvided arguments: {args}"
        result += f"\n\n--- Skill Instructions ---\n\n{skill.content}"
        return ToolResult(result)

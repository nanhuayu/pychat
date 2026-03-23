import asyncio
import base64
import tempfile
import textwrap
import unittest
import json
from pathlib import Path

from core.commands import CommandAction, CommandRegistry, PromptInvocation
from core.config import AppConfig
from core.modes.defaults import get_default_modes
from core.modes.features import get_mode_feature_policy
from core.task.task import Task
from core.task.tool_executor import ToolExecutor
from core.task.types import RetryPolicy, RunPolicy
from core.llm.request_builder import build_api_messages
from core.modes.manager import resolve_mode_config
from core.modes.types import normalize_mode_slug
from core.prompts.system_builder import build_system_prompt
from core.skills import (
    SkillExecutionCheck,
    SkillInvocationSpec,
    Skill,
    SkillsManager,
    check_skill_execution_availability,
    resolve_skill_invocation_spec,
)
from core.tools.mcp.naming import build_mcp_tool_name, parse_mcp_tool_name, tool_names_match
from core.tools.process import decode_subprocess_output
from core.tools.system.filesystem import ReadFileTool
from core.tools.system.skills import LoadSkillTool, ReadSkillResourceTool
from core.tools.system.multi_agent import AttemptCompletionTool
from core.tools.system.state_mgr import StateMgrTool
from core.tools.system.document_tools import ManageDocumentTool
from core.tools.base import ToolContext
from models.conversation import Conversation, Message
from models.provider import Provider, build_model_ref, split_model_ref
from models.state import SessionDocument
from core.state.services.task_planning_service import TaskPlanningService
from services.workspace_session_service import WorkspaceSessionService
from core.state.services.task_service import TaskService


def _make_tools():
    names = [
        "list_files",
        "read_file",
        "execute_command",
        "shell_start",
        "shell_status",
        "shell_logs",
        "shell_wait",
        "shell_kill",
        "builtin_web_search",
    ]
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"Tool {name}",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


class SkillRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = Skill(
            name="agent-browser",
            source="memory",
            description=(
                "Browser automation CLI for AI agents. Use when the user needs to interact "
                "with websites, including navigating pages, filling forms, clicking buttons, "
                "taking screenshots, extracting data, testing web apps, or automating any browser task."
            ),
            metadata={"allowed-tools": "Bash(npx agent-browser:*), Bash(agent-browser:*)"},
            content=textwrap.dedent(
                """
                # Browser Automation with agent-browser

                ```bash
                agent-browser open https://example.com
                agent-browser snapshot -i
                ```
                """
            ).strip(),
        )
        self.tools = _make_tools()

    def test_invocation_spec_extracts_cli_hints(self) -> None:
        spec = resolve_skill_invocation_spec(self.skill)

        self.assertIsInstance(spec, SkillInvocationSpec)
        self.assertEqual("cli", spec.executor)
        self.assertEqual(("npx agent-browser", "agent-browser"), spec.preferred_cli)
        self.assertFalse(spec.enable_search)

    def test_execution_check_prefers_shell_tools_for_cli_skills(self) -> None:
        execution = check_skill_execution_availability(self.skill, self.tools)

        self.assertIsInstance(execution, SkillExecutionCheck)
        self.assertTrue(execution.executable)
        self.assertEqual("execute_command", execution.concrete_tools[0])
        self.assertNotIn("builtin_web_search", execution.concrete_tools)

    def test_mcp_skill_requires_declared_tools(self) -> None:
        skill = Skill(
            name="github-triage",
            source="memory",
            description="Triages GitHub issues through MCP tools.",
            metadata={
                "executor": "mcp",
                "tools": "github:list_issues, github:add_comment",
            },
            content="# GitHub triage",
        )
        tools = self.tools + [
            {
                "type": "function",
                "function": {
                    "name": build_mcp_tool_name("github", "list_issues"),
                    "description": "List issues",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": build_mcp_tool_name("github", "add_comment"),
                    "description": "Add comment",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

        spec = resolve_skill_invocation_spec(skill)
        execution = check_skill_execution_availability(skill, tools)

        self.assertEqual("mcp", spec.executor)
        self.assertTrue(execution.executable)
        self.assertEqual(
            (
                build_mcp_tool_name("github", "list_issues"),
                build_mcp_tool_name("github", "add_comment"),
            ),
            execution.concrete_tools,
        )

    def test_system_prompt_renders_skill_runtime_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / ".pychat" / "skills" / "agent-browser"
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: agent-browser
                    description: Browser automation CLI for AI agents.
                    allowed-tools: Bash(npx agent-browser:*), Bash(agent-browser:*)
                    ---

                    # Browser Automation with agent-browser

                    See [references/commands.md](references/commands.md) for CLI details.

                    ```bash
                    agent-browser open https://example.com
                    agent-browser snapshot -i
                    ```
                    """
                ).strip(),
                encoding="utf-8",
            )
            (refs_dir / "commands.md").write_text("open\nsnapshot\n", encoding="utf-8")

            conversation = Conversation(work_dir=temp_dir, mode="agent")
            conversation.messages.append(
                Message(
                    role="user",
                    content="search wikipedia for iran",
                    metadata={
                        "skill_run": {
                            "name": "agent-browser",
                            "user_input": "search wikipedia for iran",
                        }
                    },
                )
            )

            prompt = build_system_prompt(
                conversation=conversation,
                tools=self.tools,
                provider=Provider(name="test", default_model="demo"),
                app_config=AppConfig(),
            )

            self.assertIn("<available_skills>", prompt)
            self.assertIn("executor: cli", prompt)
            self.assertIn("status: executable", prompt)
            self.assertIn("concrete_tools: execute_command", prompt)
            self.assertIn("preferred_cli: npx agent-browser, agent-browser", prompt)
            self.assertIn("call `load_skill`", prompt)
            self.assertIn("resource_paths:", prompt)
            self.assertNotIn("<loaded_skill", prompt)
            self.assertNotIn("adapter:", prompt)
            self.assertNotIn("execution_family:", prompt)

    def test_system_prompt_surfaces_current_plan_as_primary_artifact(self) -> None:
        conversation = Conversation(work_dir=".", mode="agent")
        state = conversation.get_state()
        state.documents["plan"] = SessionDocument(
            name="plan",
            content="Phase 1\n1. Inspect request flow\n2. Patch runtime\n3. Run regression checks",
        )
        state.documents["memory"] = SessionDocument(
            name="memory",
            content="Remember verified commands and stable repo facts.",
        )
        conversation.set_state(state)
        conversation.messages.append(Message(role="user", content="continue the refactor"))

        prompt = build_system_prompt(
            conversation=conversation,
            tools=self.tools,
            provider=Provider(name="test", default_model="demo"),
            app_config=AppConfig(),
        )

        self.assertIn("<current_plan>", prompt)
        self.assertIn("Phase 1", prompt)
        self.assertIn("Use the current plan as the execution source of truth.", prompt)
        self.assertIn("<session_memory>", prompt)

    def test_plan_mode_prompt_forbids_implementation_in_plan_mode(self) -> None:
        conversation = Conversation(work_dir=".", mode="plan")
        state = conversation.get_state()
        state.documents["plan"] = SessionDocument(name="plan", content="Analyze architecture and produce a rollout plan")
        conversation.set_state(state)
        conversation.messages.append(Message(role="user", content="analyze the architecture and plan the refactor"))

        prompt = build_system_prompt(
            conversation=conversation,
            tools=self.tools,
            provider=Provider(name="test", default_model="demo"),
            app_config=AppConfig(),
        )

        self.assertIn("avoid implementation work in plan mode", prompt)
        self.assertIn("The plan document above is the primary artifact", prompt)

    def test_skills_manager_lists_and_reads_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / ".pychat" / "skills" / "demo-skill"
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: demo-skill
                    description: Demo skill.
                    ---

                    See [references/usage.md](references/usage.md) for more details.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (refs_dir / "usage.md").write_text("line1\nline2\nline3\n", encoding="utf-8")

            mgr = SkillsManager(temp_dir)

            self.assertEqual(["references/usage.md"], mgr.list_resources("demo-skill"))
            snippet = mgr.read_resource("demo-skill", "references/usage.md", start_line=2, end_line=3)

            self.assertIsNotNone(snippet)
            assert snippet is not None
            self.assertEqual(("line2\nline3", 3, 2, 3), snippet)

    def test_load_skill_tool_blocks_disable_model_invocation_without_explicit_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / ".pychat" / "skills" / "restricted-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: restricted-skill
                    description: Restricted skill.
                    disable-model-invocation: true
                    ---

                    # Restricted
                    """
                ).strip(),
                encoding="utf-8",
            )

            tool = LoadSkillTool()
            context = ToolContext(work_dir=temp_dir, conversation=Conversation(work_dir=temp_dir, mode="agent"))

            result = asyncio.run(tool.execute({"skill": "restricted-skill"}, context))

            self.assertTrue(result.is_error)
            self.assertIn("must be explicitly invoked", result.to_string())

    def test_load_and_read_skill_tools_work_after_explicit_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / ".pychat" / "skills" / "demo-skill"
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: demo-skill
                    description: Demo skill.
                    disable-model-invocation: true
                    ---

                    See [references/usage.md](references/usage.md) for more details.

                    # Demo
                    """
                ).strip(),
                encoding="utf-8",
            )
            (refs_dir / "usage.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

            conversation = Conversation(work_dir=temp_dir, mode="agent")
            conversation.messages.append(
                Message(
                    role="user",
                    content="run demo skill",
                    metadata={"skill_run": {"name": "demo-skill", "user_input": "run demo skill"}},
                )
            )
            context = ToolContext(work_dir=temp_dir, conversation=conversation)

            load_result = asyncio.run(LoadSkillTool().execute({"skill": "demo-skill"}, context))
            read_result = asyncio.run(
                ReadSkillResourceTool().execute(
                    {"skill": "demo-skill", "path": "references/usage.md", "start_line": 2, "end_line": 3},
                    context,
                )
            )

            self.assertFalse(load_result.is_error)
            self.assertIn("--- SKILL.md ---", load_result.to_string())
            self.assertIn("Available Resources:", load_result.to_string())
            self.assertFalse(read_result.is_error)
            self.assertIn("Lines 2-3 of 3:", read_result.to_string())
            self.assertIn("beta\ngamma", read_result.to_string())

    def test_build_api_messages_keeps_multi_tool_turn_grouped(self) -> None:
        provider = Provider(name="test", default_model="demo")
        messages = [
            Message(role="user", content="do the work"),
            Message(
                role="assistant",
                content="",
                thinking="reasoning",
                tool_calls=[
                    {"id": "call_1", "type": "function", "function": {"name": "manage_state", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "manage_document", "arguments": "{}"}},
                ],
            ),
            Message(role="tool", content="State updated:\nvery long content", summary="State updated.", tool_call_id="call_1"),
            Message(role="tool", content="Document 'plan' saved (1200 chars).", summary="Document 'plan' saved (1200 chars).", tool_call_id="call_2"),
        ]

        api_messages = build_api_messages(messages, provider)

        self.assertEqual(4, len(api_messages))
        self.assertEqual("assistant", api_messages[1]["role"])
        self.assertEqual(2, len(api_messages[1]["tool_calls"]))
        self.assertEqual("State updated.", api_messages[2]["content"])
        self.assertEqual("Document 'plan' saved (1200 chars).", api_messages[3]["content"])

    def test_build_api_messages_preserves_tool_images(self) -> None:
        provider = Provider(name="test", default_model="demo", supports_vision=True)
        image_url = "data:image/png;base64,AAAA"
        messages = [
            Message(role="user", content="inspect the image"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                        "result": "Image file: assets/pixel.png",
                        "result_images": [image_url],
                    }
                ],
            ),
        ]

        api_messages = build_api_messages(messages, provider)

        self.assertEqual(3, len(api_messages))
        self.assertEqual("tool", api_messages[2]["role"])
        self.assertIsInstance(api_messages[2]["content"], list)
        self.assertEqual("text", api_messages[2]["content"][0]["type"])
        self.assertEqual(image_url, api_messages[2]["content"][1]["image_url"]["url"])

    def test_read_file_tool_returns_image_blocks(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7f8AAAAASUVORK5CYII="
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "pixel.png"
            image_path.write_bytes(png_bytes)

            tool = ReadFileTool()
            context = ToolContext(work_dir=temp_dir, conversation=Conversation(work_dir=temp_dir, mode="agent"))

            result = asyncio.run(tool.execute({"path": "pixel.png"}, context))

            self.assertFalse(result.is_error)
            self.assertIsInstance(result.content, list)
            self.assertEqual("text", result.content[0]["type"])
            self.assertEqual("image", result.content[1]["type"])
            self.assertTrue(str(result.content[1]["data"]).startswith("data:image/png;base64,"))

    def test_plan_command_returns_prompt_run_invocation(self) -> None:
        registry = CommandRegistry()

        result = registry.execute(
            "/plan inspect the runtime flow and produce a concrete plan",
            {"work_dir": ".", "current_mode": "chat"},
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(CommandAction.PROMPT_RUN, result.action)
        self.assertIsInstance(result.data, PromptInvocation)
        assert isinstance(result.data, PromptInvocation)
        self.assertEqual("plan", result.data.mode_slug)
        self.assertEqual(
            "inspect the runtime flow and produce a concrete plan",
            result.data.content,
        )
        self.assertEqual(
            "inspect the runtime flow and produce a concrete plan",
            result.data.document_updates.get("plan", {}).get("content"),
        )

    def test_skill_command_returns_prompt_run_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / ".pychat" / "skills" / "demo-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: demo-skill
                    description: Demo skill.
                    mode: agent
                    ---

                    # Demo skill
                    """
                ).strip(),
                encoding="utf-8",
            )

            registry = CommandRegistry()
            result = registry.execute(
                "/demo-skill inspect this repo",
                {"work_dir": temp_dir, "current_mode": "chat"},
            )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(CommandAction.PROMPT_RUN, result.action)
            self.assertIsInstance(result.data, PromptInvocation)
            assert isinstance(result.data, PromptInvocation)
            self.assertEqual("agent", result.data.mode_slug)
            self.assertEqual("inspect this repo", result.data.content)
            self.assertEqual("demo-skill", result.data.metadata["skill_run"]["name"])

    def test_skills_manager_ignores_legacy_skills_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = Path(temp_dir) / ".skills"
            legacy_dir.mkdir(parents=True)
            (legacy_dir / "legacy.md").write_text("# legacy skill", encoding="utf-8")

            mgr = SkillsManager(temp_dir)

            self.assertIsNone(mgr.get("legacy"))

    def test_skills_manager_ignores_flat_legacy_skill_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_skill = Path(temp_dir) / ".pychat" / "skills" / "legacy-skill.md"
            legacy_skill.parent.mkdir(parents=True)
            legacy_skill.write_text("# legacy skill", encoding="utf-8")

            mgr = SkillsManager(temp_dir)

            self.assertIsNone(mgr.get("legacy-skill"))

    def test_workspace_session_snapshot_keeps_only_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WorkspaceSessionService(root_dir=Path(temp_dir) / "workspace_sessions")
            conversation = Conversation(work_dir=temp_dir, mode="agent")
            state = conversation.get_state()
            state.summary = "session summary"
            state.memory["topic"] = "commands"
            state.documents["plan"] = SessionDocument(name="plan", content="1. inspect\n2. patch")
            conversation.set_state(state)

            session_dir = service._get_session_dir(conversation)
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "tasks.json").write_text("[]", encoding="utf-8")
            (session_dir / "memory.json").write_text("{}", encoding="utf-8")
            (session_dir / "summary.md").write_text("old", encoding="utf-8")
            (session_dir / "documents").mkdir(parents=True, exist_ok=True)

            service.save_snapshot(conversation)

            self.assertTrue((session_dir / "state.json").exists())
            self.assertFalse((session_dir / "tasks.json").exists())
            self.assertFalse((session_dir / "memory.json").exists())
            self.assertFalse((session_dir / "summary.md").exists())
            self.assertFalse((session_dir / "documents").exists())

    def test_attempt_completion_tool_returns_compact_ack(self) -> None:
        tool = AttemptCompletionTool()
        context = ToolContext(work_dir=".", conversation=Conversation(work_dir=".", mode="agent"))

        result = asyncio.run(tool.execute({"result": "Finished all requested changes"}, context))

        self.assertFalse(result.is_error)
        self.assertEqual("Completion acknowledged.", result.to_string())
        self.assertEqual("Finished all requested changes", context.state["_completion_result"])

    def test_state_manager_result_omits_state_echo(self) -> None:
        tool = StateMgrTool()
        context = ToolContext(
            work_dir=".",
            state={"_current_seq": 3},
            conversation=Conversation(work_dir=".", mode="agent"),
        )

        result = asyncio.run(
            tool.execute(
                {
                    "tasks": [{"action": "create", "content": "Investigate request builder", "status": "in_progress"}],
                    "memory": {"active_mode": "agent"},
                },
                context,
            )
        )

        self.assertFalse(result.is_error)
        self.assertIn("State updated:", result.to_string())
        self.assertNotIn("📋 Active tasks", result.to_string())
        self.assertNotIn("💾 Memory keys", result.to_string())

    def test_manage_document_survives_post_tool_state_sync(self) -> None:
        conversation = Conversation(work_dir=".", mode="agent")
        context = ToolContext(
            work_dir=".",
            state=conversation.get_state().to_dict(),
            conversation=conversation,
        )

        result = asyncio.run(
            ManageDocumentTool().execute(
                {"action": "update", "name": "plan", "content": "inspect\npatch\nverify"},
                context,
            )
        )

        ToolExecutor(tool_manager=object()).sync_state(conversation, context)
        state = conversation.get_state()

        self.assertFalse(result.is_error)
        self.assertIn("plan", state.documents)
        self.assertEqual("inspect\npatch\nverify", state.documents["plan"].content)

    def test_manage_document_persists_document_metadata(self) -> None:
        conversation = Conversation(work_dir=".", mode="agent")
        context = ToolContext(
            work_dir=".",
            state=conversation.get_state().to_dict(),
            conversation=conversation,
        )

        result = asyncio.run(
            ManageDocumentTool().execute(
                {
                    "action": "update",
                    "name": "report",
                    "content": "full report body",
                    "abstract": "repo-level analysis",
                    "kind": "report",
                    "references": ["docs/ARCHITECTURE_OPTIMIZATION.md", "core/task/task.py#L700"],
                },
                context,
            )
        )

        ToolExecutor(tool_manager=object()).sync_state(conversation, context)
        doc = conversation.get_state().documents["report"]

        self.assertFalse(result.is_error)
        self.assertEqual("repo-level analysis", doc.abstract)
        self.assertEqual("report", doc.kind)
        self.assertEqual(["docs/ARCHITECTURE_OPTIMIZATION.md", "core/task/task.py#L700"], doc.references)

    def test_task_service_prunes_completed_items(self) -> None:
        conversation = Conversation(work_dir=".", mode="agent")
        state = conversation.get_state()

        TaskService.handle_ops(
            state,
            [{"action": "create", "content": "inspect runtime", "status": "completed"}],
            current_seq=1,
        )

        self.assertEqual([], state.tasks)

    def test_task_planning_service_bootstraps_multiple_tasks(self) -> None:
        tasks = TaskPlanningService.build_bootstrap_tasks(
            request_text="重构 provider 显示；统一 model 标识；补 UI 回归",
            mode_slug="agent",
            current_seq=3,
        )

        self.assertGreaterEqual(len(tasks), 3)
        self.assertIn("provider 显示", tasks[0].content)

    def test_task_planning_service_marks_ambiguous_requests_for_clarification(self) -> None:
        tasks = TaskPlanningService.build_bootstrap_tasks(
            request_text="修一下",
            mode_slug="agent",
            current_seq=5,
        )

        self.assertTrue(tasks)
        self.assertIn("确认", tasks[0].content)

    def test_workspace_snapshot_persists_tool_written_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conversation = Conversation(work_dir=temp_dir, mode="plan")
            context = ToolContext(
                work_dir=temp_dir,
                state=conversation.get_state().to_dict(),
                conversation=conversation,
            )

            asyncio.run(
                ManageDocumentTool().execute(
                    {
                        "action": "update",
                        "name": "plan",
                        "content": "analyze\nrefactor\nverify",
                        "abstract": "plan index",
                        "references": ["core/task/task.py", "ui/main_window.py"],
                    },
                    context,
                )
            )
            ToolExecutor(tool_manager=object()).sync_state(conversation, context)

            service = WorkspaceSessionService(root_dir=Path(temp_dir) / "workspace_sessions")
            service.save_snapshot(conversation)

            payload = json.loads((Path(temp_dir) / ".pychat" / "sessions" / conversation.id / "state.json").read_text(encoding="utf-8"))

            self.assertEqual("analyze\nrefactor\nverify", payload["documents"]["plan"]["content"])
            self.assertEqual("plan index", payload["documents"]["plan"]["abstract"])

    def test_chat_mode_policy_matches_optional_tools(self) -> None:
        mode = resolve_mode_config("chat")
        policy = get_mode_feature_policy(mode)

        self.assertIn("search", mode.group_names())
        self.assertIn("mcp", mode.group_names())
        self.assertTrue(policy.allow_search)
        self.assertTrue(policy.allow_mcp)
        self.assertFalse(policy.default_search)
        self.assertFalse(policy.default_mcp)

    def test_mcp_tool_name_codec_roundtrip(self) -> None:
        name = build_mcp_tool_name("GitHub Server", "list-issues")

        self.assertEqual("mcp__GitHub_Server__list-issues", name)
        self.assertEqual(("GitHub_Server", "list-issues"), parse_mcp_tool_name(name))
        self.assertTrue(tool_names_match(name, "mcp--GitHub_Server--list-issues"))

    def test_provider_omits_empty_bearer_header(self) -> None:
        provider = Provider(name="local", api_base="http://localhost:11434/v1", api_key="")

        headers = provider.get_headers()

        self.assertEqual("application/json", headers["Content-Type"])
        self.assertNotIn("Authorization", headers)

    def test_provider_model_ref_uses_canonical_provider_name(self) -> None:
        provider = Provider(name="Anthropic (via Proxy)", default_model="claude-3-5-sonnet")

        self.assertEqual("anthropic-via-proxy", provider.name)
        self.assertEqual(
            "anthropic-via-proxy|claude-3-5-sonnet",
            build_model_ref(provider.name, provider.default_model),
        )
        self.assertEqual(
            ("anthropic-via-proxy", "claude-3-5-sonnet"),
            split_model_ref("Anthropic (via Proxy)|claude-3-5-sonnet"),
        )

    def test_architect_mode_no_longer_aliases_to_plan(self) -> None:
        builtin_slugs = {mode.slug for mode in get_default_modes()}

        self.assertIn("plan", builtin_slugs)
        self.assertNotIn("architect", builtin_slugs)
        self.assertEqual("architect", normalize_mode_slug("architect"))

        mode = resolve_mode_config("architect")

        self.assertEqual("architect", mode.slug)
        self.assertNotEqual("plan", mode.slug)

    def test_switch_mode_rebuilds_target_mode_defaults(self) -> None:
        task = Task(client=object(), tool_manager=object())
        conversation = Conversation(work_dir=".", mode="plan")
        current_policy = RunPolicy(
            mode="plan",
            enable_thinking=False,
            enable_search=False,
            enable_mcp=False,
            retry=RetryPolicy(),
        )

        next_policy = task._build_switched_policy(
            current_policy=current_policy,
            conversation=conversation,
            next_mode="agent",
        )

        self.assertEqual("agent", next_policy.mode)
        self.assertTrue(next_policy.enable_thinking)
        self.assertTrue(next_policy.enable_search)
        self.assertTrue(next_policy.enable_mcp)

    def test_merge_subtask_state_carries_plan_back_to_parent(self) -> None:
        task = Task(client=object(), tool_manager=object())
        parent = Conversation(work_dir=".", mode="orchestrator")
        child = Conversation(work_dir=".", mode="plan")

        parent_state = parent.get_state()
        parent_state.documents["plan"] = SessionDocument(name="plan", content="old plan")
        parent.set_state(parent_state)

        child_state = child.get_state()
        child_state.documents["plan"] = SessionDocument(name="plan", content="new plan from child")
        child_state.memory["repo_fact"] = "important"
        child.set_state(child_state)

        task._merge_subtask_state(parent_conversation=parent, child_conversation=child)

        merged_state = parent.get_state()
        self.assertEqual("new plan from child", merged_state.documents["plan"].content)
        self.assertEqual("important", merged_state.memory["repo_fact"])

    def test_build_completion_message_uses_completion_result(self) -> None:
        task = Task(client=object(), tool_manager=object())
        conversation = Conversation(work_dir=".", mode="agent")

        msg = task._build_completion_message(
            conversation=conversation,
            completion_text="Implemented the request-chain cleanup.",
            completion_command="open report",
        )

        self.assertEqual("assistant", msg.role)
        self.assertEqual("Implemented the request-chain cleanup.", msg.content)
        self.assertTrue(msg.metadata.get("completion"))
        self.assertEqual("open report", msg.metadata.get("completion_command"))

    def test_decode_subprocess_output_handles_utf16le_shell_output(self) -> None:
        text = "hello\n中文输出"

        decoded = decode_subprocess_output(text.encode("utf-16-le"))

        self.assertEqual(text, decoded)


if __name__ == "__main__":
    unittest.main()
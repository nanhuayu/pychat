"""Process execution helpers used by command-oriented tools."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\bdel\s+/[sS]",
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\s+",
    r"\b>\s*/dev/",
    r"\bgit\s+push\s+.*--force",
    r"\bgit\s+reset\s+--hard",
    r"\bdrop\s+database\b",
    r"\bdrop\s+table\b",
    r"\btruncate\s+",
    r"\bshutdown\b",
    r"\breboot\b",
]
_MAX_OUTPUT_LINES = 2000
_MAX_OUTPUT_BYTES = 50 * 1024


def decode_subprocess_output(data: object) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        return data
    if not isinstance(data, (bytes, bytearray)):
        try:
            return str(data)
        except Exception:
            return ""

    raw = bytes(data)
    for enc in ("utf-8", "utf-8-sig", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def truncate_process_output(text: str) -> str:
    if len(text) > _MAX_OUTPUT_BYTES:
        text = text[:_MAX_OUTPUT_BYTES] + f"\n\n... [truncated at {_MAX_OUTPUT_BYTES} bytes]"
    lines = text.splitlines()
    if len(lines) > _MAX_OUTPUT_LINES:
        text = "\n".join(lines[:_MAX_OUTPUT_LINES]) + f"\n\n... [{len(lines) - _MAX_OUTPUT_LINES} lines truncated]"
    return text


def is_dangerous_command(command: str) -> bool:
    cmd_lower = command.lower()
    return any(re.search(pattern, cmd_lower) for pattern in _DANGEROUS_PATTERNS)


@dataclass(frozen=True)
class CommandExecutionRequest:
    command: str
    cwd: Path
    timeout_sec: int = 120
    background: bool = False


@dataclass(frozen=True)
class CommandExecutionResult:
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    pid: int | None = None
    timed_out: bool = False

    def to_display_text(self, cwd: Path) -> str:
        if self.pid is not None:
            return f"Command started in background (PID {self.pid})"

        if self.timed_out:
            return (
                f"Command timed out after execution in '{cwd}'. "
                "Use 'background: true' for long-running commands."
            )

        parts = [f"Command executed in '{cwd}'. Exit code: {self.exit_code}"]
        if self.stdout:
            parts.append(f"Stdout:\n{self.stdout}")
        if self.stderr:
            parts.append(f"Stderr:\n{self.stderr}")
        return "\n\n".join(parts)


class CommandExecutor:
    """Thin wrapper around subprocess for consistent command execution behavior."""

    def execute(self, request: CommandExecutionRequest) -> CommandExecutionResult:
        if request.background:
            proc = subprocess.Popen(
                request.command,
                shell=True,
                cwd=str(request.cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return CommandExecutionResult(exit_code=None, pid=proc.pid)

        try:
            proc = subprocess.run(
                request.command,
                shell=True,
                cwd=str(request.cwd),
                capture_output=True,
                text=False,
                timeout=request.timeout_sec,
            )
            return CommandExecutionResult(
                exit_code=proc.returncode,
                stdout=truncate_process_output(decode_subprocess_output(proc.stdout).strip()),
                stderr=truncate_process_output(decode_subprocess_output(proc.stderr).strip()),
            )
        except subprocess.TimeoutExpired:
            return CommandExecutionResult(exit_code=None, timed_out=True)

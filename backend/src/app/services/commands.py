from __future__ import annotations

import subprocess
from pathlib import Path

from app.models import (
    CommandExecutionResult,
    CommandStep,
    GitRepository,
    StepExecution,
    utcnow,
)

MAX_COMMAND_LOG_CHARS = 50000


def run_command_for_repository(
    command_step: CommandStep,
    execution: StepExecution,
    repository: GitRepository,
    cwd: Path,
) -> CommandExecutionResult:
    command_text = command_step.command_text.strip()
    if not command_text:
        raise ValueError("command step requires a command")
    started_at = utcnow()
    try:
        completed = subprocess.run(
            command_text,
            cwd=str(cwd),
            shell=True,
            executable=command_step.shell or "/bin/sh",
            check=False,
            capture_output=True,
            text=True,
            timeout=command_step.timeout_seconds,
        )
        finished_at = utcnow()
        return CommandExecutionResult(
            step_execution_id=execution.id,
            step_id=execution.step_id,
            command_step_id=command_step.id,
            repository_id=repository.id,
            cwd=str(cwd),
            command_text=command_text,
            status="completed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout),
            stderr=_truncate(completed.stderr),
            started_at=started_at,
            finished_at=finished_at,
        )
    except subprocess.TimeoutExpired as error:
        finished_at = utcnow()
        return CommandExecutionResult(
            step_execution_id=execution.id,
            step_id=execution.step_id,
            command_step_id=command_step.id,
            repository_id=repository.id,
            cwd=str(cwd),
            command_text=command_text,
            status="failed",
            exit_code=None,
            stdout=_truncate(_to_text(error.stdout)),
            stderr=_truncate(_to_text(error.stderr) + f"\nCommand timed out after {command_step.timeout_seconds} seconds."),
            started_at=started_at,
            finished_at=finished_at,
        )


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _truncate(value: str) -> str:
    if len(value) <= MAX_COMMAND_LOG_CHARS:
        return value
    return value[:MAX_COMMAND_LOG_CHARS] + "\n...[truncated]"


def append_truncated(existing: str, chunk: str, *, max_chars: int = MAX_COMMAND_LOG_CHARS) -> str:
    value = f"{existing}{chunk}"
    if len(value) <= max_chars:
        return value
    return value[-max_chars:] + "\n...[truncated]"

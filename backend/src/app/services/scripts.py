from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from app.models import (
    GitRepository,
    Script,
    ScriptExecutionResult,
    StepExecution,
    utcnow,
)
from app.services.workspaces import workspace_root

SUPPORTED_SCRIPT_LANGUAGES = {"python", "javascript", "typescript"}
SCRIPT_ENTRYPOINTS = {
    "python": "index.py",
    "javascript": "index.js",
    "typescript": "index.ts",
}
MAX_SCRIPT_LOG_CHARS = 50000


def slugify_script(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "script"


def normalize_script_language(raw: str) -> str:
    language = raw.strip().lower()
    if language not in SUPPORTED_SCRIPT_LANGUAGES:
        raise ValueError("script language must be python, javascript, or typescript")
    return language


def script_dir(script: Script) -> Path:
    return workspace_root() / "scripts" / script.slug


def script_entrypoint_name(language: str) -> str:
    return SCRIPT_ENTRYPOINTS[normalize_script_language(language)]


def script_entrypoint_path(script: Script) -> Path:
    return script_dir(script) / script_entrypoint_name(script.language)


def read_script_source(script: Script) -> str:
    path = script_entrypoint_path(script)
    return path.read_text() if path.exists() else ""


def read_script_env(script: Script) -> str:
    path = script_dir(script) / ".env"
    return path.read_text() if path.exists() else ""


def write_script_files(script: Script, source_code: str | None = None, env_text: str | None = None) -> None:
    target = script_dir(script)
    target.mkdir(parents=True, exist_ok=True)
    entrypoint = script_entrypoint_path(script)
    if source_code is not None:
        entrypoint.write_text(source_code)
    elif not entrypoint.exists():
        entrypoint.write_text(_default_source(script.language))
    env_path = target / ".env"
    if env_text is not None:
        env_path.write_text(env_text)
    elif not env_path.exists():
        env_path.write_text("")


def move_script_files(old_slug: str, script: Script) -> None:
    old_dir = workspace_root() / "scripts" / old_slug
    new_dir = script_dir(script)
    if old_dir == new_dir or not old_dir.exists():
        return
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    if new_dir.exists():
        raise ValueError("target script slug already has files")
    old_dir.rename(new_dir)


def delete_script_files(script: Script) -> None:
    target = script_dir(script)
    if target.exists():
        shutil.rmtree(target)


def run_script_for_repository(
    script: Script,
    execution: StepExecution,
    repository: GitRepository,
    cwd: Path,
    args_text: str = "",
) -> ScriptExecutionResult:
    entrypoint = script_entrypoint_path(script)
    if not entrypoint.exists():
        raise ValueError("script entrypoint is missing")
    env = os.environ.copy()
    env.update(_parse_env(read_script_env(script)))
    env.update(
        {
            "VIBE_SCRIPT_ID": script.id,
            "VIBE_SCRIPT_SLUG": script.slug,
            "VIBE_STEP_ID": execution.step_id,
            "VIBE_STEP_EXECUTION_ID": execution.id,
            "VIBE_REPOSITORY_ID": repository.id,
            "VIBE_REPOSITORY_NAME": repository.name,
            "VIBE_REPOSITORY_DEFAULT_BRANCH": repository.default_branch,
            "VIBE_REPOSITORY_PATH": str(cwd),
        }
    )
    command = [*_command_for_script(script, entrypoint), *_parse_args(args_text)]
    started_at = utcnow()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    finished_at = utcnow()
    return ScriptExecutionResult(
        step_execution_id=execution.id,
        step_id=execution.step_id,
        script_id=script.id,
        repository_id=repository.id,
        cwd=str(cwd),
        status="completed" if completed.returncode == 0 else "failed",
        exit_code=completed.returncode,
        stdout=_truncate(completed.stdout),
        stderr=_truncate(completed.stderr),
        started_at=started_at,
        finished_at=finished_at,
    )


def command_for_script(script: Script) -> list[str]:
    entrypoint = script_entrypoint_path(script)
    if not entrypoint.exists():
        raise ValueError("script entrypoint is missing")
    return _command_for_script(script, entrypoint)


def environment_for_script(script: Script, execution: StepExecution, repository: GitRepository, cwd: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_parse_env(read_script_env(script)))
    env.update(
        {
            "VIBE_SCRIPT_ID": script.id,
            "VIBE_SCRIPT_SLUG": script.slug,
            "VIBE_STEP_ID": execution.step_id,
            "VIBE_STEP_EXECUTION_ID": execution.id,
            "VIBE_REPOSITORY_ID": repository.id,
            "VIBE_REPOSITORY_NAME": repository.name,
            "VIBE_REPOSITORY_DEFAULT_BRANCH": repository.default_branch,
            "VIBE_REPOSITORY_PATH": str(cwd),
        }
    )
    return env


def parse_script_args(args_text: str) -> list[str]:
    return _parse_args(args_text)


def _command_for_script(script: Script, entrypoint: Path) -> list[str]:
    if script.language == "python":
        return ["python", str(entrypoint)]
    if script.language == "javascript":
        return ["node", str(entrypoint)]
    if script.language == "typescript":
        if shutil.which("tsx"):
            return ["tsx", str(entrypoint)]
        if shutil.which("npx"):
            return ["npx", "tsx", str(entrypoint)]
        raise ValueError("typescript script execution requires tsx or npx")
    raise ValueError("unsupported script language")


def _parse_args(args_text: str) -> list[str]:
    text = args_text.strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError as error:
        raise ValueError(f"invalid script args: {error}") from error


def _parse_env(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def _truncate(value: str) -> str:
    if len(value) <= MAX_SCRIPT_LOG_CHARS:
        return value
    return value[:MAX_SCRIPT_LOG_CHARS] + "\n...[truncated]"


def _default_source(language: str) -> str:
    if language == "python":
        return "print('Vibe script ready')\n"
    if language == "javascript":
        return "console.log('Vibe script ready');\n"
    return "console.log('Vibe script ready');\n"

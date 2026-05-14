from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from sqlmodel import Session, select

from app.models import GitRepository, PlanRepository, WorkspaceCheckout, utcnow

MAX_LOG_TEXT_LENGTH = 4000


class GitWorkspaceError(ValueError):
    pass


def workspace_root() -> Path:
    raw = os.getenv("VIBE_WORKSPACE_ROOT", "~/workspace")
    return Path(raw).expanduser()


def repo_mirror_path(repository_id: str) -> Path:
    return workspace_root() / "repos" / repository_id


def agent_path(agent_id: str) -> Path:
    return workspace_root() / "agents" / agent_id


def plan_repo_path(plan_id: str, repository: GitRepository) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", repository.name.strip()).strip("-")
    return workspace_root() / "plans" / plan_id / (slug or repository.id)


def ensure_workspace_dirs() -> None:
    for name in ("repos", "agents", "plans", "scripts"):
        (workspace_root() / name).mkdir(parents=True, exist_ok=True)


def sync_repository_mirror(
    session: Session,
    repository: GitRepository,
) -> WorkspaceCheckout:
    ensure_workspace_dirs()
    target = repo_mirror_path(repository.id)
    _log_git_event(
        "repository_sync_start",
        repository=repository,
        target=target,
        details={"target_exists": target.exists()},
    )
    try:
        if target.exists():
            _run_git(["fetch", "--all", "--prune"], target, repository=repository)
            _run_git(
                ["checkout", repository.default_branch],
                target,
                repository=repository,
            )
            _run_git(["pull", "--ff-only"], target, repository=repository)
        else:
            _run_git(
                ["clone", repository.remote_url, str(target)],
                workspace_root(),
                repository=repository,
            )
            _run_git(
                ["checkout", repository.default_branch],
                target,
                repository=repository,
            )
    except Exception as exc:
        _log_git_event(
            "repository_sync_failed",
            repository=repository,
            target=target,
            details={"error_type": type(exc).__name__, "error": _truncate(str(exc))},
        )
        if isinstance(exc, GitWorkspaceError):
            raise
        raise GitWorkspaceError(f"git sync failed: {exc}") from exc

    repository.local_path = str(target)
    repository.updated_at = utcnow()
    session.add(repository)
    checkout = WorkspaceCheckout(
        repository_id=repository.id,
        owner_type="repository",
        owner_id=repository.id,
        path=str(target),
        branch=repository.default_branch,
        base_ref=repository.default_branch,
        status="ready",
        last_synced_at=utcnow(),
    )
    session.add(checkout)
    session.commit()
    session.refresh(checkout)
    _log_git_event(
        "repository_sync_succeeded",
        repository=repository,
        target=target,
        details={"checkout_id": checkout.id, "branch": checkout.branch},
    )
    return checkout


def create_plan_checkout(
    session: Session,
    repository: GitRepository,
    plan_id: str,
    start_ref: str | None = None,
) -> WorkspaceCheckout:
    ensure_workspace_dirs()
    mirror = repo_mirror_path(repository.id)
    if not mirror.exists():
        sync_repository_mirror(session, repository)
    else:
        _run_git(["fetch", "--all", "--prune"], mirror, repository=repository)
    target = plan_repo_path(plan_id, repository)
    requested_ref = (
        (start_ref or repository.default_branch).strip() or repository.default_branch
    )
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            ["clone", str(mirror), str(target)],
            workspace_root(),
            repository=repository,
        )
    _configure_plan_checkout_remote(target, repository)
    _run_git(["fetch", "--all", "--prune"], target, repository=repository)
    _checkout_plan_ref(target, requested_ref, repository)
    resolved_commit = _git_output(["rev-parse", "HEAD"], target, repository=repository)
    branch = (
        _git_output(["branch", "--show-current"], target, repository=repository)
        or requested_ref
    )
    checkout = session.exec(
        select(WorkspaceCheckout).where(
            WorkspaceCheckout.repository_id == repository.id,
            WorkspaceCheckout.owner_type == "plan",
            WorkspaceCheckout.owner_id == plan_id,
        )
    ).first()
    if checkout:
        checkout.path = str(target)
        checkout.branch = branch
        checkout.base_ref = requested_ref
        checkout.status = "ready"
        checkout.last_synced_at = utcnow()
        checkout.updated_at = utcnow()
    else:
        checkout = WorkspaceCheckout(
            repository_id=repository.id,
            owner_type="plan",
            owner_id=plan_id,
            path=str(target),
            branch=branch,
            base_ref=requested_ref,
            status="ready",
            last_synced_at=utcnow(),
        )
    session.add(checkout)
    membership = session.exec(
        select(PlanRepository).where(
            PlanRepository.plan_id == plan_id,
            PlanRepository.repository_id == repository.id,
        )
    ).first()
    if membership:
        membership.start_ref = requested_ref
        membership.resolved_start_commit = resolved_commit
        membership.plan_branch = None
        membership.checkout_path = str(target)
        membership.status = "ready"
        membership.updated_at = utcnow()
        session.add(membership)
    session.commit()
    session.refresh(checkout)
    return checkout


def _configure_plan_checkout_remote(target: Path, repository: GitRepository) -> None:
    _run_git(
        ["remote", "set-url", "origin", repository.remote_url],
        target,
        repository=repository,
    )


def _checkout_plan_ref(
    target: Path,
    requested_ref: str,
    repository: GitRepository,
) -> None:
    local_ref = f"refs/heads/{requested_ref}"
    target_remote_ref = f"refs/remotes/origin/{requested_ref}"
    default_remote_ref = f"refs/remotes/origin/{repository.default_branch}"
    if _git_ref_exists(target, local_ref):
        _run_git(["checkout", requested_ref], target, repository=repository)
        return
    if _git_ref_exists(target, target_remote_ref):
        _run_git(
            ["checkout", "--track", f"origin/{requested_ref}"],
            target,
            repository=repository,
        )
        return
    if _git_ref_exists(target, default_remote_ref):
        _run_git(
            ["checkout", "-b", requested_ref, f"origin/{repository.default_branch}"],
            target,
            repository=repository,
        )
        return
    try:
        _run_git(["checkout", requested_ref], target, repository=repository)
    except GitWorkspaceError:
        _run_git(["checkout", "-b", requested_ref], target, repository=repository)


def _run_git(
    args: list[str],
    cwd: Path,
    *,
    repository: GitRepository | None = None,
) -> None:
    _run_git_command(args, cwd, repository=repository)


def _git_output(
    args: list[str],
    cwd: Path,
    *,
    repository: GitRepository | None = None,
) -> str:
    completed = _run_git_command(args, cwd, repository=repository)
    return completed.stdout.strip()


def _git_ref_exists(cwd: Path, ref: str) -> bool:
    completed = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=str(cwd),
        env=_git_env(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode == 0


def _run_git_command(
    args: list[str],
    cwd: Path,
    *,
    repository: GitRepository | None = None,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    safe_args = _redact_git_args(args)
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=_git_env(),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        _log_git_event(
            "git_command_timeout",
            repository=repository,
            target=cwd,
            details={
                "args": safe_args,
                "cwd": str(cwd),
                "timeout_seconds": exc.timeout,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "stdout": _coerce_process_text(exc.stdout),
                "stderr": _coerce_process_text(exc.stderr),
            },
        )
        raise GitWorkspaceError(
            f"git {' '.join(safe_args)} timed out after {exc.timeout} seconds"
        ) from exc

    details = {
        "args": safe_args,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "stdout": _truncate(completed.stdout.strip()),
        "stderr": _truncate(completed.stderr.strip()),
    }
    _log_git_event(
        "git_command_succeeded" if completed.returncode == 0 else "git_command_failed",
        repository=repository,
        target=cwd,
        details=details,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git command failed").strip()
        raise GitWorkspaceError(_truncate(detail))
    return completed


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_ASKPASS", "/bin/false")
    env.setdefault("SSH_ASKPASS", "/bin/false")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=15")
    return env


def _log_git_event(
    event: str,
    *,
    repository: GitRepository | None,
    target: Path,
    details: dict,
) -> None:
    log_path = Path(os.getenv("VIBE_GIT_SYNC_LOG", "data/logs/git-sync.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": utcnow().isoformat(),
        "event": event,
        "repository": _repository_log_payload(repository),
        "target": str(target),
        **details,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _repository_log_payload(repository: GitRepository | None) -> dict | None:
    if repository is None:
        return None
    return {
        "id": repository.id,
        "name": repository.name,
        "remote_url": _redact_secret_text(repository.remote_url),
        "default_branch": repository.default_branch,
        "local_path": repository.local_path,
    }


def _redact_git_args(args: list[str]) -> list[str]:
    return [_redact_secret_text(arg) for arg in args]


def _redact_secret_text(value: str) -> str:
    return re.sub(r"(https?://)([^/@:\s]+):([^/@\s]+)@", r"\1***:***@", value)


def _coerce_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return _truncate(value.decode("utf-8", errors="replace").strip())
    return _truncate(value.strip())


def _truncate(value: str) -> str:
    if len(value) <= MAX_LOG_TEXT_LENGTH:
        return value
    return f"{value[:MAX_LOG_TEXT_LENGTH]}..."

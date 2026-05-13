from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import TextIO

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import engine, get_session
from app.models import (
    AgentRun,
    AgentThread,
    ChatThread,
    CommandExecutionResult,
    CommandStep,
    GitRepository,
    Plan,
    PlanAgentThread,
    PlanChatThread,
    PlanRepository,
    PlanType,
    Script,
    ScriptExecutionResult,
    ScriptStep,
    Step,
    StepAssignment,
    StepAssignmentAgentThread,
    StepCommit,
    StepDependency,
    StepExecution,
    StepExecutionAgentThread,
    StepRepository,
    StepType,
    utcnow,
)
from app.routes.common import get_or_404
from app.schemas import (
    HumanStepComplete,
    PlanAdvance,
    PlanCreate,
    PlanRepositorySelection,
    StepAssignmentCreate,
    StepCreate,
    StepExecutionBlock,
    StepExecutionComplete,
    StepExecutionResume,
    StepExecutionStart,
    StepUpdate,
)
from app.services.agent_runtime import start_worker_for_assignment
from app.services.commands import append_truncated
from app.services.plan_deletion import delete_plan_cascade
from app.services.scripts import (
    command_for_script,
    environment_for_script,
    parse_script_args,
)
from app.services.workspaces import create_plan_checkout

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("/types")
def list_plan_types(session: Session = Depends(get_session)) -> dict:
    return {
        "plan_types": session.exec(select(PlanType).order_by(PlanType.name)).all(),
        "step_types": session.exec(select(StepType).order_by(StepType.name)).all(),
    }


@router.get("")
def list_plans(session: Session = Depends(get_session)) -> list[Plan]:
    return session.exec(select(Plan).order_by(Plan.updated_at.desc())).all()


@router.post("")
def create_plan(payload: PlanCreate, session: Session = Depends(get_session)) -> Plan:
    data = payload.model_dump()
    if data.get("execution_mode") not in {"sequential", "parallel"}:
        data["execution_mode"] = "parallel"
    plan = Plan(**data)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: str, session: Session = Depends(get_session)) -> None:
    plan = get_or_404(session, Plan, plan_id)
    delete_plan_cascade(session, plan)
    session.commit()


@router.get("/{plan_id}/detail")
def plan_detail(plan_id: str, session: Session = Depends(get_session)) -> dict:
    plan = get_or_404(session, Plan, plan_id)
    steps = session.exec(select(Step).where(Step.plan_id == plan.id).order_by(Step.position, Step.created_at)).all()
    step_ids = [step.id for step in steps]
    assignments = session.exec(
        select(StepAssignment).where(StepAssignment.step_id.in_(step_ids))
    ).all() if step_ids else []
    dependencies = session.exec(
        select(StepDependency).where(StepDependency.step_id.in_(step_ids))
    ).all() if step_ids else []
    repositories = session.exec(
        select(PlanRepository).where(PlanRepository.plan_id == plan.id).order_by(PlanRepository.created_at)
    ).all()
    step_repositories = session.exec(
        select(StepRepository).where(StepRepository.step_id.in_(step_ids))
    ).all() if step_ids else []
    executions = session.exec(
        select(StepExecution).where(StepExecution.step_id.in_(step_ids)).order_by(StepExecution.created_at)
    ).all() if step_ids else []
    execution_ids = [execution.id for execution in executions]
    commits = session.exec(
        select(StepCommit).where(StepCommit.step_execution_id.in_(execution_ids)).order_by(StepCommit.created_at)
    ).all() if execution_ids else []
    script_steps = session.exec(
        select(ScriptStep).where(ScriptStep.step_id.in_(step_ids))
    ).all() if step_ids else []
    command_steps = session.exec(
        select(CommandStep).where(CommandStep.step_id.in_(step_ids))
    ).all() if step_ids else []
    script_results = session.exec(
        select(ScriptExecutionResult).where(ScriptExecutionResult.step_execution_id.in_(execution_ids)).order_by(ScriptExecutionResult.created_at)
    ).all() if execution_ids else []
    command_results = session.exec(
        select(CommandExecutionResult).where(CommandExecutionResult.step_execution_id.in_(execution_ids)).order_by(CommandExecutionResult.created_at)
    ).all() if execution_ids else []
    step_execution_agent_threads = session.exec(
        select(StepExecutionAgentThread).where(StepExecutionAgentThread.step_execution_id.in_(execution_ids)).order_by(StepExecutionAgentThread.created_at)
    ).all() if execution_ids else []
    assignment_ids = [assignment.id for assignment in assignments]
    step_assignment_agent_threads = session.exec(
        select(StepAssignmentAgentThread).where(StepAssignmentAgentThread.step_assignment_id.in_(assignment_ids)).order_by(StepAssignmentAgentThread.created_at)
    ).all() if assignment_ids else []
    plan_agent_threads = session.exec(
        select(PlanAgentThread).where(PlanAgentThread.plan_id == plan.id).order_by(PlanAgentThread.created_at)
    ).all()
    agent_thread_ids = {
        link.agent_thread_id
        for link in [*step_execution_agent_threads, *step_assignment_agent_threads, *plan_agent_threads]
    }
    agent_threads = session.exec(
        select(AgentThread).where(AgentThread.id.in_(list(agent_thread_ids))).order_by(AgentThread.updated_at.desc())
    ).all() if agent_thread_ids else []
    agent_runs = session.exec(
        select(AgentRun).where(AgentRun.agent_thread_id.in_(list(agent_thread_ids))).order_by(AgentRun.created_at.desc())
    ).all() if agent_thread_ids else []
    return {
        "plan": _plan_payload(plan),
        "steps": steps,
        "step_types": session.exec(select(StepType).order_by(StepType.name)).all(),
        "assignments": assignments,
        "dependencies": dependencies,
        "repositories": repositories,
        "step_repositories": step_repositories,
        "executions": executions,
        "commits": commits,
        "script_steps": script_steps,
        "command_steps": command_steps,
        "script_results": script_results,
        "command_results": command_results,
        "step_execution_agent_threads": step_execution_agent_threads,
        "step_assignment_agent_threads": step_assignment_agent_threads,
        "agent_threads": agent_threads,
        "agent_runs": agent_runs,
        "eligible_step_ids": [step.id for step in _eligible_steps(steps, dependencies)],
    }


@router.put("/{plan_id}/repositories")
def set_plan_repositories(
    plan_id: str,
    payload: PlanRepositorySelection,
    session: Session = Depends(get_session),
) -> dict:
    plan = get_or_404(session, Plan, plan_id)
    _ensure_plan_editable(plan)
    existing = session.exec(select(PlanRepository).where(PlanRepository.plan_id == plan.id)).all()
    by_repo = {item.repository_id: item for item in existing}
    requested_ids = {item.repository_id for item in payload.repositories}
    for item in existing:
        if item.repository_id not in requested_ids and item.status != "ready":
            session.delete(item)
    for item in payload.repositories:
        repository = get_or_404(session, GitRepository, item.repository_id)
        membership = by_repo.get(repository.id)
        start_ref = item.start_ref or repository.default_branch
        if membership:
            membership.start_ref = start_ref
            membership.updated_at = utcnow()
        else:
            membership = PlanRepository(
                plan_id=plan.id,
                repository_id=repository.id,
                start_ref=start_ref,
            )
        session.add(membership)
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()
    return {"success": True, "repositories": session.exec(select(PlanRepository).where(PlanRepository.plan_id == plan.id)).all()}


@router.post("/{plan_id}/approve")
def approve_plan(plan_id: str, session: Session = Depends(get_session)) -> dict:
    plan = get_or_404(session, Plan, plan_id)
    if plan.status not in {"draft", "awaiting_review"}:
        raise ValueError("only draft or awaiting_review plans can be approved")
    memberships = session.exec(select(PlanRepository).where(PlanRepository.plan_id == plan.id)).all()
    for membership in memberships:
        repository = get_or_404(session, GitRepository, membership.repository_id)
        create_plan_checkout(session, repository, plan.id, membership.start_ref)
    plan.status = "approved"
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()
    return {"success": True, "plan": _plan_payload(plan), "eligible_step_ids": [step.id for step in _eligible_steps_for_plan(session, plan.id)]}


@router.get("/{plan_id}/eligible-steps")
def eligible_steps(plan_id: str, session: Session = Depends(get_session)) -> dict:
    get_or_404(session, Plan, plan_id)
    return {"step_ids": [step.id for step in _eligible_steps_for_plan(session, plan_id)]}


@router.post("/{plan_id}/start-steps")
def start_steps(
    plan_id: str,
    payload: StepExecutionStart,
    session: Session = Depends(get_session),
) -> dict:
    plan = get_or_404(session, Plan, plan_id)
    eligible = _eligible_steps_for_plan(session, plan.id)
    requested = payload.step_ids or [step.id for step in eligible]
    executions: list[StepExecution] = []
    executions.extend(
        _start_requested_steps(
            session,
            plan,
            requested,
            eligible,
            payload.orchestrator_agent_thread_id,
            payload.worker_agent_thread_ids,
            payload.worker_agent_thread_ids_by_step_id,
            enforce_execution_mode=True,
        )
    )
    return {"success": True, "executions": [_execution_payload(execution) for execution in executions]}


@router.post("/{plan_id}/advance")
def advance_plan(
    plan_id: str,
    payload: PlanAdvance = PlanAdvance(),
    session: Session = Depends(get_session),
) -> dict:
    plan = get_or_404(session, Plan, plan_id)
    all_executions: list[StepExecution] = []
    stop_reason = "no_ready_steps"
    human_step_ids: list[str] = []
    waiting_step_ids: list[str] = []
    if plan.status == "draft":
        memberships = session.exec(select(PlanRepository).where(PlanRepository.plan_id == plan.id)).all()
        for membership in memberships:
            repository = get_or_404(session, GitRepository, membership.repository_id)
            create_plan_checkout(session, repository, plan.id, membership.start_ref)
        plan.status = "approved"
        plan.updated_at = utcnow()
        session.add(plan)
        session.commit()
    while True:
        if _running_steps_for_plan(session, plan.id):
            stop_reason = "running"
            break
        blocked = _blocked_steps_for_plan(session, plan.id)
        if blocked:
            stop_reason = "blocked"
            waiting_step_ids = [step.id for step in blocked]
            plan.status = "awaiting_review"
            plan.updated_at = utcnow()
            session.add(plan)
            session.commit()
            break
        failed = _failed_steps_for_plan(session, plan.id)
        if failed:
            stop_reason = "failed"
            waiting_step_ids = [step.id for step in failed]
            plan.status = "failed"
            plan.updated_at = utcnow()
            session.add(plan)
            session.commit()
            break
        eligible = _eligible_steps_for_plan(session, plan.id)
        if not eligible:
            if _pending_steps_for_plan(session, plan.id):
                plan.status = "awaiting_review"
                stop_reason = "waiting_dependencies"
            else:
                plan.status = "completed"
                stop_reason = "completed"
            plan.updated_at = utcnow()
            session.add(plan)
            session.commit()
            break
        human_steps = [step for step in eligible if _step_responsible(session, step) == "human"]
        if human_steps:
            human_step_ids = [step.id for step in human_steps]
            plan.status = "awaiting_review"
            plan.updated_at = utcnow()
            session.add(plan)
            session.commit()
            stop_reason = "needs_human"
            break
        runnable = [step.id for step in eligible]
        started = _start_requested_steps(
            session,
            plan,
            runnable,
            eligible,
            payload.orchestrator_agent_thread_id,
            [],
            payload.worker_agent_thread_ids_by_step_id,
            enforce_execution_mode=True,
        )
        all_executions.extend(started)
        if _running_steps_for_plan(session, plan.id):
            stop_reason = "running"
            break
    session.refresh(plan)
    return {
        "success": True,
        "plan": _plan_payload(plan),
        "executions": [_execution_payload(execution) for execution in all_executions],
        "eligible_step_ids": [step.id for step in _eligible_steps_for_plan(session, plan.id)],
        "stop_reason": stop_reason,
        "human_step_ids": human_step_ids,
        "waiting_step_ids": waiting_step_ids,
    }


@router.post("/{plan_id}/steps/{step_id}/complete-human")
def complete_human_step(
    plan_id: str,
    step_id: str,
    payload: HumanStepComplete,
    session: Session = Depends(get_session),
) -> dict:
    plan = get_or_404(session, Plan, plan_id)
    step = get_or_404(session, Step, step_id)
    if step.plan_id != plan.id:
        raise ValueError("step does not belong to plan")
    if step.status != "pending":
        raise ValueError("only pending human steps can be completed")
    if _step_responsible(session, step) != "human":
        raise ValueError("only human steps can be completed by the user")
    eligible_step_ids = {item.id for item in _eligible_steps_for_plan(session, plan.id)}
    if step.id not in eligible_step_ids:
        raise ValueError("only eligible human steps can be completed")
    result_md = payload.result_md.strip() or "Human review completed."
    execution = StepExecution(
        step_id=step.id,
        status="completed",
        result_md=result_md,
        finished_at=utcnow(),
        updated_at=utcnow(),
    )
    step.status = "completed"
    step.result_md = result_md
    step.updated_at = utcnow()
    session.add(execution)
    session.add(step)
    session.add(plan)
    session.commit()
    session.refresh(execution)
    _sync_plan_status(session, plan)
    return {"success": True, "execution": _execution_payload(execution), "plan": _plan_payload(plan)}


@router.post("/executions/{execution_id}/complete")
def complete_step_execution(
    execution_id: str,
    payload: StepExecutionComplete,
    session: Session = Depends(get_session),
) -> dict:
    execution = get_or_404(session, StepExecution, execution_id)
    step = get_or_404(session, Step, execution.step_id)
    plan = get_or_404(session, Plan, step.plan_id)
    step_repo_links = session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all()
    required_repo_ids = {item.repository_id for item in step_repo_links}
    commits = payload.commits
    commit_repo_ids = {item.get("repository_id", "") for item in commits}
    if _step_requires_commits(session, step):
        if required_repo_ids and not required_repo_ids.issubset(commit_repo_ids):
            raise ValueError("programming steps require one recorded commit for each affected repository")
        if not required_repo_ids and not commits:
            raise ValueError("programming steps require at least one recorded commit")
    _ensure_recorded_commit_worktrees_clean(session, plan.id, commit_repo_ids)
    for item in commits:
        repository_id = item.get("repository_id", "")
        commit_sha = item.get("commit_sha", "")
        if not repository_id or not commit_sha:
            raise ValueError("commit records require repository_id and commit_sha")
        get_or_404(session, GitRepository, repository_id)
        session.add(
            StepCommit(
                step_execution_id=execution.id,
                step_id=step.id,
                repository_id=repository_id,
                commit_sha=commit_sha,
                commit_message=item.get("commit_message", ""),
            )
        )
    execution.status = payload.status
    execution.result_md = payload.result_md
    execution.finished_at = utcnow()
    execution.updated_at = utcnow()
    step.status = payload.status
    step.result_md = payload.result_md
    if commits:
        step.git_commit = commits[-1].get("commit_sha")
    step.updated_at = utcnow()
    session.add(execution)
    session.add(step)
    session.add(plan)
    session.commit()
    _sync_plan_status(session, plan)
    return {"success": True, "execution": _execution_payload(execution), "plan": _plan_payload(plan)}


@router.post("/executions/{execution_id}/block")
def block_step_execution(
    execution_id: str,
    payload: StepExecutionBlock,
    session: Session = Depends(get_session),
) -> dict:
    execution = get_or_404(session, StepExecution, execution_id)
    step = get_or_404(session, Step, execution.step_id)
    plan = get_or_404(session, Plan, step.plan_id)
    if step.status != "running":
        raise ValueError("only running steps can be blocked")
    execution.status = "blocked"
    execution.result_md = payload.reason_md
    execution.updated_at = utcnow()
    step.status = "blocked"
    step.result_md = payload.reason_md
    step.updated_at = utcnow()
    plan.status = "awaiting_review"
    plan.updated_at = utcnow()
    session.add(execution)
    session.add(step)
    session.add(plan)
    session.commit()
    return {"success": True, "execution": _execution_payload(execution), "plan": _plan_payload(plan)}


@router.post("/executions/{execution_id}/resume")
def resume_step_execution(
    execution_id: str,
    payload: StepExecutionResume,
    session: Session = Depends(get_session),
) -> dict:
    execution = get_or_404(session, StepExecution, execution_id)
    step = get_or_404(session, Step, execution.step_id)
    plan = get_or_404(session, Plan, step.plan_id)
    if step.status != "blocked":
        raise ValueError("only blocked steps can be resumed")
    note = payload.resume_message_md.strip()
    if not note:
        raise ValueError("resume message is required")
    previous = execution.result_md.strip()
    execution.result_md = f"{previous}\n\nResume guidance:\n{note}".strip()
    execution.status = "running"
    execution.updated_at = utcnow()
    step.status = "running"
    step.result_md = execution.result_md
    step.updated_at = utcnow()
    plan.status = "running"
    plan.updated_at = utcnow()
    session.add(execution)
    session.add(step)
    session.add(plan)
    session.commit()
    return {"success": True, "execution": _execution_payload(execution), "plan": _plan_payload(plan)}


@router.get("/{plan_id}/chats")
def list_plan_chats(plan_id: str, session: Session = Depends(get_session)) -> list[ChatThread]:
    get_or_404(session, Plan, plan_id)
    links = session.exec(
        select(PlanChatThread).where(PlanChatThread.plan_id == plan_id).order_by(PlanChatThread.created_at.desc())
    ).all()
    if not links:
        return []
    chat_ids = [link.chat_thread_id for link in links]
    chats = session.exec(select(ChatThread).where(ChatThread.id.in_(chat_ids))).all()
    by_id = {chat.id: chat for chat in chats}
    return [by_id[link.chat_thread_id] for link in links if link.chat_thread_id in by_id]


@router.post("/{plan_id}/chats")
def create_plan_chat(plan_id: str, session: Session = Depends(get_session)) -> ChatThread:
    plan = get_or_404(session, Plan, plan_id)
    chat = ChatThread(thread_type="planChatOrchestrator", title=plan.name)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    session.add(PlanChatThread(plan_id=plan.id, chat_thread_id=chat.id))
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()
    session.refresh(chat)
    return chat


@router.post("/{plan_id}/steps")
def create_step(
    plan_id: str,
    payload: StepCreate,
    session: Session = Depends(get_session),
) -> Step:
    plan = get_or_404(session, Plan, plan_id)
    _ensure_plan_editable(plan)
    step_type = _resolve_step_type(session, payload.step_type_id)
    position = payload.position
    if position is None:
        existing = session.exec(select(Step).where(Step.plan_id == plan.id)).all()
        position = len(existing)
    step = Step(
        plan_id=plan.id,
        step_type_id=payload.step_type_id,
        name=payload.name,
        description=payload.description,
        kind=_legacy_kind_for_step_type(step_type),
        position=position,
    )
    session.add(step)
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()
    session.refresh(step)
    _assert_no_dependency_cycle(session, plan.id, step.id, payload.depends_on_step_ids)
    for dependency_id in payload.depends_on_step_ids:
        dependency = get_or_404(session, Step, dependency_id)
        if dependency.plan_id != plan.id:
            raise ValueError("dependency step does not belong to plan")
        session.add(StepDependency(step_id=step.id, depends_on_step_id=dependency_id))
    for repository_id in payload.repository_ids:
        get_or_404(session, GitRepository, repository_id)
        session.add(StepRepository(step_id=step.id, repository_id=repository_id))
    if payload.script_id:
        _set_script_step(session, step, payload.script_id, payload.script_args_text)
    if payload.command_text:
        _set_command_step(session, step, payload.command_text, payload.command_timeout_seconds)
    _validate_step_contract(session, step)
    session.commit()
    session.refresh(step)
    return step


@router.patch("/{plan_id}/steps/{step_id}")
def update_step(
    plan_id: str,
    step_id: str,
    payload: StepUpdate,
    session: Session = Depends(get_session),
) -> Step:
    plan = get_or_404(session, Plan, plan_id)
    _ensure_plan_editable(plan)
    step = get_or_404(session, Step, step_id)
    if step.plan_id != plan.id:
        raise ValueError("step does not belong to plan")
    _ensure_step_mutable(step)
    updates = payload.model_dump(exclude_unset=True)
    if "step_type_id" in updates:
        step_type = _resolve_step_type(session, updates["step_type_id"])
        step.step_type_id = step_type.id
        step.kind = _legacy_kind_for_step_type(step_type)
    for key in ("name", "description", "position"):
        if key in updates and updates[key] is not None:
            setattr(step, key, updates[key])
    if payload.depends_on_step_ids is not None:
        _assert_no_dependency_cycle(session, plan.id, step.id, payload.depends_on_step_ids)
        for dependency in session.exec(select(StepDependency).where(StepDependency.step_id == step.id)).all():
            session.delete(dependency)
        for dependency_id in payload.depends_on_step_ids:
            dependency = get_or_404(session, Step, dependency_id)
            if dependency.plan_id != plan.id:
                raise ValueError("dependency step does not belong to plan")
            session.add(StepDependency(step_id=step.id, depends_on_step_id=dependency_id))
    if payload.repository_ids is not None:
        for link in session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all():
            session.delete(link)
        for repository_id in payload.repository_ids:
            get_or_404(session, GitRepository, repository_id)
            session.add(StepRepository(step_id=step.id, repository_id=repository_id))
    if "script_id" in updates:
        _set_script_step(session, step, payload.script_id, payload.script_args_text)
    elif "script_args_text" in updates:
        _set_script_step(session, step, None, payload.script_args_text)
    if "command_text" in updates or "command_timeout_seconds" in updates:
        _set_command_step(session, step, payload.command_text, payload.command_timeout_seconds)
    _validate_step_contract(session, step)
    step.updated_at = utcnow()
    plan.updated_at = utcnow()
    session.add(step)
    session.add(plan)
    session.commit()
    session.refresh(step)
    return step


@router.delete("/{plan_id}/steps/{step_id}", status_code=204)
def delete_step(
    plan_id: str,
    step_id: str,
    session: Session = Depends(get_session),
) -> None:
    plan = get_or_404(session, Plan, plan_id)
    _ensure_plan_editable(plan)
    step = get_or_404(session, Step, step_id)
    if step.plan_id != plan.id:
        raise ValueError("step does not belong to plan")
    _ensure_step_mutable(step)
    executions = session.exec(select(StepExecution).where(StepExecution.step_id == step.id)).all()
    execution_ids = [execution.id for execution in executions]
    command_steps = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).all()
    command_step_ids = [link.id for link in command_steps]
    if execution_ids:
        for link in session.exec(
            select(StepExecutionAgentThread).where(StepExecutionAgentThread.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(link)
        for commit in session.exec(select(StepCommit).where(StepCommit.step_execution_id.in_(execution_ids))).all():
            session.delete(commit)
        for result in session.exec(
            select(ScriptExecutionResult).where(ScriptExecutionResult.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(result)
        for result in session.exec(
            select(CommandExecutionResult).where(CommandExecutionResult.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(result)
    if command_step_ids:
        for result in session.exec(
            select(CommandExecutionResult).where(CommandExecutionResult.command_step_id.in_(command_step_ids))
        ).all():
            session.delete(result)
    for result in session.exec(select(ScriptExecutionResult).where(ScriptExecutionResult.step_id == step.id)).all():
        session.delete(result)
    for result in session.exec(select(CommandExecutionResult).where(CommandExecutionResult.step_id == step.id)).all():
        session.delete(result)
    for execution in executions:
        session.delete(execution)
    for link in session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all():
        session.delete(link)
    for link in session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).all():
        session.delete(link)
    for link in command_steps:
        session.delete(link)
    for dependency in session.exec(
        select(StepDependency).where(
            (StepDependency.step_id == step.id) | (StepDependency.depends_on_step_id == step.id)
        )
    ).all():
        session.delete(dependency)
    for assignment in session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all():
        session.delete(assignment)
    session.delete(step)
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()


@router.post("/assignments")
def create_assignment(
    payload: StepAssignmentCreate,
    session: Session = Depends(get_session),
) -> StepAssignment:
    step = get_or_404(session, Step, payload.step_id)
    plan = get_or_404(session, Plan, step.plan_id)
    _ensure_plan_editable(plan)
    _ensure_step_mutable(step)
    _ensure_assignment_allowed(session, step)
    assignment = StepAssignment(**payload.model_dump())
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def _ensure_plan_editable(plan: Plan) -> None:
    if plan.status == "running":
        raise ValueError("plans cannot be edited while steps are running")


def _ensure_step_mutable(step: Step) -> None:
    if step.status in {"completed", "failed", "canceled", "running", "blocked"}:
        raise ValueError("only pending steps can be edited")


def _resolve_step_type(session: Session, step_type_id: str | None) -> StepType:
    if not step_type_id:
        raise ValueError("step_type_id is required")
    return get_or_404(session, StepType, step_type_id)


def _step_type(session: Session, step: Step) -> StepType | None:
    if step.step_type_id:
        return session.get(StepType, step.step_type_id)
    return None


def _step_responsible(session: Session, step: Step) -> str:
    step_type = _step_type(session, step)
    if step_type and step_type.responsible:
        return step_type.responsible
    return "agent"


def _legacy_kind_for_step_type(step_type: StepType) -> str:
    if step_type.name.lower() == "review" or step_type.responsible == "human":
        return "review"
    return "programming"


def _step_requires_commits(session: Session, step: Step) -> bool:
    step_type = _step_type(session, step)
    return bool(step_type and step_type.name.lower() == "programming")


def _set_script_step(session: Session, step: Step, script_id: str | None, args_text: str | None = None) -> None:
    existing = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).all()
    if script_id:
        get_or_404(session, Script, script_id)
        for link in existing:
            session.delete(link)
        session.add(ScriptStep(step_id=step.id, script_id=script_id, args_text=args_text or ""))
        return
    if args_text is not None and existing:
        for link in existing:
            link.args_text = args_text
            session.add(link)
        return
    for link in existing:
        session.delete(link)


def _set_command_step(
    session: Session,
    step: Step,
    command_text: str | None,
    timeout_seconds: int | None = None,
) -> None:
    existing = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
    if command_text is None and timeout_seconds is None:
        return
    text = command_text if command_text is not None else (existing.command_text if existing else "")
    timeout = timeout_seconds if timeout_seconds is not None else (existing.timeout_seconds if existing else 600)
    if timeout < 1:
        raise ValueError("command timeout must be at least 1 second")
    if not text.strip():
        if existing:
            session.delete(existing)
        return
    if existing:
        existing.command_text = text
        existing.timeout_seconds = timeout
        existing.updated_at = utcnow()
        session.add(existing)
    else:
        session.add(CommandStep(step_id=step.id, command_text=text, timeout_seconds=timeout))


def _validate_step_contract(session: Session, step: Step) -> None:
    if not step.step_type_id:
        raise ValueError("step_type_id is required")
    responsible = _step_responsible(session, step)
    script_link = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).first()
    command_link = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
    if responsible == "script" and not script_link:
        raise ValueError("script steps require a script")
    if responsible != "script" and script_link:
        raise ValueError("only script steps can reference a script")
    if responsible == "command" and not command_link:
        raise ValueError("command steps require a command")
    if responsible != "command" and command_link:
        raise ValueError("only command steps can reference a command")


def _ensure_assignment_allowed(session: Session, step: Step) -> None:
    responsible = _step_responsible(session, step)
    if responsible in {"human", "script", "command"}:
        raise ValueError(f"{responsible} steps cannot have agent assignments")
    if responsible == "agent":
        existing = session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all()
        if existing:
            raise ValueError("agent steps can have exactly one assignment")


def _start_requested_steps(
    session: Session,
    plan: Plan,
    requested_step_ids: list[str],
    eligible_steps: list[Step],
    orchestrator_agent_thread_id: str | None,
    fallback_worker_agent_thread_ids: list[str],
    worker_agent_thread_ids_by_step_id: dict[str, list[str]],
    *,
    enforce_execution_mode: bool,
) -> list[StepExecution]:
    if plan.status not in {"approved", "awaiting_review"}:
        raise ValueError("plan must be approved before steps can start")
    running = _running_steps_for_plan(session, plan.id)
    if running:
        raise ValueError("plan already has running steps")
    requested = list(requested_step_ids)
    if not requested:
        raise ValueError("no eligible steps are ready to run")
    if enforce_execution_mode and plan.execution_mode == "sequential" and len(requested) > 1:
        requested = requested[:1]
    eligible = {step.id for step in eligible_steps}
    invalid = [step_id for step_id in requested if step_id not in eligible]
    if invalid:
        raise ValueError("only eligible pending steps can start")
    executions: list[StepExecution] = []
    for step_id in requested:
        step = get_or_404(session, Step, step_id)
        _validate_step_ready_to_start(session, step)
        responsible = _step_responsible(session, step)
        if responsible == "human":
            raise ValueError("human steps must be completed by the user before automated execution can continue")
        step_worker_thread_ids = (
            worker_agent_thread_ids_by_step_id.get(step.id)
            or fallback_worker_agent_thread_ids
        )
        step.status = "running"
        step.updated_at = utcnow()
        execution = StepExecution(step_id=step.id, orchestrator_agent_thread_id=orchestrator_agent_thread_id)
        session.add(step)
        session.add(execution)
        session.commit()
        session.refresh(execution)
        if responsible == "script":
            _run_script_step(session, plan, step, execution)
            session.refresh(execution)
            session.refresh(step)
        elif responsible == "command":
            _run_command_step(session, plan, step, execution)
            session.refresh(execution)
            session.refresh(step)
        else:
            if not step_worker_thread_ids:
                assignments = session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all()
                try:
                    for assignment in assignments:
                        step_worker_thread_ids.append(
                            start_worker_for_assignment(
                                session,
                                plan=plan,
                                step=step,
                                assignment=assignment,
                                execution=execution,
                            )
                        )
                except Exception as error:
                    failure = f"Agent runtime failed to start: {error}"
                    execution.status = "failed"
                    execution.result_md = failure
                    execution.finished_at = utcnow()
                    execution.updated_at = utcnow()
                    step.status = "failed"
                    step.result_md = failure
                    step.updated_at = utcnow()
                    session.add(execution)
                    session.add(step)
                    _sync_plan_status(session, plan)
                    session.commit()
                    raise
            else:
                for thread_id in step_worker_thread_ids:
                    get_or_404(session, AgentThread, thread_id)
                    session.add(
                        StepExecutionAgentThread(
                            step_execution_id=execution.id,
                            agent_thread_id=thread_id,
                            role="worker",
                        )
                    )
            session.commit()
        executions.append(execution)
    _sync_plan_status(session, plan)
    return executions


def _validate_step_ready_to_start(session: Session, step: Step) -> None:
    if not step.step_type_id:
        raise ValueError("steps require a step type before start")
    responsible = _step_responsible(session, step)
    assignments = session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all()
    script_link = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).first()
    command_link = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
    if responsible == "agent" and len(assignments) != 1:
        raise ValueError("agent steps require exactly one assignment before start")
    if responsible == "multiagents" and not assignments:
        raise ValueError("multiagents steps require at least one assignment before start")
    if responsible in {"human", "script", "command"} and assignments:
        raise ValueError(f"{responsible} steps cannot have agent assignments")
    if responsible == "script" and not script_link:
        raise ValueError("script steps require a script before start")
    if responsible == "command" and not command_link:
        raise ValueError("command steps require a command before start")


def _sync_plan_status(session: Session, plan: Plan) -> None:
    if _running_steps_for_plan(session, plan.id):
        plan.status = "running"
    elif _blocked_steps_for_plan(session, plan.id):
        plan.status = "awaiting_review"
    elif _failed_steps_for_plan(session, plan.id):
        plan.status = "failed"
    elif _pending_steps_for_plan(session, plan.id):
        plan.status = "awaiting_review"
    else:
        plan.status = "completed"
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()


def _run_script_step(session: Session, plan: Plan, step: Step, execution: StepExecution) -> None:
    try:
        script_link = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).first()
        if not script_link:
            raise ValueError("script steps require a script")
        script = get_or_404(session, Script, script_link.script_id)
        command_for_script(script)
        parse_script_args(script_link.args_text)
        repository_links = session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all()
        if not repository_links:
            raise ValueError("script steps require at least one repository")
        for link in repository_links:
            membership = session.exec(
                select(PlanRepository).where(
                    PlanRepository.plan_id == plan.id,
                    PlanRepository.repository_id == link.repository_id,
                )
            ).first()
            if not membership or not membership.checkout_path:
                raise ValueError("script steps require prepared plan checkouts for all selected repositories")
            path = Path(membership.checkout_path)
            if not path.exists():
                raise ValueError("script step checkout path is missing")
            repository = get_or_404(session, GitRepository, link.repository_id)
            session.add(
                ScriptExecutionResult(
                    step_execution_id=execution.id,
                    step_id=step.id,
                    script_id=script.id,
                    repository_id=repository.id,
                    cwd=str(path),
                    status="running",
                )
            )
        session.commit()
        _start_execution_worker(_complete_script_step, execution.id)
    except Exception as error:
        _fail_step_execution(session, plan, step, execution, str(error))


def _run_command_step(session: Session, plan: Plan, step: Step, execution: StepExecution) -> None:
    try:
        command_step = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
        if not command_step:
            raise ValueError("command steps require a command")
        command_text = command_step.command_text.strip()
        if not command_text:
            raise ValueError("command step requires a command")
        repository_links = session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all()
        if not repository_links:
            raise ValueError("command steps require at least one repository")
        for link in repository_links:
            membership = session.exec(
                select(PlanRepository).where(
                    PlanRepository.plan_id == plan.id,
                    PlanRepository.repository_id == link.repository_id,
                )
            ).first()
            if not membership or not membership.checkout_path:
                raise ValueError("command steps require prepared plan checkouts for all selected repositories")
            path = Path(membership.checkout_path)
            if not path.exists():
                raise ValueError("command step checkout path is missing")
            repository = get_or_404(session, GitRepository, link.repository_id)
            session.add(
                CommandExecutionResult(
                    step_execution_id=execution.id,
                    step_id=step.id,
                    command_step_id=command_step.id,
                    repository_id=repository.id,
                    cwd=str(path),
                    command_text=command_text,
                    status="running",
                )
            )
        session.commit()
        _start_execution_worker(_complete_command_step, execution.id)
    except Exception as error:
        _fail_step_execution(session, plan, step, execution, str(error))


def _start_execution_worker(target, execution_id: str) -> None:
    thread = threading.Thread(target=target, args=(execution_id,), daemon=True)
    thread.start()


def _complete_script_step(execution_id: str) -> None:
    with Session(engine) as session:
        execution = session.get(StepExecution, execution_id)
        if not execution:
            return
        step = session.get(Step, execution.step_id)
        if not step:
            return
        plan = session.get(Plan, step.plan_id)
        if not plan:
            return
        results = session.exec(
            select(ScriptExecutionResult)
            .where(ScriptExecutionResult.step_execution_id == execution.id)
            .order_by(ScriptExecutionResult.created_at)
        ).all()
        failed = False
        for result in results:
            script = session.get(Script, result.script_id)
            repository = session.get(GitRepository, result.repository_id)
            if not script or not repository:
                _finish_script_result(session, result, "failed", None, "Script or repository is missing.")
                failed = True
                continue
            try:
                script_link = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).first()
                args_text = script_link.args_text if script_link else ""
                command = [*command_for_script(script), *parse_script_args(args_text)]
                process = subprocess.Popen(
                    command,
                    cwd=result.cwd,
                    env=environment_for_script(script, execution, repository, Path(result.cwd)),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                timed_out = threading.Event()
                timer = _kill_after_timeout(process, 600, timed_out)
                try:
                    _stream_process_output(process, ScriptExecutionResult, result.id)
                finally:
                    timer.cancel()
                status = "completed" if process.returncode == 0 else "failed"
                error = "\nScript timed out after 600 seconds." if timed_out.is_set() else ""
                _finish_script_result(session, result, status, process.returncode, error)
                failed = failed or status != "completed"
            except Exception as error:
                _finish_script_result(session, result, "failed", None, str(error))
                failed = True
        _finish_step_execution(session, plan, step, execution, failed, "Script")


def _complete_command_step(execution_id: str) -> None:
    with Session(engine) as session:
        execution = session.get(StepExecution, execution_id)
        if not execution:
            return
        step = session.get(Step, execution.step_id)
        if not step:
            return
        plan = session.get(Plan, step.plan_id)
        if not plan:
            return
        results = session.exec(
            select(CommandExecutionResult)
            .where(CommandExecutionResult.step_execution_id == execution.id)
            .order_by(CommandExecutionResult.created_at)
        ).all()
        failed = False
        for result in results:
            command_step = session.get(CommandStep, result.command_step_id)
            if not command_step:
                _finish_command_result(session, result, "failed", None, "Command step is missing.")
                failed = True
                continue
            try:
                process = subprocess.Popen(
                    result.command_text,
                    cwd=result.cwd,
                    shell=True,
                    executable=command_step.shell or "/bin/sh",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                timed_out = threading.Event()
                timer = _kill_after_timeout(process, command_step.timeout_seconds, timed_out)
                try:
                    _stream_process_output(process, CommandExecutionResult, result.id)
                finally:
                    timer.cancel()
                status = "completed" if process.returncode == 0 else "failed"
                error = (
                    f"\nCommand timed out after {command_step.timeout_seconds} seconds."
                    if timed_out.is_set()
                    else ""
                )
                _finish_command_result(session, result, status, process.returncode, error)
                failed = failed or status != "completed"
            except Exception as error:
                _finish_command_result(session, result, "failed", None, str(error))
                failed = True
        _finish_step_execution(session, plan, step, execution, failed, "Command")


def _kill_after_timeout(process: subprocess.Popen[str], timeout_seconds: int, timed_out: threading.Event) -> threading.Timer:
    def kill() -> None:
        if process.poll() is None:
            timed_out.set()
            process.kill()

    timer = threading.Timer(timeout_seconds, kill)
    timer.start()
    return timer


def _stream_process_output(process: subprocess.Popen[str], model, result_id: str) -> None:
    readers: list[threading.Thread] = []
    for field, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        if stream is None:
            continue
        reader = threading.Thread(target=_read_stream, args=(model, result_id, field, stream), daemon=True)
        reader.start()
        readers.append(reader)
    process.wait()
    for reader in readers:
        reader.join(timeout=1)


def _read_stream(model, result_id: str, field: str, stream: TextIO) -> None:
    try:
        for chunk in iter(stream.readline, ""):
            if chunk:
                _append_result_output(model, result_id, field, chunk)
    finally:
        stream.close()


def _append_result_output(model, result_id: str, field: str, chunk: str) -> None:
    with Session(engine) as session:
        result = session.get(model, result_id)
        if not result:
            return
        setattr(result, field, append_truncated(getattr(result, field), chunk))
        result.updated_at = utcnow()
        session.add(result)
        session.commit()


def _finish_script_result(
    session: Session,
    result: ScriptExecutionResult,
    status: str,
    exit_code: int | None,
    stderr_suffix: str,
) -> None:
    result.status = status
    result.exit_code = exit_code
    if stderr_suffix:
        result.stderr = append_truncated(result.stderr, stderr_suffix)
    result.finished_at = utcnow()
    result.updated_at = utcnow()
    session.add(result)
    session.commit()


def _finish_command_result(
    session: Session,
    result: CommandExecutionResult,
    status: str,
    exit_code: int | None,
    stderr_suffix: str,
) -> None:
    result.status = status
    result.exit_code = exit_code
    if stderr_suffix:
        result.stderr = append_truncated(result.stderr, stderr_suffix)
    result.finished_at = utcnow()
    result.updated_at = utcnow()
    session.add(result)
    session.commit()


def _finish_step_execution(
    session: Session,
    plan: Plan,
    step: Step,
    execution: StepExecution,
    failed: bool,
    label: str,
) -> None:
    execution.status = "failed" if failed else "completed"
    execution.result_md = f"{label} failed." if failed else f"{label} completed."
    execution.finished_at = utcnow()
    execution.updated_at = utcnow()
    step.status = execution.status
    step.result_md = execution.result_md
    step.updated_at = utcnow()
    session.add(execution)
    session.add(step)
    session.commit()
    _sync_plan_status(session, plan)


def _fail_step_execution(
    session: Session,
    plan: Plan,
    step: Step,
    execution: StepExecution,
    message: str,
) -> None:
    execution.status = "failed"
    execution.result_md = message
    execution.finished_at = utcnow()
    execution.updated_at = utcnow()
    step.status = "failed"
    step.result_md = message
    step.updated_at = utcnow()
    plan.status = "failed"
    plan.updated_at = utcnow()
    session.add(execution)
    session.add(step)
    session.add(plan)
    session.commit()


def _assert_no_dependency_cycle(session: Session, plan_id: str, step_id: str, depends_on_step_ids: list[str]) -> None:
    steps = session.exec(select(Step).where(Step.plan_id == plan_id)).all()
    step_ids = {step.id for step in steps}
    dependencies = session.exec(select(StepDependency).where(StepDependency.step_id.in_(list(step_ids)))).all() if step_ids else []
    graph: dict[str, set[str]] = {item.id: set() for item in steps}
    for dependency in dependencies:
        if dependency.step_id != step_id:
            graph.setdefault(dependency.step_id, set()).add(dependency.depends_on_step_id)
    graph.setdefault(step_id, set()).update(depends_on_step_ids)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dependency_id in graph.get(node, set()):
            if dependency_id == node or visit(dependency_id):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(visit(node) for node in graph):
        raise ValueError("step dependencies cannot contain cycles")


def _eligible_steps_for_plan(session: Session, plan_id: str) -> list[Step]:
    steps = session.exec(select(Step).where(Step.plan_id == plan_id).order_by(Step.position, Step.created_at)).all()
    dependencies = session.exec(select(StepDependency).where(StepDependency.step_id.in_([step.id for step in steps]))).all() if steps else []
    return _eligible_steps(steps, dependencies)


def _eligible_steps(steps: list[Step], dependencies: list[StepDependency]) -> list[Step]:
    complete = {step.id for step in steps if step.status == "completed"}
    pending = [step for step in steps if step.status == "pending"]
    by_step: dict[str, set[str]] = {}
    for dependency in dependencies:
        by_step.setdefault(dependency.step_id, set()).add(dependency.depends_on_step_id)
    return [step for step in pending if by_step.get(step.id, set()).issubset(complete)]


def _running_steps_for_plan(session: Session, plan_id: str, exclude_step_id: str | None = None) -> list[Step]:
    steps = session.exec(
        select(Step).where(Step.plan_id == plan_id, Step.status == "running")
    ).all()
    return [step for step in steps if step.id != exclude_step_id]


def _blocked_steps_for_plan(session: Session, plan_id: str) -> list[Step]:
    return session.exec(select(Step).where(Step.plan_id == plan_id, Step.status == "blocked")).all()


def _failed_steps_for_plan(session: Session, plan_id: str) -> list[Step]:
    return session.exec(select(Step).where(Step.plan_id == plan_id, Step.status == "failed")).all()


def _pending_steps_for_plan(session: Session, plan_id: str) -> list[Step]:
    return session.exec(select(Step).where(Step.plan_id == plan_id, Step.status == "pending")).all()


def _ensure_recorded_commit_worktrees_clean(session: Session, plan_id: str, repository_ids: set[str]) -> None:
    if not repository_ids:
        return
    memberships = session.exec(
        select(PlanRepository).where(
            PlanRepository.plan_id == plan_id,
            PlanRepository.repository_id.in_(repository_ids),
        )
    ).all()
    for membership in memberships:
        if not membership.checkout_path:
            continue
        path = Path(membership.checkout_path)
        if not path.exists():
            continue
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise ValueError("unable to inspect plan checkout worktree")
        if completed.stdout.strip():
            raise ValueError("programming steps require clean worktrees before completion")


def _execution_payload(execution: StepExecution) -> dict:
    return {
        "id": execution.id,
        "step_id": execution.step_id,
        "status": execution.status,
        "orchestrator_agent_thread_id": execution.orchestrator_agent_thread_id,
        "result_md": execution.result_md,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "created_at": execution.created_at.isoformat(),
        "updated_at": execution.updated_at.isoformat(),
    }


def _plan_payload(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "plan_type_id": plan.plan_type_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "execution_mode": plan.execution_mode,
        "context_md": plan.context_md,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }

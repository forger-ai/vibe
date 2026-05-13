from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.desktop_events import DesktopEventClient, DesktopEventError
from app.forger_desktop import (
    create_agent_thread as desktop_create_agent_thread,
)
from app.forger_desktop import (
    start_agent_run as desktop_start_agent_run,
)
from app.models import (
    Agent,
    AgentRun,
    AgentThread,
    GitRepository,
    Plan,
    PlanAgentThread,
    PlanRepository,
    Step,
    StepAssignment,
    StepAssignmentAgentThread,
    StepExecution,
    StepExecutionAgentThread,
    StepRepository,
    StepType,
    utcnow,
)
from app.realtime import hub
from app.services.prompt_builder import render_agent_prompt

TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}


def start_worker_for_assignment(
    session: Session,
    *,
    plan: Plan,
    step: Step,
    assignment: StepAssignment,
    execution: StepExecution | None = None,
) -> str:
    agent = session.get(Agent, assignment.agent_id)
    if not agent:
        raise ValueError("assignment agent not found")
    context = step_task_context(session, plan, step, assignment, agent)
    prompt = render_agent_prompt(session, agent, "agentStepTask", context)
    title = f"{step.name} · {agent.name}"
    workspace_path = workspace_path_for_step(session, plan, step)
    desktop_thread = desktop_create_agent_thread(
        title=title,
        manifest_agent_id="agentStepTask",
        initial_prompt=prompt,
        runtime=runtime_for_agent(agent),
        metadata={
            "vibeAgentId": agent.id,
            "planId": plan.id,
            "stepId": step.id,
            "assignmentId": assignment.id,
        },
        workspace_path=workspace_path,
    )
    stored_thread = AgentThread(
        desktop_thread_id=str(desktop_thread.get("desktop_thread_id") or ""),
        agent_id=agent.id,
        manifest_agent_id="agentStepTask",
        owner_type="agent",
        invocation_mode="step_task",
        title=title,
        initial_prompt_snapshot_md=prompt,
        status=str(desktop_thread.get("status") or "idle"),
    )
    session.add(stored_thread)
    session.commit()
    session.refresh(stored_thread)
    session.add(PlanAgentThread(plan_id=plan.id, agent_thread_id=stored_thread.id))
    session.add(StepAssignmentAgentThread(step_assignment_id=assignment.id, agent_thread_id=stored_thread.id))
    if execution:
        session.add(StepExecutionAgentThread(step_execution_id=execution.id, agent_thread_id=stored_thread.id, role="worker"))
    run = desktop_start_agent_run(
        desktop_thread_id=stored_thread.desktop_thread_id,
        message=assignment.instructions_md or step.description,
        context=json.dumps(filter_step_runtime_context(context), indent=2),
        runtime=runtime_for_agent(agent),
        workspace_path=workspace_path,
    )
    stored_run = AgentRun(
        agent_thread_id=stored_thread.id,
        desktop_run_id=str(run.get("desktop_run_id") or ""),
        trigger_type="step_task",
        trigger_id=step.id,
        status=str(run.get("status") or "queued"),
        input_md=assignment.instructions_md or step.description,
        context_snapshot_md=prompt,
        started_at=utcnow(),
    )
    stored_thread.status = "running"
    stored_thread.updated_at = utcnow()
    session.add(stored_thread)
    session.add(stored_run)
    session.commit()
    return stored_thread.id


def step_task_context(
    session: Session,
    plan: Plan,
    step: Step,
    assignment: StepAssignment,
    agent: Agent,
) -> dict[str, Any]:
    repository_ids = [
        link.repository_id
        for link in session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all()
    ]
    step_type = session.get(StepType, step.step_type_id) if step.step_type_id else None
    repositories = session.exec(select(GitRepository).where(GitRepository.id.in_(repository_ids))).all() if repository_ids else []
    return {
        "plan_id": plan.id,
        "step_id": step.id,
        "assignment": {"instructions": assignment.instructions_md},
        "agentIdentity": agent.identity_md,
        "agentTone": agent.tone_md,
        "agentGuardrails": agent.guardrails_md,
        "globalGuardrails": "",
        "plan": {
            "id": plan.id,
            "description": f"{plan.name}\n\n{plan.description}\n\n{plan.context_md}".strip(),
        },
        "step": {
            "description": "\n\n".join([
                step.name,
                step.description,
                f"step_type={step_type.name if step_type else 'unknown'}",
                f"responsible={step_type.responsible if step_type else 'unknown'}",
                f"repository_ids={', '.join(repository_ids) or 'none'}",
            ]),
        },
        "repository_ids": repository_ids,
        "repository_context": "\n".join(
            f"- {repository.name}: id={repository.id}; remote={repository.remote_url}; default_branch={repository.default_branch}"
            for repository in repositories
        ) or "No repositories selected for this step.",
        "user_message": assignment.instructions_md or step.description,
    }


def filter_step_runtime_context(context: dict[str, Any]) -> dict[str, Any]:
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    step = context.get("step") if isinstance(context.get("step"), dict) else {}
    assignment = context.get("assignment") if isinstance(context.get("assignment"), dict) else {}
    return {
        "agentIdentity": context.get("agentIdentity", ""),
        "agentTone": context.get("agentTone", ""),
        "agentGuardrails": context.get("agentGuardrails", ""),
        "globalGuardrails": context.get("globalGuardrails", ""),
        "planDescription": plan.get("description", ""),
        "stepDescription": step.get("description", ""),
        "assignmentInstructions": assignment.get("instructions", ""),
        "repositoryContext": context.get("repository_context", ""),
    }


def runtime_for_agent(agent: Agent) -> dict[str, Any]:
    if agent.provider == "auto":
        return {"provider": "auto"}
    return {
        "provider": agent.provider,
        "model": agent.model,
        "effort": agent.reasoning_effort,
        "modelParams": agent.model_params_json,
    }


def workspace_path_for_step(session: Session, plan: Plan, step: Step) -> str | None:
    links = session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all()
    for link in links:
        membership = session.exec(
            select(PlanRepository).where(
                PlanRepository.plan_id == plan.id,
                PlanRepository.repository_id == link.repository_id,
            )
        ).first()
        if membership and membership.checkout_path and Path(membership.checkout_path).exists():
            return membership.checkout_path
    return None


async def handle_desktop_event(event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    thread_id = str(event.get("thread_id") or "")
    run_id = str(event.get("run_id") or "")
    if not thread_id:
        return
    with Session(engine) as session:
        stored_thread = session.exec(select(AgentThread).where(AgentThread.desktop_thread_id == thread_id)).first()
        if not stored_thread:
            return
        run = (
            session.exec(
                select(AgentRun).where(
                    AgentRun.agent_thread_id == stored_thread.id,
                    AgentRun.desktop_run_id == run_id,
                )
            ).first()
            if run_id
            else None
        )
        if run:
            _update_run_from_event(run, event, payload)
            session.add(run)
        stored_thread.status = str(event.get("status") or stored_thread.status)
        if stored_thread.status == "completed":
            stored_thread.status = "idle"
        stored_thread.updated_at = utcnow()
        session.add(stored_thread)
        _reconcile_step_run(session, stored_thread, run, event_type, payload)
        session.commit()
        await publish_thread_channels(session, stored_thread)


def _update_run_from_event(run: AgentRun, event: dict[str, Any], payload: dict[str, Any]) -> None:
    status = str(event.get("status") or run.status)
    if status:
        run.status = status
    if event.get("type") == "assistant.message.appended":
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        run.result_md = str(message.get("content") or run.result_md)
    run.error = str((payload.get("run") or {}).get("error") or run.error or "") or None if isinstance(payload.get("run"), dict) else run.error
    if run.status in TERMINAL_RUN_STATUSES and not run.finished_at:
        run.finished_at = utcnow()
    run.updated_at = utcnow()


def _reconcile_step_run(
    session: Session,
    stored_thread: AgentThread,
    run: AgentRun | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    link = session.exec(
        select(StepExecutionAgentThread).where(StepExecutionAgentThread.agent_thread_id == stored_thread.id)
    ).first()
    if not link:
        return
    execution = session.get(StepExecution, link.step_execution_id)
    if not execution:
        return
    step = session.get(Step, execution.step_id)
    if not step:
        return
    if event_type == "assistant.message.appended":
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        result = str(message.get("content") or "")
        if result:
            execution.result_md = result
            step.result_md = result
    if run and run.status in TERMINAL_RUN_STATUSES:
        status = "completed" if run.status == "completed" else run.status
        execution.status = status
        execution.finished_at = execution.finished_at or utcnow()
        execution.updated_at = utcnow()
        step.status = status
        step.result_md = run.result_md or step.result_md or (run.error or "")
        step.updated_at = utcnow()
        for assignment in session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all():
            assignment.status = status
            assignment.updated_at = utcnow()
            session.add(assignment)
        session.add(execution)
        session.add(step)
        plan = session.get(Plan, step.plan_id)
        if plan:
            sync_plan_status(session, plan)


def sync_plan_status(session: Session, plan: Plan) -> None:
    steps = session.exec(select(Step).where(Step.plan_id == plan.id)).all()
    statuses = {step.status for step in steps}
    if "running" in statuses:
        plan.status = "running"
    elif "blocked" in statuses:
        plan.status = "awaiting_review"
    elif "failed" in statuses:
        plan.status = "failed"
    elif "pending" in statuses:
        plan.status = "awaiting_review"
    else:
        plan.status = "completed"
    plan.updated_at = utcnow()
    session.add(plan)


async def publish_thread_channels(session: Session, stored_thread: AgentThread) -> None:
    await hub.publish(f"agent_threads:{stored_thread.id}", "agent_thread.updated", {"agent_thread_id": stored_thread.id})
    plan_link = session.exec(select(PlanAgentThread).where(PlanAgentThread.agent_thread_id == stored_thread.id)).first()
    if plan_link:
        await hub.publish(f"plans:{plan_link.plan_id}", "plan.updated", {"plan_id": plan_link.plan_id})
    if stored_thread.chat_thread_id:
        await hub.publish(f"chat:{stored_thread.chat_thread_id}", "chat.updated", {"chat_thread_id": stored_thread.chat_thread_id})


def start_desktop_event_listener() -> asyncio.Task[None] | None:
    try:
        client = DesktopEventClient()
    except DesktopEventError:
        return None
    return asyncio.create_task(client.run(handle_desktop_event))

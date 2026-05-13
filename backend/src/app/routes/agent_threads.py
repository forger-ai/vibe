from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    AgentRun,
    AgentThread,
    DiscussionParticipant,
    PlanAgentThread,
    StepAssignmentAgentThread,
    utcnow,
)
from app.routes.common import get_or_404
from app.schemas import AgentRunCreate, AgentRunUpdate, AgentThreadCreate

router = APIRouter(prefix="/api/agent-threads", tags=["agent-threads"])


@router.get("")
def list_threads(session: Session = Depends(get_session)) -> list[AgentThread]:
    return session.exec(select(AgentThread).order_by(AgentThread.updated_at.desc())).all()


@router.post("")
def create_thread(
    payload: AgentThreadCreate,
    session: Session = Depends(get_session),
) -> AgentThread:
    thread = AgentThread(
        desktop_thread_id=payload.desktop_thread_id,
        agent_id=payload.agent_id,
        manifest_agent_id=payload.manifest_agent_id,
        chat_thread_id=payload.chat_thread_id,
        discussion_id=payload.discussion_id,
        owner_type=payload.owner_type,
        invocation_mode=payload.invocation_mode,
        title=payload.title,
        initial_prompt_snapshot_md=payload.initial_prompt_snapshot_md,
    )
    session.add(thread)
    session.commit()
    session.refresh(thread)
    if payload.plan_id:
        session.add(PlanAgentThread(plan_id=payload.plan_id, agent_thread_id=thread.id))
    if payload.discussion_id and payload.agent_id:
        participant = session.exec(
            select(DiscussionParticipant).where(
                DiscussionParticipant.discussion_id == payload.discussion_id,
                DiscussionParticipant.agent_id == payload.agent_id,
            )
        ).first()
        if participant:
            participant.agent_thread_id = thread.id
            participant.updated_at = utcnow()
            session.add(participant)
    if payload.step_assignment_id:
        session.add(
            StepAssignmentAgentThread(
                step_assignment_id=payload.step_assignment_id,
                agent_thread_id=thread.id,
            )
        )
    session.commit()
    session.refresh(thread)
    return thread


@router.get("/{thread_id}/runs")
def list_runs(thread_id: str, session: Session = Depends(get_session)) -> list[AgentRun]:
    return session.exec(
        select(AgentRun)
        .where(AgentRun.agent_thread_id == thread_id)
        .order_by(AgentRun.created_at.desc())
    ).all()


@router.post("/runs")
def create_run(payload: AgentRunCreate, session: Session = Depends(get_session)) -> AgentRun:
    run = AgentRun(**payload.model_dump(), started_at=utcnow())
    thread = get_or_404(session, AgentThread, payload.agent_thread_id)
    thread.status = "running"
    thread.updated_at = utcnow()
    session.add(thread)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


@router.patch("/runs/{run_id}")
def update_run(
    run_id: str,
    payload: AgentRunUpdate,
    session: Session = Depends(get_session),
) -> AgentRun:
    run = get_or_404(session, AgentRun, run_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(run, key, value)
    run.updated_at = utcnow()
    if payload.status in {"completed", "failed", "canceled"}:
        run.finished_at = payload.finished_at or utcnow()
        thread = session.get(AgentThread, run.agent_thread_id)
        if thread:
            thread.status = "idle" if payload.status == "completed" else payload.status
            thread.updated_at = utcnow()
            session.add(thread)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run

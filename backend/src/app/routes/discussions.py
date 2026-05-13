from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Agent,
    Discussion,
    DiscussionMessage,
    DiscussionParticipant,
    utcnow,
)
from app.routes.common import get_or_404
from app.schemas import DiscussionConsensusUpdate, DiscussionCreate, DiscussionMessageCreate

router = APIRouter(prefix="/api/discussions", tags=["discussions"])


@router.get("")
def list_discussions(
    chat_thread_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    statement = select(Discussion).order_by(Discussion.updated_at.desc())
    if chat_thread_id:
        statement = statement.where(Discussion.chat_thread_id == chat_thread_id)
    return [_discussion_payload(item) for item in session.exec(statement).all()]


@router.post("")
def create_discussion(
    payload: DiscussionCreate,
    session: Session = Depends(get_session),
) -> dict:
    agent_ids = _unique_agent_ids(payload.agent_ids)
    if len(agent_ids) < 2:
        raise ValueError("a discussion requires at least two agents")
    for agent_id in agent_ids:
        get_or_404(session, Agent, agent_id)
    discussion = Discussion(
        chat_thread_id=payload.chat_thread_id,
        title=payload.title,
        objective_md=payload.objective_md,
        current_agent_id=agent_ids[0],
    )
    session.add(discussion)
    session.commit()
    session.refresh(discussion)
    for position, agent_id in enumerate(agent_ids):
        session.add(
            DiscussionParticipant(
                discussion_id=discussion.id,
                agent_id=agent_id,
                position=position,
            )
        )
    session.commit()
    return get_discussion_detail(discussion.id, session)


@router.get("/{discussion_id}")
def get_discussion_detail(
    discussion_id: str,
    session: Session = Depends(get_session),
) -> dict:
    discussion = get_or_404(session, Discussion, discussion_id)
    participants = session.exec(
        select(DiscussionParticipant)
        .where(DiscussionParticipant.discussion_id == discussion.id)
        .order_by(DiscussionParticipant.position)
    ).all()
    messages = session.exec(
        select(DiscussionMessage)
        .where(DiscussionMessage.discussion_id == discussion.id)
        .order_by(DiscussionMessage.position, DiscussionMessage.created_at)
    ).all()
    return {
        "discussion": _discussion_payload(discussion),
        "participants": [_participant_payload(item) for item in participants],
        "messages": [_message_payload(item) for item in messages],
        "next_agent_id": discussion.current_agent_id if discussion.status == "running" else None,
    }


@router.post("/{discussion_id}/messages")
def create_discussion_message(
    discussion_id: str,
    payload: DiscussionMessageCreate,
    session: Session = Depends(get_session),
) -> dict:
    if payload.discussion_id != discussion_id:
        raise ValueError("discussion_id mismatch")
    discussion = get_or_404(session, Discussion, discussion_id)
    participant = session.exec(
        select(DiscussionParticipant).where(
            DiscussionParticipant.discussion_id == discussion.id,
            DiscussionParticipant.agent_id == payload.agent_id,
        )
    ).first()
    if not participant:
        raise ValueError("agent is not a discussion participant")
    position = len(
        session.exec(
            select(DiscussionMessage).where(DiscussionMessage.discussion_id == discussion.id)
        ).all()
    )
    message = DiscussionMessage(
        discussion_id=discussion.id,
        agent_id=payload.agent_id,
        agent_thread_id=payload.agent_thread_id or participant.agent_thread_id,
        agent_run_id=payload.agent_run_id,
        content_md=payload.content_md,
        end_discussion=payload.end_discussion,
        round_index=discussion.current_round,
        position=position,
        metadata_json=payload.metadata_json,
    )
    session.add(message)
    participant.last_end_discussion = payload.end_discussion
    participant.updated_at = utcnow()
    session.add(participant)
    _advance_discussion(session, discussion, participant)
    session.commit()
    return get_discussion_detail(discussion.id, session)


@router.patch("/{discussion_id}/consensus")
def update_discussion_consensus(
    discussion_id: str,
    payload: DiscussionConsensusUpdate,
    session: Session = Depends(get_session),
) -> dict:
    discussion = get_or_404(session, Discussion, discussion_id)
    discussion.consensus_md = payload.consensus_md
    discussion.updated_at = utcnow()
    session.add(discussion)
    session.commit()
    return get_discussion_detail(discussion.id, session)


def _advance_discussion(
    session: Session,
    discussion: Discussion,
    current: DiscussionParticipant,
) -> None:
    participants = session.exec(
        select(DiscussionParticipant)
        .where(DiscussionParticipant.discussion_id == discussion.id)
        .order_by(DiscussionParticipant.position)
    ).all()
    active = [item for item in participants if item.status == "active"]
    if active and all(item.last_end_discussion for item in active):
        discussion.status = "completed"
        discussion.current_agent_id = None
        discussion.finished_at = utcnow()
        discussion.updated_at = utcnow()
        session.add(discussion)
        return
    candidates = [item for item in active if not item.last_end_discussion]
    if not candidates:
        discussion.status = "completed"
        discussion.current_agent_id = None
        discussion.finished_at = utcnow()
        discussion.updated_at = utcnow()
        session.add(discussion)
        return
    next_items = [item for item in candidates if item.position > current.position]
    if next_items:
        next_participant = next_items[0]
    else:
        next_participant = candidates[0]
        discussion.current_round += 1
    discussion.current_agent_id = next_participant.agent_id
    discussion.updated_at = utcnow()
    session.add(discussion)


def _unique_agent_ids(agent_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for agent_id in agent_ids:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        result.append(agent_id)
    return result


def _discussion_payload(discussion: Discussion) -> dict:
    return {
        "id": discussion.id,
        "chat_thread_id": discussion.chat_thread_id,
        "title": discussion.title,
        "objective_md": discussion.objective_md,
        "status": discussion.status,
        "current_agent_id": discussion.current_agent_id,
        "current_round": discussion.current_round,
        "consensus_md": discussion.consensus_md,
        "created_at": discussion.created_at.isoformat(),
        "updated_at": discussion.updated_at.isoformat(),
        "finished_at": discussion.finished_at.isoformat() if discussion.finished_at else None,
    }


def _participant_payload(participant: DiscussionParticipant) -> dict:
    return {
        "id": participant.id,
        "discussion_id": participant.discussion_id,
        "agent_id": participant.agent_id,
        "agent_thread_id": participant.agent_thread_id,
        "position": participant.position,
        "status": participant.status,
        "last_end_discussion": participant.last_end_discussion,
        "created_at": participant.created_at.isoformat(),
        "updated_at": participant.updated_at.isoformat(),
    }


def _message_payload(message: DiscussionMessage) -> dict:
    return {
        "id": message.id,
        "discussion_id": message.discussion_id,
        "agent_id": message.agent_id,
        "agent_thread_id": message.agent_thread_id,
        "agent_run_id": message.agent_run_id,
        "content_md": message.content_md,
        "end_discussion": message.end_discussion,
        "round_index": message.round_index,
        "position": message.position,
        "metadata_json": message.metadata_json,
        "created_at": message.created_at.isoformat(),
    }

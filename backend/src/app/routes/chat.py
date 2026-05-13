from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    ChatAgentThread,
    ChatMessage,
    ChatProgressEvent,
    ChatThread,
    ChatThreadMessage,
    utcnow,
)
from app.routes.common import get_or_404
from app.schemas import (
    ChatAgentThreadCreate,
    ChatAgentThreadUpdate,
    ChatDebugLogCreate,
    ChatMessageCreate,
    ChatProgressEventCreate,
    ChatThreadCreate,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/threads")
def list_threads(session: Session = Depends(get_session)) -> list[ChatThread]:
    return session.exec(select(ChatThread).order_by(ChatThread.updated_at.desc())).all()


@router.post("/threads")
def create_thread(
    payload: ChatThreadCreate,
    session: Session = Depends(get_session),
) -> ChatThread:
    thread = ChatThread(**payload.model_dump())
    session.add(thread)
    session.commit()
    session.refresh(thread)
    return thread


@router.get("/threads/{thread_id}/messages")
def list_messages(thread_id: str, session: Session = Depends(get_session)) -> list[ChatMessage]:
    statement = (
        select(ChatMessage)
        .join(ChatThreadMessage, ChatThreadMessage.chat_message_id == ChatMessage.id)
        .where(ChatThreadMessage.chat_thread_id == thread_id)
        .where(ChatMessage.visibility == "visible")
        .order_by(ChatThreadMessage.position, ChatMessage.created_at)
    )
    return session.exec(statement).all()


@router.get("/threads/{thread_id}/progress")
def list_progress(thread_id: str, session: Session = Depends(get_session)) -> list[ChatProgressEvent]:
    return session.exec(
        select(ChatProgressEvent)
        .where(ChatProgressEvent.chat_thread_id == thread_id)
        .order_by(ChatProgressEvent.created_at)
    ).all()


@router.post("/progress")
def create_progress(
    payload: ChatProgressEventCreate,
    session: Session = Depends(get_session),
) -> ChatProgressEvent:
    existing = session.exec(
        select(ChatProgressEvent).where(
            ChatProgressEvent.chat_thread_id == payload.chat_thread_id,
            ChatProgressEvent.agent_thread_id == payload.agent_thread_id,
            ChatProgressEvent.desktop_run_id == payload.desktop_run_id,
            ChatProgressEvent.event_type == payload.event_type,
            ChatProgressEvent.content_md == payload.content_md,
        )
    ).first()
    if existing:
        return existing
    event = ChatProgressEvent(**payload.model_dump())
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.post("/debug-log")
def append_debug_log(payload: ChatDebugLogCreate) -> dict[str, bool | str]:
    path = Path(os.getenv("VIBE_CHAT_DEBUG_LOG", "data/logs/chat-debug.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "created_at": utcnow().isoformat(),
        **payload.model_dump(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    return {"success": True, "path": str(path)}


@router.get("/threads/{thread_id}/agents")
def list_chat_agents(
    thread_id: str,
    session: Session = Depends(get_session),
) -> list[ChatAgentThread]:
    return session.exec(
        select(ChatAgentThread)
        .where(ChatAgentThread.chat_thread_id == thread_id)
        .order_by(ChatAgentThread.created_at)
    ).all()


@router.put("/threads/{thread_id}/agents/{agent_id}")
def upsert_chat_agent(
    thread_id: str,
    agent_id: str,
    payload: ChatAgentThreadCreate,
    session: Session = Depends(get_session),
) -> ChatAgentThread:
    get_or_404(session, ChatThread, thread_id)
    existing = session.exec(
        select(ChatAgentThread).where(
            ChatAgentThread.chat_thread_id == thread_id,
            ChatAgentThread.agent_id == agent_id,
        )
    ).first()
    if existing:
        existing.enabled = payload.enabled
        existing.updated_at = utcnow()
        participant = existing
    else:
        participant = ChatAgentThread(
            chat_thread_id=thread_id,
            agent_id=agent_id,
            enabled=payload.enabled,
        )
    session.add(participant)
    session.commit()
    session.refresh(participant)
    return participant


@router.patch("/agent-threads/{participant_id}")
def update_chat_agent(
    participant_id: str,
    payload: ChatAgentThreadUpdate,
    session: Session = Depends(get_session),
) -> ChatAgentThread:
    participant = get_or_404(session, ChatAgentThread, participant_id)
    if payload.enabled is not None:
        participant.enabled = payload.enabled
    participant.updated_at = utcnow()
    session.add(participant)
    session.commit()
    session.refresh(participant)
    return participant


@router.post("/messages")
def create_message(
    payload: ChatMessageCreate,
    session: Session = Depends(get_session),
) -> ChatMessage:
    desktop_message_id = payload.metadata_json.get("desktop_message_id")
    if isinstance(desktop_message_id, str) and desktop_message_id:
        existing_messages = session.exec(
            select(ChatMessage)
            .join(ChatThreadMessage, ChatThreadMessage.chat_message_id == ChatMessage.id)
            .where(ChatThreadMessage.chat_thread_id == payload.chat_thread_id)
            .where(ChatMessage.source_type == payload.source_type)
            .where(ChatMessage.source_id == payload.source_id)
            .where(ChatMessage.role == payload.role)
        ).all()
        for existing in existing_messages:
            if existing.metadata_json.get("desktop_message_id") == desktop_message_id:
                return existing

    message = ChatMessage(
        source_type=payload.source_type,
        source_id=payload.source_id,
        role=payload.role,
        content_md=payload.content_md,
        visibility=payload.visibility,
        metadata_json=payload.metadata_json,
    )
    position = len(
        session.exec(
            select(ChatThreadMessage).where(
                ChatThreadMessage.chat_thread_id == payload.chat_thread_id
            )
        ).all()
    )
    thread = session.get(ChatThread, payload.chat_thread_id)
    if thread:
        thread.updated_at = utcnow()
        session.add(thread)
    session.add(message)
    session.commit()
    session.refresh(message)
    session.add(
        ChatThreadMessage(
            chat_thread_id=payload.chat_thread_id,
            chat_message_id=message.id,
            position=int(position),
        )
    )
    session.commit()
    session.refresh(message)
    return message

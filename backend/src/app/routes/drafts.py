from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import ChatDraft, ChatDraftQuestion, utcnow
from app.routes.common import get_or_404
from app.schemas import ChatDraftQuestionAnswer, ChatDraftUpdate

router = APIRouter(prefix="/api/chat/drafts", tags=["chat-drafts"])


@router.get("/active/{chat_thread_id}")
def active_draft(chat_thread_id: str, session: Session = Depends(get_session)) -> dict:
    draft = session.exec(
        select(ChatDraft)
        .where(ChatDraft.chat_thread_id == chat_thread_id, ChatDraft.status.in_(["active", "accepted"]))
        .order_by(ChatDraft.updated_at.desc())
    ).first()
    pending_question = session.exec(
        select(ChatDraftQuestion)
        .where(ChatDraftQuestion.chat_thread_id == chat_thread_id, ChatDraftQuestion.status == "pending")
        .order_by(ChatDraftQuestion.created_at.desc(), ChatDraftQuestion.position)
    ).first()
    questions = []
    if pending_question:
        questions = session.exec(
            select(ChatDraftQuestion)
            .where(
                ChatDraftQuestion.chat_thread_id == chat_thread_id,
                ChatDraftQuestion.batch_id == pending_question.batch_id,
                ChatDraftQuestion.status.in_(["pending", "answered"]),
            )
            .order_by(ChatDraftQuestion.position, ChatDraftQuestion.created_at)
        ).all()
    return {"draft": draft, "questions": questions}


@router.patch("/{draft_id}")
def update_draft(
    draft_id: str,
    payload: ChatDraftUpdate,
    session: Session = Depends(get_session),
) -> ChatDraft:
    draft = get_or_404(session, ChatDraft, draft_id)
    if payload.description_md is not None:
        draft.description_md = payload.description_md
    if payload.status is not None:
        draft.status = payload.status
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


@router.patch("/questions/{question_id}")
def answer_question(
    question_id: str,
    payload: ChatDraftQuestionAnswer,
    session: Session = Depends(get_session),
) -> ChatDraftQuestion:
    question = get_or_404(session, ChatDraftQuestion, question_id)
    question.selected_option = payload.selected_option
    question.answer_text = payload.answer_text
    question.status = "answered"
    question.updated_at = utcnow()
    session.add(question)
    session.commit()
    session.refresh(question)
    return question

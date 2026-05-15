from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models import ChatPlanDraft, ChatProposal, ChatQuestion, utcnow
from app.routes.common import get_or_404
from app.schemas import ChatPlanDraftUpdate, ChatProposalUpdate, ChatQuestionAnswer
from app.services.plan_drafts import PlanDraftError, create_plan_from_chat_plan_draft

router = APIRouter(prefix="/api/chat/proposals", tags=["chat-proposals"])


@router.get("/active/{chat_thread_id}")
def active_chat_artifacts(chat_thread_id: str, session: Session = Depends(get_session)) -> dict:
    proposal = session.exec(
        select(ChatProposal)
        .where(ChatProposal.chat_thread_id == chat_thread_id, ChatProposal.status == "active")
        .order_by(ChatProposal.updated_at.desc())
    ).first()
    plan_draft = session.exec(
        select(ChatPlanDraft)
        .where(ChatPlanDraft.chat_thread_id == chat_thread_id, ChatPlanDraft.status == "active")
        .order_by(ChatPlanDraft.updated_at.desc())
    ).first()
    pending_question = session.exec(
        select(ChatQuestion)
        .where(ChatQuestion.chat_thread_id == chat_thread_id, ChatQuestion.status == "pending")
        .order_by(ChatQuestion.created_at.desc(), ChatQuestion.position)
    ).first()
    questions = []
    if pending_question:
        questions = session.exec(
            select(ChatQuestion)
            .where(
                ChatQuestion.chat_thread_id == chat_thread_id,
                ChatQuestion.batch_id == pending_question.batch_id,
                ChatQuestion.status.in_(["pending", "answered"]),
            )
            .order_by(ChatQuestion.position, ChatQuestion.created_at)
        ).all()
    return {"proposal": proposal, "plan_draft": plan_draft, "questions": questions}


@router.patch("/{proposal_id}")
def update_proposal(
    proposal_id: str,
    payload: ChatProposalUpdate,
    session: Session = Depends(get_session),
) -> ChatProposal:
    proposal = get_or_404(session, ChatProposal, proposal_id)
    if payload.description_md is not None:
        proposal.description_md = payload.description_md
    if payload.status is not None:
        proposal.status = payload.status
    proposal.updated_at = utcnow()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


@router.patch("/plan-drafts/{draft_id}")
def update_plan_draft(
    draft_id: str,
    payload: ChatPlanDraftUpdate,
    session: Session = Depends(get_session),
) -> ChatPlanDraft:
    draft = get_or_404(session, ChatPlanDraft, draft_id)
    if payload.status is not None:
        draft.status = payload.status
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


@router.post("/plan-drafts/{draft_id}/accept")
def accept_plan_draft(draft_id: str, session: Session = Depends(get_session)) -> dict:
    draft = get_or_404(session, ChatPlanDraft, draft_id)
    try:
        plan, plan_chat, steps = create_plan_from_chat_plan_draft(session, draft)
        session.commit()
        session.refresh(draft)
        session.refresh(plan)
        session.refresh(plan_chat)
    except PlanDraftError as error:
        session.rollback()
        raise HTTPException(status_code=400, detail={"code": error.code, "message": str(error)}) from error
    return {
        "success": True,
        "plan": plan,
        "chat_thread": plan_chat,
        "step_ids": [step.id for step in steps],
        "plan_draft": draft,
    }


@router.patch("/questions/{question_id}")
def answer_question(
    question_id: str,
    payload: ChatQuestionAnswer,
    session: Session = Depends(get_session),
) -> ChatQuestion:
    question = get_or_404(session, ChatQuestion, question_id)
    question.selected_option = payload.selected_option
    question.answer_text = payload.answer_text
    question.status = "answered"
    question.updated_at = utcnow()
    session.add(question)
    session.commit()
    session.refresh(question)
    return question

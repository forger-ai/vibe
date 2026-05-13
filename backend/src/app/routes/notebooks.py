from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    AgentNotebookEntry,
    NotebookEntry,
    PlanNotebookEntry,
    PlanTypeNotebookEntry,
    RepositoryNotebookEntry,
    StepTypeNotebookEntry,
)
from app.schemas import NotebookEntryCreate

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.get("")
def list_entries(session: Session = Depends(get_session)) -> list[NotebookEntry]:
    return session.exec(select(NotebookEntry).order_by(NotebookEntry.updated_at.desc())).all()


@router.post("")
def create_entry(
    payload: NotebookEntryCreate,
    session: Session = Depends(get_session),
) -> NotebookEntry:
    entry = NotebookEntry(
        title=payload.title,
        short_description=payload.short_description,
        long_description_md=payload.long_description_md,
        entry_type=payload.entry_type,
        load_policy=payload.load_policy,
        read_when=payload.read_when,
        created_by_agent_id=payload.created_by_agent_id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    if payload.scope_type and payload.scope_id:
        _link_scope(session, entry.id, payload.scope_type, payload.scope_id)
    session.commit()
    session.refresh(entry)
    return entry


def _link_scope(session: Session, entry_id: str, scope_type: str, scope_id: str) -> None:
    mapping = {
        "repository": RepositoryNotebookEntry(
            repository_id=scope_id,
            notebook_entry_id=entry_id,
        ),
        "plan_type": PlanTypeNotebookEntry(
            plan_type_id=scope_id,
            notebook_entry_id=entry_id,
        ),
        "plan": PlanNotebookEntry(plan_id=scope_id, notebook_entry_id=entry_id),
        "step_type": StepTypeNotebookEntry(
            step_type_id=scope_id,
            notebook_entry_id=entry_id,
        ),
        "agent": AgentNotebookEntry(agent_id=scope_id, notebook_entry_id=entry_id),
    }
    link = mapping.get(scope_type)
    if link:
        session.add(link)

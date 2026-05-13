from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import StepType, utcnow
from app.routes.common import get_or_404
from app.schemas import StepTypeCreate, StepTypeUpdate

router = APIRouter(prefix="/api/step-types", tags=["step-types"])

RESPONSIBLE_VALUES = {"agent", "multiagents", "human", "script", "command"}


@router.get("")
def list_step_types(session: Session = Depends(get_session)) -> list[StepType]:
    return session.exec(select(StepType).order_by(StepType.name)).all()


@router.post("")
def create_step_type(payload: StepTypeCreate, session: Session = Depends(get_session)) -> StepType:
    data = payload.model_dump()
    data["responsible"] = _responsible(data.get("responsible"))
    step_type = StepType(**data)
    session.add(step_type)
    session.commit()
    session.refresh(step_type)
    return step_type


@router.patch("/{step_type_id}")
def update_step_type(
    step_type_id: str,
    payload: StepTypeUpdate,
    session: Session = Depends(get_session),
) -> StepType:
    step_type = get_or_404(session, StepType, step_type_id)
    updates = payload.model_dump(exclude_unset=True)
    if "responsible" in updates and updates["responsible"] is not None:
        updates["responsible"] = _responsible(updates["responsible"])
    for key, value in updates.items():
        if value is not None:
            setattr(step_type, key, value)
    step_type.updated_at = utcnow()
    session.add(step_type)
    session.commit()
    session.refresh(step_type)
    return step_type


@router.delete("/{step_type_id}", status_code=204)
def delete_step_type(step_type_id: str, session: Session = Depends(get_session)) -> None:
    step_type = get_or_404(session, StepType, step_type_id)
    session.delete(step_type)
    session.commit()


def _responsible(value: object) -> str:
    responsible = str(value or "agent")
    if responsible not in RESPONSIBLE_VALUES:
        raise ValueError("responsible must be agent, multiagents, human, script, or command")
    return responsible

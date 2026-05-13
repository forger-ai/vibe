from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import GitRepository
from app.routes.common import get_or_404
from app.schemas import RepositoryCreate
from app.services.workspaces import create_plan_checkout, sync_repository_mirror

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


@router.get("")
def list_repositories(session: Session = Depends(get_session)) -> list[GitRepository]:
    return session.exec(select(GitRepository).order_by(GitRepository.name)).all()


@router.post("")
def create_repository(
    payload: RepositoryCreate,
    session: Session = Depends(get_session),
) -> GitRepository:
    repository = GitRepository(**payload.model_dump())
    session.add(repository)
    session.commit()
    session.refresh(repository)
    return repository


@router.post("/{repository_id}/sync")
def sync_repository(repository_id: str, session: Session = Depends(get_session)) -> dict:
    repository = get_or_404(session, GitRepository, repository_id)
    checkout = sync_repository_mirror(session, repository)
    return {"success": True, "checkout": checkout}


@router.post("/{repository_id}/plan-checkout/{plan_id}")
def create_plan_workspace(
    repository_id: str,
    plan_id: str,
    session: Session = Depends(get_session),
) -> dict:
    repository = get_or_404(session, GitRepository, repository_id)
    checkout = create_plan_checkout(session, repository, plan_id)
    return {"success": True, "checkout": checkout}

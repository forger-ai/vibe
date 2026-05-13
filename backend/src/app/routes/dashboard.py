from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Agent, AgentRun, GitRepository, Plan
from app.schemas import DashboardSummary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummary)
def dashboard(session: Session = Depends(get_session)) -> DashboardSummary:
    repositories = len(session.exec(select(GitRepository)).all())
    agents = len(session.exec(select(Agent)).all())
    active_plans = len(
        session.exec(select(Plan).where(Plan.status.in_(["draft", "active", "running"]))).all()
    )
    active_runs = len(
        session.exec(select(AgentRun).where(AgentRun.status.in_(["queued", "running"]))).all()
    )
    return DashboardSummary(
        repositories=repositories,
        agents=agents,
        active_plans=active_plans,
        active_runs=active_runs,
    )

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Agent, utcnow
from app.routes.common import get_or_404
from app.schemas import AgentCreate, AgentUpdate, PromptBuildRequest, PromptVariablesRequest
from app.services.prompt_builder import build_agent_prompt_variables, list_thread_interfaces, render_agent_prompt

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def list_agents(session: Session = Depends(get_session)) -> list[Agent]:
    return session.exec(select(Agent).order_by(Agent.name)).all()


@router.post("")
def create_agent(payload: AgentCreate, session: Session = Depends(get_session)) -> Agent:
    agent = Agent(**payload.model_dump())
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@router.patch("/{agent_id}")
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    session: Session = Depends(get_session),
) -> Agent:
    agent = get_or_404(session, Agent, agent_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, key, value)
    agent.updated_at = utcnow()
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@router.get("/interfaces")
def list_agent_interfaces() -> list[dict[str, str]]:
    return [
        {"id": key, "title": key.replace("-", " ").title(), "template": value}
        for key, value in list_thread_interfaces().items()
    ]


@router.post("/prompt")
def build_prompt(
    payload: PromptBuildRequest,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    agent = get_or_404(session, Agent, payload.agent_id)
    return {
        "prompt": render_agent_prompt(
            session,
            agent,
            payload.manifest_agent_id,
            payload.context,
            payload.manifest_prompt_template,
        )
    }


@router.post("/prompt-variables")
def build_prompt_variables(
    payload: PromptVariablesRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    agent = get_or_404(session, Agent, payload.agent_id)
    return build_agent_prompt_variables(session, agent, payload.manifest_agent_id, payload.context)

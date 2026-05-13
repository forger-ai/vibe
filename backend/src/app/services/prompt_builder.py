from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Agent,
    AgentNotebookEntry,
    NotebookEntry,
    PlanNotebookEntry,
    RepositoryNotebookEntry,
)


def list_thread_interfaces() -> dict[str, str]:
    return _load_manifest_prompts()


def render_agent_prompt(
    session: Session,
    agent: Agent,
    manifest_agent_id: str,
    context: dict[str, Any],
    manifest_prompt_template: str | None = None,
) -> str:
    template = (manifest_prompt_template or "").strip()
    if not template:
        template = _load_manifest_prompts().get(manifest_agent_id, "")
    if not template:
        template = _load_manifest_prompts().get("free-chat-agent", "")
    values = build_agent_prompt_variables(session, agent, manifest_agent_id, context)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return str(values.get(key, values.get(_legacy_key(key), "")))

    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, template).strip()


def _legacy_key(key: str) -> str:
    return {
        "agent.identity": "agentIdentity",
        "agent.id": "agentId",
        "agent.tone": "agentTone",
        "agent.task": "agentTask",
        "agent.feature_intake_task": "agentFeatureIntakeTask",
        "agent.plan_task": "agentPlanTask",
        "agent.free_chat_task": "agentFreeChatTask",
        "agent.guardrails": "agentGuardrails",
        "chat.id": "chatThreadId",
        "chat.role": "chatRole",
        "global.guardrails": "globalGuardrails",
        "notebooks.agent": "agentNotebook",
        "notebooks.plan": "planNotebook",
        "notebooks.repository": "repositoryNotebook",
        "notebooks.interface": "interfaceNotebook",
        "notebooks.global": "globalNotebook",
        "orchestrator": "orchestrator",
        "plan.description": "planDescription",
        "plan.steps": "planSteps",
        "plan.assignments": "planAssignments",
        "repository.context": "repositoryContext",
        "agents": "agentsInChat",
        "review.target": "reviewTarget",
        "step.description": "stepDescription",
        "assignment.instructions": "assignmentInstructions",
        "user.message": "userMessage",
    }.get(key, key)


def build_agent_prompt_variables(
    session: Session,
    agent: Agent,
    manifest_agent_id: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    notebooks = build_notebook_context(session, agent.id, manifest_agent_id, context)
    return {
        "agentIdentity": agent.identity_md,
        "agentId": agent.id,
        "agentTone": agent.tone_md,
        "agentTask": _agent_task(agent, manifest_agent_id),
        "agentFeatureIntakeTask": agent.feature_intake_task_md,
        "agentPlanTask": agent.plan_task_md,
        "agentFreeChatTask": agent.free_chat_task_md,
        "agentGuardrails": agent.guardrails_md,
        "chatThreadId": context.get("chat_id", ""),
        "chatRole": context.get("chat_role", ""),
        "context": context.get("context", ""),
        "globalGuardrails": context.get("global_guardrails", ""),
        "agentNotebook": notebooks["agent"],
        "planNotebook": notebooks["plan"],
        "repositoryNotebook": notebooks["repository"],
        "interfaceNotebook": notebooks["interface"],
        "globalNotebook": notebooks["global"],
        "orchestrator": context.get("orchestrator", ""),
        "planDescription": _nested(context, "plan", "description"),
        "planSteps": _nested(context, "plan", "steps"),
        "planAssignments": _nested(context, "plan", "assignments"),
        "repositoryContext": context.get("repository_context", ""),
        "agentsInChat": context.get("agents", ""),
        "reviewTarget": context.get("review_target", ""),
        "discussionId": context.get("discussion_id", ""),
        "discussionObjective": context.get("discussion_objective", ""),
        "discussionMessages": context.get("discussion_messages", ""),
        "stepDescription": _nested(context, "step", "description"),
        "assignmentInstructions": _nested(context, "assignment", "instructions"),
        "userMessage": context.get("user_message", ""),
    }


def build_notebook_context(
    session: Session,
    agent_id: str,
    manifest_agent_id: str,
    context: dict[str, Any],
) -> dict[str, str]:
    plan_id = str(context.get("plan_id") or _nested(context, "plan", "id") or "")
    repository_ids = _repository_ids(context)
    scoped_ids: dict[str, set[str]] = {
        "agent": {
            link.notebook_entry_id
            for link in session.exec(select(AgentNotebookEntry).where(AgentNotebookEntry.agent_id == agent_id)).all()
        },
        "plan": set(),
        "repository": set(),
        "interface": set(),
        "global": set(),
    }
    if plan_id:
        scoped_ids["plan"] = {
            link.notebook_entry_id
            for link in session.exec(select(PlanNotebookEntry).where(PlanNotebookEntry.plan_id == plan_id)).all()
        }
    if repository_ids:
        scoped_ids["repository"] = {
            link.notebook_entry_id
            for link in session.exec(
                select(RepositoryNotebookEntry).where(RepositoryNotebookEntry.repository_id.in_(repository_ids))
            ).all()
        }
    entries = session.exec(select(NotebookEntry).order_by(NotebookEntry.updated_at.desc())).all()
    linked_ids = scoped_ids["agent"] | scoped_ids["plan"] | scoped_ids["repository"]
    scoped_ids["interface"] = {
        entry.id
        for entry in entries
        if entry.entry_type in {manifest_agent_id, manifest_agent_id.replace("-agent", "")}
    }
    scoped_ids["global"] = {
        entry.id
        for entry in entries
        if entry.id not in linked_ids
        and entry.id not in scoped_ids["interface"]
        and entry.load_policy == "always"
    }
    entry_by_id = {entry.id: entry for entry in entries}
    return {
        key: _format_notebook_entries([entry_by_id[entry_id] for entry_id in ids if entry_id in entry_by_id])
        for key, ids in scoped_ids.items()
    }


def _format_notebook_entries(entries: list[NotebookEntry]) -> str:
    if not entries:
        return "No registered notebook entries."
    parts: list[str] = []
    for entry in sorted(entries, key=lambda item: item.updated_at, reverse=True):
        if entry.load_policy == "always" or entry.read_when is None:
            parts.append(
                f"## {entry.title}\n"
                f"ID: {entry.id}\n"
                f"Slug: {notebook_slug(entry)}\n"
                f"Type: {entry.entry_type}\n"
                f"When to read: always\n\n"
                f"{entry.long_description_md}".strip()
            )
        else:
            parts.append(
                f"- {entry.title} (id: {entry.id}, slug: {notebook_slug(entry)}): "
                f"{entry.short_description or 'No short description.'} "
                f"When to read: {entry.read_when}"
            )
    return "\n\n".join(parts)


def _repository_ids(context: dict[str, Any]) -> list[str]:
    raw_ids = context.get("repository_ids")
    if isinstance(raw_ids, list):
        return [str(item) for item in raw_ids if str(item).strip()]
    return []


def _agent_task(agent: Agent, manifest_agent_id: str) -> str:
    if manifest_agent_id in {"featureIntakeOrchestrator"}:
        return ""
    if manifest_agent_id in {"freeChatOrchestrator", "planChatOrchestrator"}:
        return ""
    if manifest_agent_id in {"agentChatDiscussion", "agentChatTask"}:
        return agent.free_chat_task_md
    if manifest_agent_id == "agentStepTask":
        return agent.plan_task_md
    if manifest_agent_id == "feature-intake-agent":
        return agent.feature_intake_task_md
    if manifest_agent_id == "plan-agent":
        return agent.plan_task_md
    return agent.free_chat_task_md


def notebook_slug(entry: NotebookEntry) -> str:
    title = re.sub(r"[^a-z0-9]+", "-", entry.title.lower()).strip("-")
    prefix = title or "notebook"
    return f"{prefix}-{entry.id[:8]}"


def _load_manifest_prompts() -> dict[str, str]:
    manifest_path = _manifest_path()
    if not manifest_path or not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        return {}
    prompts: dict[str, str] = {}
    for item in data.get("agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "")
        prompt_blocks = item.get("prompts") if isinstance(item.get("prompts"), dict) else {}
        initial = prompt_blocks.get("initial") if isinstance(prompt_blocks.get("initial"), dict) else {}
        prompt = str(initial.get("body") or item.get("initialPrompt") or item.get("initialPromptTemplate") or "")
        if agent_id and prompt.strip():
            prompts[agent_id] = prompt.strip()
    return prompts


def _manifest_path() -> Path | None:
    configured = os.environ.get("VIBE_MANIFEST_PATH")
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "manifest.json"
        if candidate.exists():
            return candidate
    return None


def _nested(context: dict[str, Any], key: str, field: str) -> str:
    value = context.get(key)
    if isinstance(value, dict):
        item = value.get(field)
        return str(item) if item is not None else ""
    return ""

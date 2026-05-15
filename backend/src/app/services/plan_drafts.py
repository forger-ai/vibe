from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import (
    ChatPlanDraft,
    ChatThread,
    CommandStep,
    GitRepository,
    Plan,
    PlanChatThread,
    PlanRepository,
    Script,
    ScriptStep,
    Step,
    StepAssignment,
    StepDependency,
    StepRepository,
    StepType,
    utcnow,
)


class PlanDraftError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


def validate_plan_draft_payload(
    session: Session,
    *,
    repositories: object,
    steps: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repository_items = _normalize_repositories(repositories)
    step_items = _normalize_steps(steps)
    for item in repository_items:
        repository = session.get(GitRepository, _required_string(item, "repository_id"))
        if not repository:
            raise PlanDraftError("repository_id not found", code="not_found")
    for item in step_items:
        _reject_legacy_step_kind(item)
        step_type = _required_step_type(session, item.get("step_type_id"))
        _validate_create_plan_step_payload(session, item, step_type)
    return repository_items, step_items


def create_plan_from_chat_plan_draft(
    session: Session,
    draft: ChatPlanDraft,
) -> tuple[Plan, ChatThread, list[Step]]:
    if draft.status != "active":
        raise PlanDraftError("only active plan drafts can be accepted", code="invalid_state")
    repository_items, step_items = validate_plan_draft_payload(
        session,
        repositories=draft.repositories_json,
        steps=draft.steps_json,
    )
    plan = Plan(
        name=draft.name,
        description=draft.description,
        context_md=draft.context_md,
    )
    session.add(plan)
    session.flush()
    for item in repository_items:
        repository = session.get(GitRepository, _required_string(item, "repository_id"))
        if not repository:
            raise PlanDraftError("repository_id not found", code="not_found")
        session.add(
            PlanRepository(
                plan_id=plan.id,
                repository_id=repository.id,
                start_ref=str(item.get("start_ref") or repository.default_branch),
            )
        )
    plan_chat = ChatThread(thread_type="planChatOrchestrator", title=plan.name)
    session.add(plan_chat)
    session.flush()
    session.add(PlanChatThread(plan_id=plan.id, chat_thread_id=plan_chat.id))

    created_steps: list[Step] = []
    for item in step_items:
        step_type = _required_step_type(session, item.get("step_type_id"))
        step = Step(
            plan_id=plan.id,
            step_type_id=step_type.id,
            name=_required_string(item, "name"),
            description=_required_string(item, "description"),
            kind=_legacy_kind_for_step_type(step_type),
            position=len(created_steps),
        )
        session.add(step)
        session.flush()
        created_steps.append(step)
        for repository_id in item.get("repository_ids") or []:
            if isinstance(repository_id, str) and repository_id.strip():
                repository = session.get(GitRepository, repository_id)
                if not repository:
                    raise PlanDraftError("repository_id not found", code="not_found")
                session.add(StepRepository(step_id=step.id, repository_id=repository.id))
        script_id = str(item.get("script_id") or "")
        if script_id:
            script = session.get(Script, script_id)
            if not script:
                raise PlanDraftError("script_id not found", code="not_found")
            session.add(
                ScriptStep(
                    step_id=step.id,
                    script_id=script.id,
                    args_text=str(item.get("script_args_text") or ""),
                )
            )
        command_text = str(item.get("command_text") or "")
        if command_text.strip():
            timeout = int(item.get("command_timeout_seconds") or 600)
            if timeout < 1:
                raise PlanDraftError("command_timeout_seconds must be at least 1")
            session.add(
                CommandStep(
                    step_id=step.id,
                    command_text=command_text,
                    timeout_seconds=timeout,
                )
            )
        for assignment in item.get("assignments") or []:
            if isinstance(assignment, dict):
                session.add(
                    StepAssignment(
                        step_id=step.id,
                        agent_id=_required_string(assignment, "agent_id"),
                        instructions_md=_required_string(assignment, "instructions_md"),
                    )
                )
        session.flush()
        _validate_step_contract(session, step)

    for index, item in enumerate(step_items):
        for dependency_index in item.get("depends_on_step_indexes") or []:
            if isinstance(dependency_index, int) and 0 <= dependency_index < len(created_steps):
                session.add(
                    StepDependency(
                        step_id=created_steps[index].id,
                        depends_on_step_id=created_steps[dependency_index].id,
                    )
                )

    draft.status = "implemented"
    draft.created_plan_id = plan.id
    draft.updated_at = utcnow()
    session.add(draft)
    return plan, plan_chat, created_steps


def _normalize_repositories(repositories: object) -> list[dict[str, Any]]:
    if repositories is None:
        return []
    if not isinstance(repositories, list):
        raise PlanDraftError("repositories must be an array")
    return [item for item in repositories if isinstance(item, dict)]


def _normalize_steps(steps: object) -> list[dict[str, Any]]:
    if not isinstance(steps, list) or not steps:
        raise PlanDraftError("steps must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    for item in steps:
        if not isinstance(item, dict):
            raise PlanDraftError("step items must be objects")
        normalized.append(item)
    return normalized


def _required_string(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PlanDraftError(f"{name} is required")
    return value.strip()


def _required_step_type(session: Session, value: object) -> StepType:
    step_type_id = str(value or "").strip()
    if not step_type_id:
        raise PlanDraftError("step_type_id is required")
    step_type = session.get(StepType, step_type_id)
    if not step_type:
        raise PlanDraftError("step_type_id not found", code="not_found")
    return step_type


def _legacy_kind_for_step_type(step_type: StepType) -> str:
    if step_type.name.lower() == "review" or step_type.responsible == "human":
        return "review"
    return "programming"


def _validate_create_plan_step_payload(
    session: Session,
    item: dict[str, Any],
    step_type: StepType,
) -> None:
    responsible = step_type.responsible or "agent"
    script_id = str(item.get("script_id") or "")
    command_text = str(item.get("command_text") or "")
    if responsible == "script" and not script_id.strip():
        raise PlanDraftError("script steps require a script")
    if responsible != "script" and script_id.strip():
        raise PlanDraftError("only script steps can reference a script")
    if responsible == "command" and not command_text.strip():
        raise PlanDraftError("command steps require a command")
    if responsible != "command" and command_text.strip():
        raise PlanDraftError("only command steps can reference a command")
    for repository_id in item.get("repository_ids") or []:
        if not isinstance(repository_id, str) or not repository_id.strip():
            raise PlanDraftError("repository_ids must contain repository ids")
        if not session.get(GitRepository, repository_id):
            raise PlanDraftError("repository_id not found", code="not_found")
    if script_id and not session.get(Script, script_id):
        raise PlanDraftError("script_id not found", code="not_found")


def _reject_legacy_step_kind(args: dict[str, Any]) -> None:
    if "kind" in args:
        raise PlanDraftError("kind is no longer accepted; use step_type_id")


def _step_responsible(session: Session, step: Step) -> str:
    step_type = session.get(StepType, step.step_type_id) if step.step_type_id else None
    if step_type and step_type.responsible:
        return step_type.responsible
    return "agent"


def _validate_step_contract(session: Session, step: Step) -> None:
    responsible = _step_responsible(session, step)
    script_link = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).first()
    command_link = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
    if responsible == "script" and not script_link:
        raise PlanDraftError("script steps require a script")
    if responsible != "script" and script_link:
        raise PlanDraftError("only script steps can reference a script")
    if responsible == "command" and not command_link:
        raise PlanDraftError("command steps require a command")
    if responsible != "command" and command_link:
        raise PlanDraftError("only command steps can reference a command")

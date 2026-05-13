from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from app.database import engine
from app.database_ext import init_app_db
from app.forger_desktop import (
    ForgerDesktopRuntimeError,
    create_agent_thread as desktop_create_agent_thread,
    get_agent_thread as desktop_get_agent_thread,
    start_agent_run as desktop_start_agent_run,
    wait_for_run as desktop_wait_for_run,
)
from app.mcp_runtime import ToolError, ToolRegistry, main
from app.models import (
    Agent,
    AgentRun,
    AgentThread,
    ChatAgentThread,
    ChatDraft,
    ChatDraftQuestion,
    ChatMessage,
    ChatProgressEvent,
    ChatThread,
    ChatThreadMessage,
    CommandExecutionResult,
    CommandStep,
    Discussion,
    DiscussionMessage,
    DiscussionParticipant,
    GitRepository,
    NotebookEntry,
    Plan,
    PlanChatThread,
    PlanRepository,
    Script,
    ScriptExecutionResult,
    ScriptStep,
    Step,
    StepAssignment,
    StepAssignmentAgentThread,
    StepCommit,
    StepDependency,
    StepExecution,
    StepExecutionAgentThread,
    StepRepository,
    StepType,
    WorkspaceCheckout,
    utcnow,
)
from app.services.plan_deletion import delete_plan_cascade
from app.services.prompt_builder import list_thread_interfaces, notebook_slug, render_agent_prompt
from app.services.scripts import (
    delete_script_files,
    normalize_script_language,
    read_script_env,
    read_script_source,
    slugify_script,
    write_script_files,
)

registry = ToolRegistry()


@registry.tool("status", "Return Vibe MCP and database status.")
def status(_args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        repository_count = len(session.exec(select(GitRepository)).all())
    return {
        "success": True,
        "status": "ok",
        "agentInterfaces": list(list_thread_interfaces().keys()),
        "repositoryCount": repository_count,
    }


@registry.tool(
    "list_repositories",
    "List repositories configured in Vibe, including synced local workspace paths when available.",
    {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)
def list_repositories(_args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        repositories = session.exec(select(GitRepository).order_by(GitRepository.name)).all()
        checkouts = session.exec(
            select(WorkspaceCheckout).where(WorkspaceCheckout.owner_type == "repository")
        ).all()
        checkout_by_repo = {checkout.repository_id: checkout for checkout in checkouts}
        return {
            "success": True,
            "repositories": [
                {
                    "id": repository.id,
                    "name": repository.name,
                    "description": repository.description,
                    "remote_url": repository.remote_url,
                    "default_branch": repository.default_branch,
                    "local_path": repository.local_path,
                    "credential_mode": repository.credential_mode,
                    "checkout": _checkout_payload(checkout_by_repo.get(repository.id)),
                }
                for repository in repositories
            ],
        }


@registry.tool(
    "list_plans",
    "List Vibe plans with stable ids, status, execution mode, and short previews.",
    {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)
def list_plans(_args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        plans = session.exec(select(Plan).order_by(Plan.updated_at.desc())).all()
        return {
            "success": True,
            "plans": [
                {
                    "id": plan.id,
                    "name": plan.name,
                    "status": plan.status,
                    "execution_mode": plan.execution_mode,
                    "description_preview": _preview(plan.description),
                    "context_preview": _preview(plan.context_md),
                    "updated_at": plan.updated_at.isoformat(),
                }
                for plan in plans
            ],
        }


@registry.tool(
    "get_plan_detail",
    "Return full operational detail for a Vibe plan, including ids needed by step and assignment MCP tools.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
        },
        "required": ["plan_id"],
        "additionalProperties": False,
    },
)
def get_plan_detail(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        steps = session.exec(select(Step).where(Step.plan_id == plan.id).order_by(Step.position, Step.created_at)).all()
        step_ids = [step.id for step in steps]
        assignments = session.exec(
            select(StepAssignment).where(StepAssignment.step_id.in_(step_ids))
        ).all() if step_ids else []
        dependencies = session.exec(
            select(StepDependency).where(StepDependency.step_id.in_(step_ids))
        ).all() if step_ids else []
        repositories = session.exec(
            select(PlanRepository).where(PlanRepository.plan_id == plan.id).order_by(PlanRepository.created_at)
        ).all()
        step_repositories = session.exec(
            select(StepRepository).where(StepRepository.step_id.in_(step_ids))
        ).all() if step_ids else []
        executions = session.exec(
            select(StepExecution).where(StepExecution.step_id.in_(step_ids)).order_by(StepExecution.created_at)
        ).all() if step_ids else []
        execution_ids = [execution.id for execution in executions]
        commits = session.exec(
            select(StepCommit).where(StepCommit.step_execution_id.in_(execution_ids)).order_by(StepCommit.created_at)
        ).all() if execution_ids else []
        script_steps = session.exec(
            select(ScriptStep).where(ScriptStep.step_id.in_(step_ids))
        ).all() if step_ids else []
        command_steps = session.exec(
            select(CommandStep).where(CommandStep.step_id.in_(step_ids))
        ).all() if step_ids else []
        script_results = session.exec(
            select(ScriptExecutionResult).where(ScriptExecutionResult.step_execution_id.in_(execution_ids)).order_by(ScriptExecutionResult.created_at)
        ).all() if execution_ids else []
        command_results = session.exec(
            select(CommandExecutionResult).where(CommandExecutionResult.step_execution_id.in_(execution_ids)).order_by(CommandExecutionResult.created_at)
        ).all() if execution_ids else []
        return {
            "success": True,
            "plan": _plan_payload(plan),
            "steps": [_step_payload(step) for step in steps],
            "step_types": [_step_type_payload(step_type) for step_type in session.exec(select(StepType).order_by(StepType.name)).all()],
            "dependencies": [_dependency_payload(dependency) for dependency in dependencies],
            "assignments": [_assignment_payload(assignment) for assignment in assignments],
            "repositories": [_plan_repository_payload(repository) for repository in repositories],
            "step_repositories": [_step_repository_payload(link) for link in step_repositories],
            "executions": [_execution_payload(execution) for execution in executions],
            "commits": [_commit_payload(commit) for commit in commits],
            "script_steps": [_script_step_payload(link) for link in script_steps],
            "command_steps": [_command_step_payload(link) for link in command_steps],
            "script_results": [_script_result_payload(result) for result in script_results],
            "command_results": [_command_result_payload(result) for result in command_results],
            "eligible_step_ids": [step.id for step in _eligible_steps(steps, dependencies)],
        }


@registry.tool(
    "write_chat_message",
    "Write an internal, non-visible note into a Vibe chat thread.",
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "source_id": {"type": "string"},
            "role": {"type": "string"},
            "content_md": {"type": "string"},
            "visibility": {"type": "string"},
        },
        "required": ["chat_thread_id", "content_md"],
        "additionalProperties": False,
    },
)
def write_chat_message(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    content = _string(args, "content_md")
    role = str(args.get("role") or "assistant")
    visibility = str(args.get("visibility") or "internal")
    if role == "assistant" or visibility == "visible":
        raise ToolError(
            "visible chat responses are owned by the manifest orchestrator",
            code="visible_chat_forbidden",
        )
    with Session(engine) as session:
        thread = session.get(ChatThread, thread_id)
        if not thread:
            raise ToolError("chat_thread_id not found", code="not_found")
        count = len(
            session.exec(
                select(ChatThreadMessage).where(
                    ChatThreadMessage.chat_thread_id == thread_id
                )
            ).all()
        )
        message = ChatMessage(
            source_type="system",
            source_id=str(args.get("source_id") or ""),
            role=role,
            content_md=content,
            visibility=visibility,
            metadata_json={"source_tool": "write_chat_message", "internal": True},
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        session.add(
            ChatThreadMessage(
                chat_thread_id=thread_id,
                chat_message_id=message.id,
                position=count,
            )
        )
        session.commit()
        return {"success": True, "message_id": message.id}


@registry.tool(
    "call_agent",
    "Invoke one Vibe Agent through Forger Desktop. Only the manifest orchestrator may call this tool.",
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "instructions_md": {"type": "string"},
            "wait": {"type": "boolean"},
            "expose_progress": {"type": "boolean"},
            "title": {"type": "string"},
            "timeout_seconds": {"type": "number"},
            "orchestrator_agent_id": {"type": "string"},
        },
        "required": ["chat_thread_id", "agent_id", "instructions_md"],
        "additionalProperties": False,
    },
)
def call_agent(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    agent_id = _string(args, "agent_id")
    instructions = _string(args, "instructions_md")
    orchestrator_agent_id = str(args.get("orchestrator_agent_id") or "manifest-orchestrator")
    wait = bool(args.get("wait", False))
    expose_progress = bool(args.get("expose_progress", False))
    timeout_seconds = int(args.get("timeout_seconds") or 600)

    with Session(engine) as session:
        _require_manifest_orchestrator(session, thread_id, orchestrator_agent_id)
        _require_no_blocking_draft_gate(session, thread_id)
        agent = session.get(Agent, agent_id)
        if not agent:
            raise ToolError("agent_id not found", code="not_found")
        prompt = render_agent_prompt(
            session,
            agent,
            "agentChatTask",
            {
                "chat_thread_id": thread_id,
                "userMessage": instructions,
                "turnPayload": {"chat_thread_id": thread_id, "instructions_md": instructions},
            },
        )
        title = str(args.get("title") or agent.name or "Agent task")
        try:
            desktop_thread = desktop_create_agent_thread(
                title=title,
                manifest_agent_id="agentChatTask",
                initial_prompt=prompt,
                runtime=_runtime_for_agent(agent),
                metadata={"vibeAgentId": agent.id, "chatThreadId": thread_id, "invocationMode": "single_task"},
            )
            stored_thread = AgentThread(
                desktop_thread_id=str(desktop_thread.get("desktop_thread_id") or ""),
                agent_id=agent.id,
                manifest_agent_id="agentChatTask",
                chat_thread_id=thread_id,
                owner_type="agent",
                invocation_mode="single_task",
                title=title,
                initial_prompt_snapshot_md=prompt,
                status=str(desktop_thread.get("status") or "idle"),
            )
            session.add(stored_thread)
            session.commit()
            session.refresh(stored_thread)
            run = desktop_start_agent_run(
                desktop_thread_id=stored_thread.desktop_thread_id,
                message=instructions,
                context=json.dumps({"chat_thread_id": thread_id, "instructions_md": instructions}, indent=2),
                runtime=_runtime_for_agent(agent),
            )
            stored_run = AgentRun(
                agent_thread_id=stored_thread.id,
                desktop_run_id=str(run.get("desktop_run_id") or ""),
                trigger_type="call_agent",
                trigger_id=thread_id,
                status=str(run.get("status") or "queued"),
                input_md=instructions,
                context_snapshot_md=prompt,
                started_at=utcnow(),
            )
            stored_thread.status = "running"
            stored_thread.updated_at = utcnow()
            session.add(stored_thread)
            session.add(stored_run)
            session.commit()
            session.refresh(stored_run)
            if expose_progress:
                _write_progress(session, thread_id, agent.id, stored_thread.id, stored_run.desktop_run_id, "agent_call.started", f"{agent.name} started.")
            if not wait:
                return {
                    "success": True,
                    "agent_thread_id": stored_thread.id,
                    "desktop_thread_id": stored_thread.desktop_thread_id,
                    "agent_run_id": stored_run.id,
                    "desktop_run_id": stored_run.desktop_run_id,
                    "status": stored_run.status,
                }
            final_run = desktop_wait_for_run(
                desktop_thread_id=stored_thread.desktop_thread_id,
                desktop_run_id=stored_run.desktop_run_id,
                timeout_seconds=timeout_seconds,
            )
            live_thread = desktop_get_agent_thread(stored_thread.desktop_thread_id) or {}
            result = _last_assistant_message(live_thread)
            stored_run.status = str(final_run.get("status") or "completed")
            stored_run.result_md = result
            stored_run.error = str(final_run.get("error") or "") or None
            stored_run.finished_at = utcnow()
            stored_run.updated_at = utcnow()
            stored_thread.status = "idle" if stored_run.status == "completed" else stored_run.status
            stored_thread.updated_at = utcnow()
            session.add(stored_thread)
            session.add(stored_run)
            if expose_progress:
                _write_progress(
                    session,
                    thread_id,
                    agent.id,
                    stored_thread.id,
                    stored_run.desktop_run_id,
                    f"agent_call.{stored_run.status}",
                    f"{agent.name} {stored_run.status}.",
                )
            session.commit()
            return {
                "success": stored_run.status == "completed",
                "agent_thread_id": stored_thread.id,
                "desktop_thread_id": stored_thread.desktop_thread_id,
                "agent_run_id": stored_run.id,
                "desktop_run_id": stored_run.desktop_run_id,
                "status": stored_run.status,
                "result_md": result,
                "error": stored_run.error,
            }
        except ForgerDesktopRuntimeError as error:
            raise ToolError(str(error), code="desktop_runtime_error") from error


@registry.tool(
    "ask_user",
    "Ask the user up to four Draft Mode questions. Only the manifest orchestrator may call this tool.",
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "orchestrator_agent_id": {"type": "string"},
            "chat_draft_id": {"type": "string"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "required": ["label"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["question", "options"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["chat_thread_id", "questions"],
        "additionalProperties": False,
    },
)
def ask_user(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    orchestrator_agent_id = str(args.get("agent_id") or args.get("orchestrator_agent_id") or "manifest-orchestrator")
    questions = args.get("questions")
    if not isinstance(questions, list) or len(questions) == 0:
        raise ToolError("questions must include at least one question", code="invalid_input")
    if len(questions) > 4:
        raise ToolError("ask_user accepts at most four questions per call", code="invalid_input")
    batch_id = str(uuid4())
    with Session(engine) as session:
        _require_manifest_orchestrator(session, thread_id, orchestrator_agent_id)
        _cancel_active_draft_gates(session, thread_id)
        draft_id = str(args.get("chat_draft_id") or "") or None
        if draft_id and not session.get(ChatDraft, draft_id):
            raise ToolError("chat_draft_id not found", code="not_found")
        created: list[ChatDraftQuestion] = []
        for position, item in enumerate(questions):
            question = str(item.get("question") or "").strip() if isinstance(item, dict) else ""
            options = item.get("options") if isinstance(item, dict) else []
            if not question:
                raise ToolError("question text is required", code="invalid_input")
            if not isinstance(options, list) or len(options) == 0 or len(options) > 3:
                raise ToolError("each question must include one to three options", code="invalid_input")
            normalized_options = [
                {
                    "label": str(option.get("label") or "").strip(),
                    "description": str(option.get("description") or "").strip(),
                }
                for option in options
                if isinstance(option, dict) and str(option.get("label") or "").strip()
            ]
            if len(normalized_options) != len(options):
                raise ToolError("each option requires a label", code="invalid_input")
            created.append(
                ChatDraftQuestion(
                    chat_thread_id=thread_id,
                    chat_draft_id=draft_id,
                    question=question,
                    options_json=normalized_options,
                    batch_id=batch_id,
                    position=position,
                    status="pending",
                )
            )
        for question in created:
            session.add(question)
        session.commit()
        return {
            "success": True,
            "batch_id": batch_id,
            "questions": [_draft_question_payload(question) for question in created],
        }


@registry.tool(
    "draft",
    "Create or replace the active Draft Mode draft. Only the manifest orchestrator may call this tool.",
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "orchestrator_agent_id": {"type": "string"},
            "manifest_orchestrator_id": {"type": "string"},
            "orchestrator_agent_thread_id": {"type": "string"},
            "description_md": {"type": "string"},
        },
        "required": ["chat_thread_id", "description_md"],
        "additionalProperties": False,
    },
)
def draft(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    orchestrator_agent_id = str(args.get("agent_id") or args.get("orchestrator_agent_id") or "manifest-orchestrator")
    description = _string(args, "description_md")
    with Session(engine) as session:
        _require_manifest_orchestrator(session, thread_id, orchestrator_agent_id)
        _cancel_active_draft_gates(session, thread_id)
        item = ChatDraft(
            chat_thread_id=thread_id,
            manifest_orchestrator_id=str(args.get("manifest_orchestrator_id") or ""),
            orchestrator_agent_thread_id=str(args.get("orchestrator_agent_thread_id") or "") or None,
            description_md=description,
            status="active",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {"success": True, "draft": _draft_payload(item)}


@registry.tool(
    "get_active_draft",
    "Read the active Draft Mode draft and all Draft Mode questions for a chat.",
    {
        "type": "object",
        "properties": {"chat_thread_id": {"type": "string"}},
        "required": ["chat_thread_id"],
        "additionalProperties": False,
    },
)
def get_active_draft(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    with Session(engine) as session:
        draft_item = session.exec(
            select(ChatDraft)
            .where(ChatDraft.chat_thread_id == thread_id, ChatDraft.status.in_(["active", "accepted"]))
            .order_by(ChatDraft.updated_at.desc())
        ).first()
        pending_question = session.exec(
            select(ChatDraftQuestion)
            .where(ChatDraftQuestion.chat_thread_id == thread_id, ChatDraftQuestion.status == "pending")
            .order_by(ChatDraftQuestion.created_at.desc(), ChatDraftQuestion.position)
        ).first()
        questions = []
        if pending_question:
            questions = session.exec(
                select(ChatDraftQuestion)
                .where(
                    ChatDraftQuestion.chat_thread_id == thread_id,
                    ChatDraftQuestion.batch_id == pending_question.batch_id,
                    ChatDraftQuestion.status.in_(["pending", "answered"]),
                )
                .order_by(ChatDraftQuestion.position, ChatDraftQuestion.created_at)
            ).all()
        return {
            "success": True,
            "draft": _draft_payload(draft_item) if draft_item else None,
            "questions": [_draft_question_payload(question) for question in questions],
        }


@registry.tool(
    "start_discussion",
    "Create a deterministic Vibe discussion for two or more invokable Agents.",
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "title": {"type": "string"},
            "objective_md": {"type": "string"},
            "agent_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["chat_thread_id", "objective_md", "agent_ids"],
        "additionalProperties": False,
    },
)
def start_discussion(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    agent_ids = _unique_strings(args.get("agent_ids") or [])
    if len(agent_ids) < 2:
        raise ToolError("agent_ids must include at least two agents", code="invalid_input")
    with Session(engine) as session:
        if not session.get(ChatThread, thread_id):
            raise ToolError("chat_thread_id not found", code="not_found")
        for agent_id in agent_ids:
            if not session.get(Agent, agent_id):
                raise ToolError("agent_id not found", code="not_found")
        discussion = Discussion(
            chat_thread_id=thread_id,
            title=str(args.get("title") or "Discussion"),
            objective_md=_string(args, "objective_md"),
            current_agent_id=agent_ids[0],
        )
        session.add(discussion)
        session.commit()
        session.refresh(discussion)
        for position, agent_id in enumerate(agent_ids):
            session.add(
                DiscussionParticipant(
                    discussion_id=discussion.id,
                    agent_id=agent_id,
                    position=position,
                )
            )
        session.commit()
        return _discussion_detail_payload(session, discussion.id)


@registry.tool(
    "run_discussion",
    "Create and optionally wait for a deterministic discussion using the Forger Desktop runtime.",
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "title": {"type": "string"},
            "objective_md": {"type": "string"},
            "agent_ids": {"type": "array", "items": {"type": "string"}},
            "wait": {"type": "boolean"},
            "expose_progress": {"type": "boolean"},
            "max_rounds": {"type": "number"},
            "timeout_seconds": {"type": "number"},
            "orchestrator_agent_id": {"type": "string"},
        },
        "required": ["chat_thread_id", "objective_md", "agent_ids"],
        "additionalProperties": False,
    },
)
def run_discussion(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    orchestrator_agent_id = str(args.get("orchestrator_agent_id") or "manifest-orchestrator")
    wait = bool(args.get("wait", False))
    expose_progress = bool(args.get("expose_progress", False))
    max_rounds = int(args.get("max_rounds") or 2)
    timeout_seconds = int(args.get("timeout_seconds") or 600)
    with Session(engine) as session:
        _require_manifest_orchestrator(session, thread_id, orchestrator_agent_id)
        _require_no_blocking_draft_gate(session, thread_id)
    detail = start_discussion(args)
    if not wait:
        return detail
    discussion_id = detail["discussion"]["id"]
    deadline_timeout = max(1, timeout_seconds)
    for _ in range(max(1, max_rounds * max(1, len(detail.get("participants", []))))):
        with Session(engine) as session:
            discussion = session.get(Discussion, discussion_id)
            if not discussion or discussion.status != "running" or not discussion.current_agent_id:
                return _discussion_detail_payload(session, discussion_id)
            agent = session.get(Agent, discussion.current_agent_id)
            participant = session.exec(
                select(DiscussionParticipant).where(
                    DiscussionParticipant.discussion_id == discussion.id,
                    DiscussionParticipant.agent_id == discussion.current_agent_id,
                )
            ).first()
            if not agent or not participant:
                raise ToolError("discussion participant not found", code="not_found")
            prompt = render_agent_prompt(
                session,
                agent,
                "agentChatDiscussion",
                {
                    "discussion_id": discussion.id,
                    "discussionObjective": discussion.objective_md,
                    "turnPayload": _discussion_detail_payload(session, discussion.id),
                },
            )
            desktop_thread = desktop_create_agent_thread(
                title=discussion.title,
                manifest_agent_id="agentChatDiscussion",
                initial_prompt=prompt,
                runtime=_runtime_for_agent(agent),
                metadata={"vibeAgentId": agent.id, "chatThreadId": thread_id, "discussionId": discussion.id},
            )
            stored_thread = AgentThread(
                desktop_thread_id=str(desktop_thread.get("desktop_thread_id") or ""),
                agent_id=agent.id,
                manifest_agent_id="agentChatDiscussion",
                chat_thread_id=thread_id,
                discussion_id=discussion.id,
                owner_type="agent",
                invocation_mode="discussion",
                title=discussion.title,
                initial_prompt_snapshot_md=prompt,
                status="running",
            )
            session.add(stored_thread)
            session.commit()
            session.refresh(stored_thread)
            participant.agent_thread_id = stored_thread.id
            participant.updated_at = utcnow()
            session.add(participant)
            run = desktop_start_agent_run(
                desktop_thread_id=stored_thread.desktop_thread_id,
                message=f"Discussion turn: {discussion.title}",
                context=json.dumps(_discussion_detail_payload(session, discussion.id), indent=2),
                runtime=_runtime_for_agent(agent),
            )
            stored_run = AgentRun(
                agent_thread_id=stored_thread.id,
                desktop_run_id=str(run.get("desktop_run_id") or ""),
                trigger_type="discussion",
                trigger_id=discussion.id,
                status=str(run.get("status") or "queued"),
                input_md=discussion.objective_md,
                context_snapshot_md=prompt,
                started_at=utcnow(),
            )
            session.add(stored_run)
            if expose_progress:
                _write_progress(session, thread_id, agent.id, stored_thread.id, stored_run.desktop_run_id, "discussion_turn.started", f"{agent.name} started a discussion turn.")
            session.commit()
        final_run = desktop_wait_for_run(
            desktop_thread_id=stored_thread.desktop_thread_id,
            desktop_run_id=stored_run.desktop_run_id,
            timeout_seconds=deadline_timeout,
        )
        with Session(engine) as session:
            refreshed_run = session.get(AgentRun, stored_run.id)
            refreshed_thread = session.get(AgentThread, stored_thread.id)
            if refreshed_run:
                refreshed_run.status = str(final_run.get("status") or "completed")
                refreshed_run.finished_at = utcnow()
                refreshed_run.updated_at = utcnow()
                session.add(refreshed_run)
            if refreshed_thread:
                refreshed_thread.status = "idle"
                refreshed_thread.updated_at = utcnow()
                session.add(refreshed_thread)
            if expose_progress:
                _write_progress(session, thread_id, agent.id, stored_thread.id, stored_run.desktop_run_id, "discussion_turn.completed", f"{agent.name} completed a discussion turn.")
            session.commit()
            detail = _discussion_detail_payload(session, discussion_id)
            if detail["discussion"]["status"] != "running":
                return detail
    with Session(engine) as session:
        return _discussion_detail_payload(session, discussion_id)


@registry.tool(
    "write_discussion_message",
    "Append an Agent message to a deterministic Vibe discussion and advance to the next participant.",
    {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "agent_thread_id": {"type": "string"},
            "agent_run_id": {"type": "string"},
            "content_md": {"type": "string"},
            "end_discussion": {"type": "boolean"},
        },
        "required": ["discussion_id", "agent_id", "content_md"],
        "additionalProperties": False,
    },
)
def write_discussion_message(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    discussion_id = _string(args, "discussion_id")
    agent_id = _string(args, "agent_id")
    with Session(engine) as session:
        discussion = session.get(Discussion, discussion_id)
        if not discussion:
            raise ToolError("discussion_id not found", code="not_found")
        participant = session.exec(
            select(DiscussionParticipant).where(
                DiscussionParticipant.discussion_id == discussion.id,
                DiscussionParticipant.agent_id == agent_id,
            )
        ).first()
        if not participant:
            raise ToolError("agent is not a discussion participant", code="forbidden")
        position = len(session.exec(select(DiscussionMessage).where(DiscussionMessage.discussion_id == discussion.id)).all())
        message = DiscussionMessage(
            discussion_id=discussion.id,
            agent_id=agent_id,
            agent_thread_id=str(args.get("agent_thread_id") or "") or participant.agent_thread_id,
            agent_run_id=str(args.get("agent_run_id") or "") or None,
            content_md=_string(args, "content_md"),
            end_discussion=bool(args.get("end_discussion") is True),
            round_index=discussion.current_round,
            position=position,
        )
        session.add(message)
        participant.last_end_discussion = message.end_discussion
        participant.updated_at = utcnow()
        session.add(participant)
        _advance_discussion(session, discussion, participant)
        session.commit()
        return _discussion_detail_payload(session, discussion.id)


@registry.tool(
    "get_discussion_detail",
    "Inspect a Vibe discussion, including participants, ordered messages, state, and next Agent.",
    {
        "type": "object",
        "properties": {"discussion_id": {"type": "string"}},
        "required": ["discussion_id"],
        "additionalProperties": False,
    },
)
def get_discussion_detail(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        return _discussion_detail_payload(session, _string(args, "discussion_id"))


@registry.tool(
    "update_discussion_consensus",
    "Store the orchestrator-written consensus for a Vibe discussion.",
    {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string"},
            "consensus_md": {"type": "string"},
        },
        "required": ["discussion_id", "consensus_md"],
        "additionalProperties": False,
    },
)
def update_discussion_consensus(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        discussion = session.get(Discussion, _string(args, "discussion_id"))
        if not discussion:
            raise ToolError("discussion_id not found", code="not_found")
        discussion.consensus_md = _string(args, "consensus_md")
        discussion.updated_at = utcnow()
        session.add(discussion)
        session.commit()
        return _discussion_detail_payload(session, discussion.id)


@registry.tool(
    "get_notebook_entry",
    "Read a Vibe notebook entry by id or prompt-injected slug.",
    {
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "Notebook entry id or slug shown in the prompt notebook context.",
            },
        },
        "required": ["identifier"],
        "additionalProperties": False,
    },
)
def get_notebook_entry(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    identifier = _string(args, "identifier").strip()
    with Session(engine) as session:
        entry = session.get(NotebookEntry, identifier)
        if not entry:
            entries = session.exec(select(NotebookEntry)).all()
            entry = next((item for item in entries if notebook_slug(item) == identifier), None)
        if not entry:
            raise ToolError("notebook entry not found", code="not_found")
        return {
            "success": True,
            "entry": {
                "id": entry.id,
                "slug": notebook_slug(entry),
                "title": entry.title,
                "short_description": entry.short_description,
                "long_description_md": entry.long_description_md,
                "entry_type": entry.entry_type,
                "load_policy": entry.load_policy,
                "read_when": entry.read_when,
                "created_by_agent_id": entry.created_by_agent_id,
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
            },
        }


@registry.tool(
    "list_step_types",
    "List Vibe step types and their responsible execution mode.",
    {"type": "object", "properties": {}, "additionalProperties": False},
)
def list_step_types(_args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        return {
            "success": True,
            "step_types": [
                _step_type_payload(step_type)
                for step_type in session.exec(select(StepType).order_by(StepType.name)).all()
            ],
        }


@registry.tool(
    "create_step_type",
    "Create a Vibe step type. responsible must be agent, multiagents, human, script, or command.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "context_md": {"type": "string"},
            "main_task_md": {"type": "string"},
            "responsible": {"type": "string", "enum": ["agent", "multiagents", "human", "script", "command"]},
            "git_work": {"type": "boolean"},
        },
        "required": ["name", "responsible"],
        "additionalProperties": False,
    },
)
def create_step_type(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    responsible = _responsible(args.get("responsible"))
    with Session(engine) as session:
        step_type = StepType(
            name=_string(args, "name"),
            description=str(args.get("description") or "") or None,
            context_md=str(args.get("context_md") or ""),
            main_task_md=str(args.get("main_task_md") or ""),
            responsible=responsible,
            git_work=bool(args.get("git_work", True)),
        )
        session.add(step_type)
        session.commit()
        session.refresh(step_type)
        return {"success": True, "step_type": _step_type_payload(step_type)}


@registry.tool(
    "update_step_type",
    "Update a Vibe step type.",
    {
        "type": "object",
        "properties": {
            "step_type_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "context_md": {"type": "string"},
            "main_task_md": {"type": "string"},
            "responsible": {"type": "string", "enum": ["agent", "multiagents", "human", "script", "command"]},
            "git_work": {"type": "boolean"},
        },
        "required": ["step_type_id"],
        "additionalProperties": False,
    },
)
def update_step_type(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        step_type = session.get(StepType, _string(args, "step_type_id"))
        if not step_type:
            raise ToolError("step_type_id not found", code="not_found")
        for key in ("name", "description", "context_md", "main_task_md"):
            if key in args and args[key] is not None:
                setattr(step_type, key, str(args[key]))
        if "responsible" in args and args["responsible"] is not None:
            step_type.responsible = _responsible(args["responsible"])
        if "git_work" in args and args["git_work"] is not None:
            step_type.git_work = bool(args["git_work"])
        step_type.updated_at = utcnow()
        session.add(step_type)
        session.commit()
        session.refresh(step_type)
        return {"success": True, "step_type": _step_type_payload(step_type)}


@registry.tool(
    "delete_step_type",
    "Delete a Vibe step type. Use only when the user explicitly asks.",
    {
        "type": "object",
        "properties": {
            "step_type_id": {"type": "string"},
            "confirm_delete": {"type": "boolean"},
        },
        "required": ["step_type_id", "confirm_delete"],
        "additionalProperties": False,
    },
)
def delete_step_type(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    if args.get("confirm_delete") is not True:
        raise ToolError("confirm_delete must be true", code="confirmation_required")
    with Session(engine) as session:
        step_type = session.get(StepType, _string(args, "step_type_id"))
        if not step_type:
            raise ToolError("step_type_id not found", code="not_found")
        session.delete(step_type)
        session.commit()
        return {"success": True, "step_type_id": step_type.id}


@registry.tool(
    "list_scripts",
    "List editable Vibe scripts with source and env text.",
    {"type": "object", "properties": {}, "additionalProperties": False},
)
def list_scripts(_args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        return {
            "success": True,
            "scripts": [_script_payload(script) for script in session.exec(select(Script).order_by(Script.name)).all()],
        }


@registry.tool(
    "create_script",
    "Create an editable Vibe script under workspace/scripts/{slug}.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "slug": {"type": "string"},
            "description": {"type": "string"},
            "language": {"type": "string", "enum": ["python", "javascript", "typescript"]},
            "main_task_md": {"type": "string"},
            "source_code": {"type": "string"},
            "env_text": {"type": "string"},
        },
        "required": ["name", "language"],
        "additionalProperties": False,
    },
)
def create_script(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        slug = slugify_script(str(args.get("slug") or args.get("name") or "script"))
        if session.exec(select(Script).where(Script.slug == slug)).first():
            raise ToolError("script slug already exists", code="invalid_input")
        script = Script(
            name=_string(args, "name"),
            slug=slug,
            description=str(args.get("description") or "") or None,
            language=normalize_script_language(_string(args, "language")),
            main_task_md=str(args.get("main_task_md") or ""),
        )
        session.add(script)
        session.commit()
        session.refresh(script)
        write_script_files(script, str(args.get("source_code") or ""), str(args.get("env_text") or ""))
        return {"success": True, "script": _script_payload(script)}


@registry.tool(
    "update_script",
    "Update an editable Vibe script and its source or .env text.",
    {
        "type": "object",
        "properties": {
            "script_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "language": {"type": "string", "enum": ["python", "javascript", "typescript"]},
            "main_task_md": {"type": "string"},
            "source_code": {"type": "string"},
            "env_text": {"type": "string"},
        },
        "required": ["script_id"],
        "additionalProperties": False,
    },
)
def update_script(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    with Session(engine) as session:
        script = session.get(Script, _string(args, "script_id"))
        if not script:
            raise ToolError("script_id not found", code="not_found")
        for key in ("name", "description", "main_task_md"):
            if key in args and args[key] is not None:
                setattr(script, key, str(args[key]))
        if "language" in args and args["language"] is not None:
            script.language = normalize_script_language(str(args["language"]))
        script.updated_at = utcnow()
        session.add(script)
        session.commit()
        session.refresh(script)
        write_script_files(script, args.get("source_code"), args.get("env_text"))
        return {"success": True, "script": _script_payload(script)}


@registry.tool(
    "delete_script",
    "Delete a Vibe script database record. Use only when the user explicitly asks.",
    {
        "type": "object",
        "properties": {
            "script_id": {"type": "string"},
            "confirm_delete": {"type": "boolean"},
        },
        "required": ["script_id", "confirm_delete"],
        "additionalProperties": False,
    },
)
def delete_script(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    if args.get("confirm_delete") is not True:
        raise ToolError("confirm_delete must be true", code="confirmation_required")
    with Session(engine) as session:
        script = session.get(Script, _string(args, "script_id"))
        if not script:
            raise ToolError("script_id not found", code="not_found")
        delete_script_files(script)
        session.delete(script)
        session.commit()
        return {"success": True, "script_id": script.id}


@registry.tool(
    "create_plan_from_intake",
    (
        "Create a Vibe plan from a feature-intake chat. The manifest orchestrator owns this call. "
        "Steps must be executable implementation, migration, wiring, test, review, or release work. "
        "Clarifications, definitions, specs, architecture decisions, acceptance criteria, and open questions "
        "belong in description/context_md, not as standalone steps."
    ),
    {
        "type": "object",
        "properties": {
            "chat_thread_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {
                "type": "string",
                "description": "Plan summary including the clarified user-facing goal and accepted scope.",
            },
            "context_md": {
                "type": "string",
                "description": "Clarified definitions, decisions, acceptance criteria, risks, and open questions.",
            },
            "steps": {
                "type": "array",
                "description": (
                    "Executable work only. Do not include definition-only, scoping-only, or spec-writing steps; "
                    "resolve those in chat and store the outcome in description/context_md."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "depends_on_step_indexes": {"type": "array", "items": {"type": "number"}},
                        "step_type_id": {"type": "string"},
                        "script_id": {"type": "string"},
                        "script_args_text": {"type": "string"},
                        "command_text": {"type": "string"},
                        "command_timeout_seconds": {"type": "number"},
                        "repository_ids": {"type": "array", "items": {"type": "string"}},
                        "assignments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "agent_id": {"type": "string"},
                                    "instructions_md": {"type": "string"},
                                },
                                "required": ["agent_id", "instructions_md"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["name", "description", "step_type_id"],
                    "additionalProperties": False,
                },
            },
            "repositories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "repository_id": {"type": "string"},
                        "start_ref": {"type": "string"},
                    },
                    "required": ["repository_id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["chat_thread_id", "agent_id", "name", "description", "steps"],
        "additionalProperties": False,
    },
)
def create_plan_from_intake(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    thread_id = _string(args, "chat_thread_id")
    agent_id = _string(args, "agent_id")
    steps_payload = args.get("steps")
    if not isinstance(steps_payload, list) or not steps_payload:
        raise ToolError("steps must be a non-empty array", code="invalid_input")
    with Session(engine) as session:
        try:
            _require_manifest_orchestrator(session, thread_id, agent_id)
            accepted_draft = _require_accepted_draft(session, thread_id)
            plan = Plan(
                name=_string(args, "name"),
                description=_string(args, "description"),
                context_md=str(args.get("context_md") or ""),
            )
            session.add(plan)
            session.flush()
            for item in args.get("repositories") or []:
                if not isinstance(item, dict):
                    continue
                repository = session.get(
                    GitRepository,
                    _required_string(item, "repository_id"),
                )
                if not repository:
                    raise ToolError("repository_id not found", code="not_found")
                session.add(
                    PlanRepository(
                        plan_id=plan.id,
                        repository_id=repository.id,
                        start_ref=str(
                            item.get("start_ref") or repository.default_branch
                        ),
                    )
                )
            plan_chat = ChatThread(thread_type="planChatOrchestrator", title=plan.name)
            session.add(plan_chat)
            session.flush()
            session.add(PlanChatThread(plan_id=plan.id, chat_thread_id=plan_chat.id))

            created_steps: list[Step] = []
            for item in steps_payload:
                if not isinstance(item, dict):
                    raise ToolError("step items must be objects", code="invalid_input")
                _reject_legacy_step_kind(item)
                step_type = _required_step_type(session, item.get("step_type_id"))
                _validate_create_plan_step_payload(item, step_type)
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
                        session.add(
                            StepRepository(
                                step_id=step.id,
                                repository_id=repository_id,
                            )
                        )
                script_id = str(item.get("script_id") or "")
                if script_id:
                    session.add(
                        ScriptStep(
                            step_id=step.id,
                            script_id=script_id,
                            args_text=str(item.get("script_args_text") or ""),
                        )
                    )
                command_text = str(item.get("command_text") or "")
                if command_text.strip():
                    timeout = int(item.get("command_timeout_seconds") or 600)
                    if timeout < 1:
                        raise ToolError(
                            "command_timeout_seconds must be at least 1",
                            code="invalid_input",
                        )
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
                                instructions_md=_required_string(
                                    assignment,
                                    "instructions_md",
                                ),
                            )
                        )
                session.flush()
                _validate_step_contract(session, step)

            for index, item in enumerate(steps_payload):
                if not isinstance(item, dict):
                    continue
                for dependency_index in item.get("depends_on_step_indexes") or []:
                    if (
                        isinstance(dependency_index, int)
                        and 0 <= dependency_index < len(created_steps)
                    ):
                        session.add(
                            StepDependency(
                                step_id=created_steps[index].id,
                                depends_on_step_id=created_steps[dependency_index].id,
                            )
                        )
            accepted_draft.status = "implemented"
            accepted_draft.updated_at = utcnow()
            session.add(accepted_draft)
            session.commit()
            return {
                "success": True,
                "plan_id": plan.id,
                "chat_thread_id": plan_chat.id,
                "step_ids": [step.id for step in created_steps],
            }
        except Exception:
            session.rollback()
            raise


@registry.tool(
    "update_plan",
    "Update high-level Vibe plan fields: name, description, context, and status.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "context_md": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["plan_id", "agent_id"],
        "additionalProperties": False,
    },
)
def update_plan(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    agent_id = _string(args, "agent_id")
    updates = {
        key: args[key]
        for key in ("name", "description", "context_md", "status")
        if key in args and args[key] is not None
    }
    if not updates:
        raise ToolError("at least one plan field must be provided", code="invalid_input")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        for key, value in updates.items():
            if key == "name" and not str(value).strip():
                raise ToolError("name cannot be blank", code="invalid_input")
            setattr(plan, key, str(value))
        plan.updated_at = utcnow()
        session.add(plan)
        session.commit()
        session.refresh(plan)
        return {
            "success": True,
            "plan": {
                "id": plan.id,
                "name": plan.name,
                "description": plan.description,
                "context_md": plan.context_md,
                "status": plan.status,
                "updated_at": plan.updated_at.isoformat(),
            },
        }


@registry.tool(
    "create_plan_step",
    "Create a pending typed step in a Vibe plan. The manifest orchestrator owns this call.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "step_type_id": {"type": "string"},
            "position": {"type": "number"},
            "depends_on_step_ids": {"type": "array", "items": {"type": "string"}},
            "repository_ids": {"type": "array", "items": {"type": "string"}},
            "script_id": {"type": "string"},
            "script_args_text": {"type": "string"},
            "command_text": {"type": "string"},
            "command_timeout_seconds": {"type": "number"},
        },
        "required": ["plan_id", "agent_id", "name", "description", "step_type_id"],
        "additionalProperties": False,
    },
)
def create_plan_step(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    agent_id = _string(args, "agent_id")
    _reject_legacy_step_kind(args)
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        _ensure_plan_mutable(plan)
        step_type = _required_step_type(session, args.get("step_type_id"))
        position = args.get("position")
        if not isinstance(position, int):
            position = len(session.exec(select(Step).where(Step.plan_id == plan.id)).all())
        step = Step(
            plan_id=plan.id,
            step_type_id=step_type.id,
            name=_string(args, "name"),
            description=_string(args, "description"),
            kind=_legacy_kind_for_step_type(step_type),
            position=position,
        )
        session.add(step)
        session.commit()
        session.refresh(step)
        _replace_step_dependencies(session, step, args.get("depends_on_step_ids") or [])
        _replace_step_repositories(session, step, args.get("repository_ids") or [])
        _replace_script_step(session, step, str(args.get("script_id") or "") or None, str(args.get("script_args_text") or ""))
        _replace_command_step(session, step, str(args.get("command_text") or ""), int(args.get("command_timeout_seconds") or 600))
        _validate_step_contract(session, step)
        plan.updated_at = utcnow()
        session.add(plan)
        session.commit()
        session.refresh(step)
        return {"success": True, "step": _step_payload(step)}


@registry.tool(
    "update_plan_step",
    "Update a pending Vibe plan step. Completed, running, blocked, failed, or canceled steps cannot be edited.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "step_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "step_type_id": {"type": "string"},
            "position": {"type": "number"},
            "depends_on_step_ids": {"type": "array", "items": {"type": "string"}},
            "repository_ids": {"type": "array", "items": {"type": "string"}},
            "script_id": {"type": "string"},
        },
        "required": ["plan_id", "step_id", "agent_id"],
        "additionalProperties": False,
    },
)
def update_plan_step(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    _reject_legacy_step_kind(args)
    plan_id = _string(args, "plan_id")
    step_id = _string(args, "step_id")
    agent_id = _string(args, "agent_id")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        _ensure_plan_mutable(plan)
        step = _step_for_plan(session, plan, step_id)
        _ensure_step_mutable(step)
        if "name" in args and args["name"] is not None:
            step.name = _string(args, "name")
        if "description" in args and args["description"] is not None:
            step.description = _string(args, "description")
        if "step_type_id" in args:
            step_type = _required_step_type(session, args.get("step_type_id"))
            step.step_type_id = step_type.id
            step.kind = _legacy_kind_for_step_type(step_type)
        if "position" in args and isinstance(args["position"], int):
            step.position = int(args["position"])
        if "depends_on_step_ids" in args:
            _replace_step_dependencies(session, step, args.get("depends_on_step_ids") or [])
        if "repository_ids" in args:
            _replace_step_repositories(session, step, args.get("repository_ids") or [])
        if "script_id" in args:
            _replace_script_step(session, step, str(args.get("script_id") or "") or None, str(args.get("script_args_text") or ""))
        elif "script_args_text" in args:
            _replace_script_step(session, step, None, str(args.get("script_args_text") or ""))
        if "command_text" in args or "command_timeout_seconds" in args:
            _replace_command_step(
                session,
                step,
                str(args.get("command_text")) if "command_text" in args and args.get("command_text") is not None else None,
                int(args.get("command_timeout_seconds")) if "command_timeout_seconds" in args and args.get("command_timeout_seconds") is not None else None,
            )
        _validate_step_contract(session, step)
        step.updated_at = utcnow()
        plan.updated_at = utcnow()
        session.add(step)
        session.add(plan)
        session.commit()
        session.refresh(step)
        return {"success": True, "step": _step_payload(step)}


@registry.tool(
    "delete_plan_step",
    "Delete a pending Vibe plan step and its dependencies/assignments. Completed, running, blocked, failed, or canceled steps cannot be deleted.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "step_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "confirm_delete": {"type": "boolean"},
        },
        "required": ["plan_id", "step_id", "agent_id", "confirm_delete"],
        "additionalProperties": False,
    },
)
def delete_plan_step(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    if args.get("confirm_delete") is not True:
        raise ToolError("confirm_delete must be true", code="confirmation_required")
    plan_id = _string(args, "plan_id")
    step_id = _string(args, "step_id")
    agent_id = _string(args, "agent_id")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        _ensure_plan_mutable(plan)
        step = _step_for_plan(session, plan, step_id)
        _ensure_step_mutable(step)
        _delete_step_children(session, step)
        session.delete(step)
        plan.updated_at = utcnow()
        session.add(plan)
        session.commit()
        return {"success": True, "step_id": step_id}


@registry.tool(
    "create_step_assignment",
    "Assign an Agent to a pending plan step. The manifest orchestrator owns this call.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "step_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "assigned_agent_id": {"type": "string"},
            "instructions_md": {"type": "string"},
        },
        "required": ["plan_id", "step_id", "agent_id", "assigned_agent_id", "instructions_md"],
        "additionalProperties": False,
    },
)
def create_step_assignment(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    step_id = _string(args, "step_id")
    agent_id = _string(args, "agent_id")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        _ensure_plan_mutable(plan)
        step = _step_for_plan(session, plan, step_id)
        _ensure_step_mutable(step)
        _ensure_assignment_allowed(session, step)
        assignment = StepAssignment(
            step_id=step.id,
            agent_id=_string(args, "assigned_agent_id"),
            instructions_md=_string(args, "instructions_md"),
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)
        return {"success": True, "assignment": _assignment_payload(assignment)}


@registry.tool(
    "update_step_assignment",
    "Update an assignment on a pending plan step. The parent step must not be completed, running, blocked, failed, or canceled.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "assignment_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "assigned_agent_id": {"type": "string"},
            "instructions_md": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["plan_id", "assignment_id", "agent_id"],
        "additionalProperties": False,
    },
)
def update_step_assignment(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    assignment_id = _string(args, "assignment_id")
    agent_id = _string(args, "agent_id")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        _ensure_plan_mutable(plan)
        assignment = session.get(StepAssignment, assignment_id)
        if not assignment:
            raise ToolError("assignment_id not found", code="not_found")
        step = _step_for_plan(session, plan, assignment.step_id)
        _ensure_step_mutable(step)
        if "assigned_agent_id" in args and args["assigned_agent_id"] is not None:
            assignment.agent_id = _string(args, "assigned_agent_id")
        if "instructions_md" in args and args["instructions_md"] is not None:
            assignment.instructions_md = _string(args, "instructions_md")
        if "status" in args and args["status"] is not None:
            assignment.status = _string(args, "status")
        assignment.updated_at = utcnow()
        session.add(assignment)
        session.commit()
        session.refresh(assignment)
        return {"success": True, "assignment": _assignment_payload(assignment)}


@registry.tool(
    "delete_step_assignment",
    "Delete an assignment from a pending plan step. The parent step must not be completed, running, blocked, failed, or canceled.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "assignment_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "confirm_delete": {"type": "boolean"},
        },
        "required": ["plan_id", "assignment_id", "agent_id", "confirm_delete"],
        "additionalProperties": False,
    },
)
def delete_step_assignment(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    if args.get("confirm_delete") is not True:
        raise ToolError("confirm_delete must be true", code="confirmation_required")
    plan_id = _string(args, "plan_id")
    assignment_id = _string(args, "assignment_id")
    agent_id = _string(args, "agent_id")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        _ensure_plan_mutable(plan)
        assignment = session.get(StepAssignment, assignment_id)
        if not assignment:
            raise ToolError("assignment_id not found", code="not_found")
        step = _step_for_plan(session, plan, assignment.step_id)
        _ensure_step_mutable(step)
        session.delete(assignment)
        session.commit()
        return {"success": True, "assignment_id": assignment_id}


@registry.tool(
    "delete_plan",
    "Delete a Vibe plan and its plan chats, steps, assignments, and associated agent thread links.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "confirm_delete": {
                "type": "boolean",
                "description": "Must be true. Agents should only delete after explicit user intent.",
            },
        },
        "required": ["plan_id", "agent_id", "confirm_delete"],
        "additionalProperties": False,
    },
)
def delete_plan(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    agent_id = _string(args, "agent_id")
    if args.get("confirm_delete") is not True:
        raise ToolError("confirm_delete must be true", code="confirmation_required")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        delete_plan_cascade(session, plan)
        session.commit()
        return {"success": True, "plan_id": plan_id}


@registry.tool(
    "write_notebook_entry",
    "Write a Vibe notebook entry for reusable project, plan, repository, or agent memory.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "agent_id": {"type": "string"},
            "chat_thread_id": {"type": "string"},
            "plan_id": {"type": "string"},
            "short_description": {"type": "string"},
            "long_description_md": {"type": "string"},
            "entry_type": {"type": "string"},
            "load_policy": {"type": "string"},
            "read_when": {"type": "string"},
        },
        "required": ["title", "long_description_md", "agent_id"],
        "additionalProperties": False,
    },
)
def write_notebook_entry(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    agent_id = _string(args, "agent_id")
    entry = NotebookEntry(
        title=_string(args, "title"),
        short_description=str(args.get("short_description") or ""),
        long_description_md=_string(args, "long_description_md"),
        entry_type=str(args.get("entry_type") or "log"),
        load_policy=str(args.get("load_policy") or "retrieval"),
        read_when=str(args.get("read_when") or "") or None,
        created_by_agent_id=agent_id,
    )
    with Session(engine) as session:
        chat_thread_id = str(args.get("chat_thread_id") or "")
        plan_id = str(args.get("plan_id") or "")
        if chat_thread_id:
            _require_chat_orchestrator(session, chat_thread_id, agent_id)
        elif plan_id:
            plan = session.get(Plan, plan_id)
            if not plan:
                raise ToolError("plan_id not found", code="not_found")
            _require_plan_orchestrator(session, plan, agent_id)
        else:
            raise ToolError("chat_thread_id or plan_id is required for notebook writes", code="invalid_input")
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return {"success": True, "notebook_entry_id": entry.id}


@registry.tool(
    "mark_step_blocked",
    "Pause a running plan step as blocked with a concrete reason. The manifest orchestrator owns this call.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "step_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "reason_md": {"type": "string"},
        },
        "required": ["plan_id", "step_id", "agent_id", "reason_md"],
        "additionalProperties": False,
    },
)
def mark_step_blocked(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    step_id = _string(args, "step_id")
    agent_id = _string(args, "agent_id")
    reason = _string(args, "reason_md")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        step = session.get(Step, step_id)
        if not step or step.plan_id != plan.id:
            raise ToolError("step_id not found for plan", code="not_found")
        if step.status != "running":
            raise ToolError("only running steps can be blocked", code="invalid_state")
        execution = _latest_execution_for_step(session, step.id)
        if not execution:
            raise ToolError("step has no execution to block", code="not_found")
        execution.status = "blocked"
        execution.result_md = reason
        execution.updated_at = utcnow()
        step.status = "blocked"
        step.result_md = reason
        step.updated_at = utcnow()
        plan.status = "awaiting_review"
        plan.updated_at = utcnow()
        session.add(execution)
        session.add(step)
        session.add(plan)
        session.commit()
        return {
            "success": True,
            "step": _step_payload(step),
            "execution": _execution_payload(execution),
            "plan": _plan_payload(plan),
        }


@registry.tool(
    "resume_blocked_step",
    "Resume a blocked plan step with user-approved unblock guidance. The manifest orchestrator owns this call.",
    {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "step_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "resume_message_md": {
                "type": "string",
                "description": "Concrete guidance from the user or orchestrator explaining how to continue.",
            },
        },
        "required": ["plan_id", "step_id", "agent_id", "resume_message_md"],
        "additionalProperties": False,
    },
)
def resume_blocked_step(args: dict[str, Any]) -> dict[str, Any]:
    init_app_db()
    plan_id = _string(args, "plan_id")
    step_id = _string(args, "step_id")
    agent_id = _string(args, "agent_id")
    note = _string(args, "resume_message_md")
    with Session(engine) as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise ToolError("plan_id not found", code="not_found")
        _require_plan_orchestrator(session, plan, agent_id)
        step = session.get(Step, step_id)
        if not step or step.plan_id != plan.id:
            raise ToolError("step_id not found for plan", code="not_found")
        if step.status != "blocked":
            raise ToolError("only blocked steps can be resumed", code="invalid_state")
        execution = _latest_execution_for_step(session, step.id)
        if not execution or execution.status != "blocked":
            raise ToolError("step has no blocked execution to resume", code="not_found")
        previous = execution.result_md.strip()
        execution.result_md = f"{previous}\n\nResume guidance:\n{note}".strip()
        execution.status = "running"
        execution.updated_at = utcnow()
        step.status = "running"
        step.result_md = execution.result_md
        step.updated_at = utcnow()
        plan.status = "running"
        plan.updated_at = utcnow()
        session.add(execution)
        session.add(step)
        session.add(plan)
        session.commit()
        return {
            "success": True,
            "step": _step_payload(step),
            "execution": _execution_payload(execution),
            "plan": _plan_payload(plan),
        }


def _string(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{name} is required", code="invalid_input")
    return value.strip()


def _required_string(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{name} is required", code="invalid_input")
    return value.strip()


def _checkout_payload(checkout: WorkspaceCheckout | None) -> dict[str, Any] | None:
    if not checkout:
        return None
    return {
        "id": checkout.id,
        "path": checkout.path,
        "branch": checkout.branch,
        "base_ref": checkout.base_ref,
        "status": checkout.status,
        "last_synced_at": checkout.last_synced_at.isoformat() if checkout.last_synced_at else None,
    }


def _latest_execution_for_step(session: Session, step_id: str) -> StepExecution | None:
    return session.exec(
        select(StepExecution)
        .where(StepExecution.step_id == step_id)
        .order_by(StepExecution.created_at.desc())
    ).first()


def _ensure_plan_mutable(plan: Plan) -> None:
    if plan.status == "running":
        raise ToolError("plans cannot be edited while steps are running", code="invalid_state")


def _ensure_step_mutable(step: Step) -> None:
    if step.status in {"completed", "failed", "canceled", "running", "blocked"}:
        raise ToolError("only pending steps can be edited", code="invalid_state")


def _step_responsible(session: Session, step: Step) -> str:
    step_type = session.get(StepType, step.step_type_id) if step.step_type_id else None
    if step_type and step_type.responsible:
        return step_type.responsible
    return "agent"


def _required_step_type(session: Session, value: object) -> StepType:
    step_type_id = str(value or "").strip()
    if not step_type_id:
        raise ToolError("step_type_id is required", code="invalid_input")
    step_type = session.get(StepType, step_type_id)
    if not step_type:
        raise ToolError("step_type_id not found", code="not_found")
    return step_type


def _legacy_kind_for_step_type(step_type: StepType) -> str:
    if step_type.name.lower() == "review" or step_type.responsible == "human":
        return "review"
    return "programming"


def _validate_create_plan_step_payload(
    item: dict[str, Any],
    step_type: StepType,
) -> None:
    responsible = step_type.responsible or "agent"
    script_id = str(item.get("script_id") or "")
    command_text = str(item.get("command_text") or "")
    if responsible == "script" and not script_id.strip():
        raise ToolError("script steps require a script", code="invalid_input")
    if responsible != "script" and script_id.strip():
        raise ToolError(
            "only script steps can reference a script",
            code="invalid_input",
        )
    if responsible == "command" and not command_text.strip():
        raise ToolError("command steps require a command", code="invalid_input")
    if responsible != "command" and command_text.strip():
        raise ToolError(
            "only command steps can reference a command",
            code="invalid_input",
        )


def _reject_legacy_step_kind(args: dict[str, Any]) -> None:
    if "kind" in args:
        raise ToolError("kind is no longer accepted; use step_type_id", code="invalid_input")


def _ensure_assignment_allowed(session: Session, step: Step) -> None:
    responsible = _step_responsible(session, step)
    if responsible in {"human", "script", "command"}:
        raise ToolError(f"{responsible} steps cannot have agent assignments", code="invalid_state")
    if responsible == "agent":
        existing = session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all()
        if existing:
            raise ToolError("agent steps can have exactly one assignment", code="invalid_state")


def _step_for_plan(session: Session, plan: Plan, step_id: str) -> Step:
    step = session.get(Step, step_id)
    if not step or step.plan_id != plan.id:
        raise ToolError("step_id not found for plan", code="not_found")
    return step


def _replace_step_dependencies(session: Session, step: Step, dependency_ids: object) -> None:
    if not isinstance(dependency_ids, list):
        raise ToolError("depends_on_step_ids must be an array", code="invalid_input")
    _assert_no_dependency_cycle(session, step, dependency_ids)
    for dependency in session.exec(select(StepDependency).where(StepDependency.step_id == step.id)).all():
        session.delete(dependency)
    for dependency_id in dependency_ids:
        if not isinstance(dependency_id, str) or not dependency_id.strip():
            raise ToolError("depends_on_step_ids must contain step ids", code="invalid_input")
        dependency_step = session.get(Step, dependency_id)
        if not dependency_step or dependency_step.plan_id != step.plan_id:
            raise ToolError("dependency step_id not found for plan", code="not_found")
        if dependency_step.id == step.id:
            raise ToolError("step cannot depend on itself", code="invalid_input")
        session.add(StepDependency(step_id=step.id, depends_on_step_id=dependency_step.id))


def _assert_no_dependency_cycle(session: Session, step: Step, dependency_ids: list[Any]) -> None:
    steps = session.exec(select(Step).where(Step.plan_id == step.plan_id)).all()
    step_ids = [item.id for item in steps]
    dependencies = session.exec(select(StepDependency).where(StepDependency.step_id.in_(step_ids))).all() if step_ids else []
    graph: dict[str, set[str]] = {item.id: set() for item in steps}
    next_dependencies = {str(item) for item in dependency_ids if isinstance(item, str)}
    for dependency in dependencies:
        if dependency.step_id != step.id:
            graph.setdefault(dependency.step_id, set()).add(dependency.depends_on_step_id)
    graph.setdefault(step.id, set()).update(next_dependencies)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dependency_id in graph.get(node, set()):
            if dependency_id == node or visit(dependency_id):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(visit(node) for node in graph):
        raise ToolError("step dependencies cannot contain cycles", code="invalid_input")


def _replace_step_repositories(session: Session, step: Step, repository_ids: object) -> None:
    if not isinstance(repository_ids, list):
        raise ToolError("repository_ids must be an array", code="invalid_input")
    for link in session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all():
        session.delete(link)
    for repository_id in repository_ids:
        if not isinstance(repository_id, str) or not repository_id.strip():
            raise ToolError("repository_ids must contain repository ids", code="invalid_input")
        repository = session.get(GitRepository, repository_id)
        if not repository:
            raise ToolError("repository_id not found", code="not_found")
        session.add(StepRepository(step_id=step.id, repository_id=repository.id))


def _replace_script_step(session: Session, step: Step, script_id: str | None, args_text: str | None = None) -> None:
    existing = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).all()
    if script_id:
        script = session.get(Script, script_id)
        if not script:
            raise ToolError("script_id not found", code="not_found")
        for link in existing:
            session.delete(link)
        session.add(ScriptStep(step_id=step.id, script_id=script.id, args_text=args_text or ""))
        return
    if args_text is not None and existing:
        for link in existing:
            link.args_text = args_text
            session.add(link)
        return
    for link in existing:
        session.delete(link)


def _replace_command_step(
    session: Session,
    step: Step,
    command_text: str | None,
    timeout_seconds: int | None = None,
) -> None:
    existing = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
    if command_text is None and timeout_seconds is None:
        return
    text = command_text if command_text is not None else (existing.command_text if existing else "")
    timeout = timeout_seconds if timeout_seconds is not None else (existing.timeout_seconds if existing else 600)
    if timeout < 1:
        raise ToolError("command_timeout_seconds must be at least 1", code="invalid_input")
    if not text.strip():
        if existing:
            session.delete(existing)
        return
    if existing:
        existing.command_text = text
        existing.timeout_seconds = timeout
        existing.updated_at = utcnow()
        session.add(existing)
    else:
        session.add(CommandStep(step_id=step.id, command_text=text, timeout_seconds=timeout))


def _validate_step_contract(session: Session, step: Step) -> None:
    if not step.step_type_id:
        raise ToolError("step_type_id is required", code="invalid_input")
    responsible = _step_responsible(session, step)
    script_link = session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).first()
    command_link = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).first()
    if responsible == "script" and not script_link:
        raise ToolError("script steps require a script", code="invalid_input")
    if responsible != "script" and script_link:
        raise ToolError("only script steps can reference a script", code="invalid_input")
    if responsible == "command" and not command_link:
        raise ToolError("command steps require a command", code="invalid_input")
    if responsible != "command" and command_link:
        raise ToolError("only command steps can reference a command", code="invalid_input")


def _delete_step_children(session: Session, step: Step) -> None:
    executions = session.exec(select(StepExecution).where(StepExecution.step_id == step.id)).all()
    execution_ids = [execution.id for execution in executions]
    command_steps = session.exec(select(CommandStep).where(CommandStep.step_id == step.id)).all()
    command_step_ids = [link.id for link in command_steps]
    if execution_ids:
        for link in session.exec(
            select(StepExecutionAgentThread).where(StepExecutionAgentThread.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(link)
        for commit in session.exec(select(StepCommit).where(StepCommit.step_execution_id.in_(execution_ids))).all():
            session.delete(commit)
        for result in session.exec(
            select(ScriptExecutionResult).where(ScriptExecutionResult.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(result)
        for result in session.exec(
            select(CommandExecutionResult).where(CommandExecutionResult.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(result)
    if command_step_ids:
        for result in session.exec(
            select(CommandExecutionResult).where(CommandExecutionResult.command_step_id.in_(command_step_ids))
        ).all():
            session.delete(result)
    for result in session.exec(select(ScriptExecutionResult).where(ScriptExecutionResult.step_id == step.id)).all():
        session.delete(result)
    for result in session.exec(select(CommandExecutionResult).where(CommandExecutionResult.step_id == step.id)).all():
        session.delete(result)
    for execution in executions:
        session.delete(execution)
    assignments = session.exec(select(StepAssignment).where(StepAssignment.step_id == step.id)).all()
    assignment_ids = [assignment.id for assignment in assignments]
    if assignment_ids:
        for link in session.exec(
            select(StepAssignmentAgentThread).where(StepAssignmentAgentThread.step_assignment_id.in_(assignment_ids))
        ).all():
            session.delete(link)
    for assignment in assignments:
        session.delete(assignment)
    for link in session.exec(select(StepRepository).where(StepRepository.step_id == step.id)).all():
        session.delete(link)
    for link in session.exec(select(ScriptStep).where(ScriptStep.step_id == step.id)).all():
        session.delete(link)
    for link in command_steps:
        session.delete(link)
    for dependency in session.exec(
        select(StepDependency).where(
            (StepDependency.step_id == step.id) | (StepDependency.depends_on_step_id == step.id)
        )
    ).all():
        session.delete(dependency)


def _step_payload(step: Step) -> dict[str, Any]:
    return {
        "id": step.id,
        "plan_id": step.plan_id,
        "step_type_id": step.step_type_id,
        "name": step.name,
        "description": step.description,
        "position": step.position,
        "status": step.status,
        "result_md": step.result_md,
        "git_commit": step.git_commit,
        "updated_at": step.updated_at.isoformat(),
    }


def _assignment_payload(assignment: StepAssignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "step_id": assignment.step_id,
        "agent_id": assignment.agent_id,
        "instructions_md": assignment.instructions_md,
        "status": assignment.status,
        "created_at": assignment.created_at.isoformat(),
        "updated_at": assignment.updated_at.isoformat(),
    }


def _execution_payload(execution: StepExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "step_id": execution.step_id,
        "status": execution.status,
        "orchestrator_agent_thread_id": execution.orchestrator_agent_thread_id,
        "result_md": execution.result_md,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "updated_at": execution.updated_at.isoformat(),
    }


def _plan_payload(plan: Plan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "execution_mode": plan.execution_mode,
        "updated_at": plan.updated_at.isoformat(),
    }


def _dependency_payload(dependency: StepDependency) -> dict[str, Any]:
    return {
        "id": dependency.id,
        "step_id": dependency.step_id,
        "depends_on_step_id": dependency.depends_on_step_id,
    }


def _plan_repository_payload(repository: PlanRepository) -> dict[str, Any]:
    return {
        "id": repository.id,
        "plan_id": repository.plan_id,
        "repository_id": repository.repository_id,
        "start_ref": repository.start_ref,
        "resolved_start_commit": repository.resolved_start_commit,
        "plan_branch": repository.plan_branch,
        "checkout_path": repository.checkout_path,
        "status": repository.status,
        "updated_at": repository.updated_at.isoformat(),
    }


def _step_repository_payload(link: StepRepository) -> dict[str, Any]:
    return {
        "id": link.id,
        "step_id": link.step_id,
        "repository_id": link.repository_id,
    }


def _step_type_payload(step_type: StepType) -> dict[str, Any]:
    return {
        "id": step_type.id,
        "name": step_type.name,
        "description": step_type.description,
        "context_md": step_type.context_md,
        "main_task_md": step_type.main_task_md,
        "responsible": step_type.responsible,
        "git_work": step_type.git_work,
        "created_at": step_type.created_at.isoformat(),
        "updated_at": step_type.updated_at.isoformat(),
    }


def _script_payload(script: Script) -> dict[str, Any]:
    return {
        "id": script.id,
        "name": script.name,
        "slug": script.slug,
        "description": script.description,
        "language": script.language,
        "main_task_md": script.main_task_md,
        "metadata_json": script.metadata_json,
        "source_code": read_script_source(script),
        "env_text": read_script_env(script),
        "created_at": script.created_at.isoformat(),
        "updated_at": script.updated_at.isoformat(),
    }


def _script_step_payload(link: ScriptStep) -> dict[str, Any]:
    return {
        "id": link.id,
        "step_id": link.step_id,
        "script_id": link.script_id,
        "args_text": link.args_text,
        "created_at": link.created_at.isoformat(),
    }


def _command_step_payload(link: CommandStep) -> dict[str, Any]:
    return {
        "id": link.id,
        "step_id": link.step_id,
        "command_text": link.command_text,
        "shell": link.shell,
        "timeout_seconds": link.timeout_seconds,
        "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat(),
    }


def _script_result_payload(result: ScriptExecutionResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "step_execution_id": result.step_execution_id,
        "step_id": result.step_id,
        "script_id": result.script_id,
        "repository_id": result.repository_id,
        "cwd": result.cwd,
        "status": result.status,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
    }


def _command_result_payload(result: CommandExecutionResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "step_execution_id": result.step_execution_id,
        "step_id": result.step_id,
        "command_step_id": result.command_step_id,
        "repository_id": result.repository_id,
        "cwd": result.cwd,
        "command_text": result.command_text,
        "status": result.status,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
    }


def _commit_payload(commit: StepCommit) -> dict[str, Any]:
    return {
        "id": commit.id,
        "step_execution_id": commit.step_execution_id,
        "step_id": commit.step_id,
        "repository_id": commit.repository_id,
        "commit_sha": commit.commit_sha,
        "commit_message": commit.commit_message,
        "created_at": commit.created_at.isoformat(),
    }


def _eligible_steps(steps: list[Step], dependencies: list[StepDependency]) -> list[Step]:
    complete = {step.id for step in steps if step.status == "completed"}
    pending = [step for step in steps if step.status == "pending"]
    by_step: dict[str, set[str]] = {}
    for dependency in dependencies:
        by_step.setdefault(dependency.step_id, set()).add(dependency.depends_on_step_id)
    return [step for step in pending if by_step.get(step.id, set()).issubset(complete)]


def _preview(value: str, limit: int = 240) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}…"


def _responsible(value: object) -> str:
    responsible = str(value or "agent")
    if responsible not in {"agent", "multiagents", "human", "script", "command"}:
        raise ToolError("responsible must be agent, multiagents, human, script, or command", code="invalid_input")
    return responsible


def _unique_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _advance_discussion(
    session: Session,
    discussion: Discussion,
    current: DiscussionParticipant,
) -> None:
    participants = session.exec(
        select(DiscussionParticipant)
        .where(DiscussionParticipant.discussion_id == discussion.id)
        .order_by(DiscussionParticipant.position)
    ).all()
    active = [item for item in participants if item.status == "active"]
    if active and all(item.last_end_discussion for item in active):
        discussion.status = "completed"
        discussion.current_agent_id = None
        discussion.finished_at = utcnow()
        discussion.updated_at = utcnow()
        session.add(discussion)
        return
    candidates = [item for item in active if not item.last_end_discussion]
    if not candidates:
        discussion.status = "completed"
        discussion.current_agent_id = None
        discussion.finished_at = utcnow()
        discussion.updated_at = utcnow()
        session.add(discussion)
        return
    next_items = [item for item in candidates if item.position > current.position]
    if next_items:
        next_participant = next_items[0]
    else:
        next_participant = candidates[0]
        discussion.current_round += 1
    discussion.current_agent_id = next_participant.agent_id
    discussion.updated_at = utcnow()
    session.add(discussion)


def _discussion_detail_payload(session: Session, discussion_id: str) -> dict[str, Any]:
    discussion = session.get(Discussion, discussion_id)
    if not discussion:
        raise ToolError("discussion_id not found", code="not_found")
    participants = session.exec(
        select(DiscussionParticipant)
        .where(DiscussionParticipant.discussion_id == discussion.id)
        .order_by(DiscussionParticipant.position)
    ).all()
    messages = session.exec(
        select(DiscussionMessage)
        .where(DiscussionMessage.discussion_id == discussion.id)
        .order_by(DiscussionMessage.position, DiscussionMessage.created_at)
    ).all()
    return {
        "success": True,
        "discussion": {
            "id": discussion.id,
            "chat_thread_id": discussion.chat_thread_id,
            "title": discussion.title,
            "objective_md": discussion.objective_md,
            "status": discussion.status,
            "current_agent_id": discussion.current_agent_id,
            "current_round": discussion.current_round,
            "consensus_md": discussion.consensus_md,
            "created_at": discussion.created_at.isoformat(),
            "updated_at": discussion.updated_at.isoformat(),
            "finished_at": discussion.finished_at.isoformat() if discussion.finished_at else None,
        },
        "participants": [
            {
                "id": item.id,
                "discussion_id": item.discussion_id,
                "agent_id": item.agent_id,
                "agent_thread_id": item.agent_thread_id,
                "position": item.position,
                "status": item.status,
                "last_end_discussion": item.last_end_discussion,
            }
            for item in participants
        ],
        "messages": [
            {
                "id": item.id,
                "discussion_id": item.discussion_id,
                "agent_id": item.agent_id,
                "agent_thread_id": item.agent_thread_id,
                "agent_run_id": item.agent_run_id,
                "content_md": item.content_md,
                "end_discussion": item.end_discussion,
                "round_index": item.round_index,
                "position": item.position,
                "metadata_json": item.metadata_json,
                "created_at": item.created_at.isoformat(),
            }
            for item in messages
        ],
        "next_agent_id": discussion.current_agent_id if discussion.status == "running" else None,
    }


def _require_chat_orchestrator(session: Session, thread_id: str, agent_id: str) -> None:
    if not session.get(ChatThread, thread_id):
        raise ToolError("chat_thread_id not found", code="not_found")
    if not agent_id:
        raise ToolError("agent_id is required for audit context", code="invalid_input")


def _require_manifest_orchestrator(session: Session, thread_id: str, agent_id: str) -> None:
    if not session.get(ChatThread, thread_id):
        raise ToolError("chat_thread_id not found", code="not_found")
    if agent_id not in {"manifest-orchestrator", "freeChatOrchestrator", "featureIntakeOrchestrator", "planChatOrchestrator"}:
        raise ToolError("Draft Mode and agent orchestration tools are restricted to the manifest orchestrator", code="forbidden")


def _cancel_active_draft_gates(session: Session, thread_id: str) -> None:
    active_drafts = session.exec(
        select(ChatDraft).where(ChatDraft.chat_thread_id == thread_id, ChatDraft.status == "active")
    ).all()
    pending_questions = session.exec(
        select(ChatDraftQuestion).where(
            ChatDraftQuestion.chat_thread_id == thread_id,
            ChatDraftQuestion.status == "pending",
        )
    ).all()
    now = utcnow()
    for item in active_drafts:
        item.status = "canceled"
        item.updated_at = now
        session.add(item)
    for item in pending_questions:
        item.status = "canceled"
        item.updated_at = now
        session.add(item)


def _require_no_blocking_draft_gate(session: Session, thread_id: str) -> None:
    active_draft = session.exec(
        select(ChatDraft).where(ChatDraft.chat_thread_id == thread_id, ChatDraft.status == "active")
    ).first()
    if active_draft:
        raise ToolError("active draft must be answered before continuing", code="draft_gate_active")
    pending_question = session.exec(
        select(ChatDraftQuestion).where(
            ChatDraftQuestion.chat_thread_id == thread_id,
            ChatDraftQuestion.status == "pending",
        )
    ).first()
    if pending_question:
        raise ToolError("pending questions must be answered before continuing", code="draft_gate_active")


def _require_accepted_draft(session: Session, thread_id: str) -> ChatDraft:
    pending_question = session.exec(
        select(ChatDraftQuestion).where(
            ChatDraftQuestion.chat_thread_id == thread_id,
            ChatDraftQuestion.status == "pending",
        )
    ).first()
    if pending_question:
        raise ToolError("pending questions must be answered before creating a plan", code="draft_gate_active")
    active_draft = session.exec(
        select(ChatDraft).where(ChatDraft.chat_thread_id == thread_id, ChatDraft.status == "active")
    ).first()
    if active_draft:
        raise ToolError("active draft must be accepted before creating a plan", code="draft_not_accepted")
    accepted_draft = session.exec(
        select(ChatDraft)
        .where(ChatDraft.chat_thread_id == thread_id, ChatDraft.status == "accepted")
        .order_by(ChatDraft.updated_at.desc())
    ).first()
    if not accepted_draft:
        raise ToolError("accepted draft required before creating a plan", code="draft_not_accepted")
    return accepted_draft


def _require_plan_orchestrator(session: Session, plan: Plan, agent_id: str) -> None:
    if not plan.id:
        raise ToolError("plan not found", code="not_found")
    if not agent_id:
        raise ToolError("agent_id is required for audit context", code="invalid_input")


def _runtime_for_agent(agent: Agent) -> dict[str, Any] | None:
    if agent.provider == "auto":
        return {"provider": "auto"}
    return {
        "provider": agent.provider,
        "model": agent.model,
        "effort": agent.reasoning_effort,
        "modelParams": agent.model_params_json,
    }


def _write_progress(
    session: Session,
    chat_thread_id: str,
    agent_id: str | None,
    agent_thread_id: str | None,
    desktop_run_id: str | None,
    event_type: str,
    content_md: str,
) -> None:
    session.add(
        ChatProgressEvent(
            chat_thread_id=chat_thread_id,
            agent_id=agent_id,
            agent_thread_id=agent_thread_id,
            desktop_run_id=desktop_run_id,
            event_type=event_type,
            content_md=content_md,
        )
    )


def _last_assistant_message(thread: dict[str, Any]) -> str:
    messages = thread.get("messages") if isinstance(thread, dict) else []
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""


def _draft_payload(item: ChatDraft) -> dict[str, Any]:
    return {
        "id": item.id,
        "chat_thread_id": item.chat_thread_id,
        "manifest_orchestrator_id": item.manifest_orchestrator_id,
        "orchestrator_agent_thread_id": item.orchestrator_agent_thread_id,
        "description_md": item.description_md,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _draft_question_payload(item: ChatDraftQuestion) -> dict[str, Any]:
    return {
        "id": item.id,
        "chat_thread_id": item.chat_thread_id,
        "chat_draft_id": item.chat_draft_id,
        "question": item.question,
        "options_json": item.options_json,
        "selected_option": item.selected_option,
        "answer_text": item.answer_text,
        "batch_id": item.batch_id,
        "status": item.status,
        "position": item.position,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _append_chat_message(
    session: Session,
    *,
    thread_id: str,
    source_type: str,
    source_id: str,
    role: str,
    content_md: str,
    metadata_json: dict[str, Any] | None = None,
) -> ChatMessage:
    position = len(
        session.exec(
            select(ChatThreadMessage).where(ChatThreadMessage.chat_thread_id == thread_id)
        ).all()
    )
    message = ChatMessage(
        source_type=source_type,
        source_id=source_id,
        role=role,
        content_md=content_md,
        metadata_json=metadata_json or {},
    )
    thread = session.get(ChatThread, thread_id)
    if thread:
        thread.updated_at = utcnow()
        session.add(thread)
    session.add(message)
    session.commit()
    session.refresh(message)
    session.add(ChatThreadMessage(chat_thread_id=thread_id, chat_message_id=message.id, position=position))
    session.commit()
    session.refresh(message)
    return message


if __name__ == "__main__":
    main(registry, server_name="vibe")

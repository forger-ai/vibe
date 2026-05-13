from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class GitRepository(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    remote_url: str = Field(min_length=1, max_length=1000)
    default_branch: str = Field(default="main", max_length=120)
    local_path: str | None = Field(default=None, max_length=1200)
    credential_mode: str = Field(default="local_git", max_length=80)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Agent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    identity_md: str = Field(default="", max_length=20000)
    tone_md: str = Field(default="", max_length=10000)
    feature_intake_task_md: str = Field(default="", max_length=20000)
    plan_task_md: str = Field(default="", max_length=20000)
    free_chat_task_md: str = Field(default="", max_length=20000)
    guardrails_md: str = Field(default="", max_length=20000)
    provider: str = Field(default="auto", max_length=80)
    model: str = Field(default="", max_length=160)
    reasoning_effort: str = Field(default="default", max_length=80)
    model_params_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChatThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    thread_type: str = Field(index=True, max_length=80)
    title: str = Field(default="New thread", max_length=200)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChatMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    source_type: str = Field(default="user", max_length=80)
    source_id: str | None = Field(default=None, max_length=160)
    role: str = Field(default="user", max_length=40)
    content_md: str = Field(default="", max_length=100000)
    visibility: str = Field(default="visible", max_length=80)
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class ChatThreadMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    chat_message_id: str = Field(foreign_key="chatmessage.id", index=True)
    position: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utcnow)


class ChatProgressEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    agent_id: str | None = Field(default=None, foreign_key="agent.id", index=True)
    agent_thread_id: str | None = Field(default=None, foreign_key="agentthread.id", index=True)
    desktop_run_id: str | None = Field(default=None, index=True, max_length=160)
    source_message_id: str | None = Field(default=None, max_length=160)
    event_type: str = Field(default="run.progress", index=True, max_length=80)
    content_md: str = Field(default="", max_length=100000)
    created_at: datetime = Field(default_factory=utcnow)


class ChatDraft(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    manifest_orchestrator_id: str = Field(default="", index=True, max_length=160)
    orchestrator_agent_thread_id: str | None = Field(default=None, foreign_key="agentthread.id", index=True)
    description_md: str = Field(default="", max_length=100000)
    status: str = Field(default="active", index=True, max_length=80)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChatDraftQuestion(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    chat_draft_id: str | None = Field(default=None, foreign_key="chatdraft.id", index=True)
    question: str = Field(default="", max_length=2000)
    options_json: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    selected_option: str | None = Field(default=None, max_length=500)
    answer_text: str = Field(default="", max_length=5000)
    batch_id: str = Field(default="", index=True, max_length=160)
    status: str = Field(default="pending", index=True, max_length=80)
    position: int = Field(default=0, ge=0, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PlanType(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    context_md: str = Field(default="", max_length=20000)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Plan(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_type_id: str | None = Field(default=None, foreign_key="plantype.id", index=True)
    name: str = Field(index=True, min_length=1, max_length=160)
    description: str = Field(default="", max_length=20000)
    status: str = Field(default="draft", index=True, max_length=80)
    execution_mode: str = Field(default="parallel", index=True, max_length=80)
    context_md: str = Field(default="", max_length=40000)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PlanRepository(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_id: str = Field(foreign_key="plan.id", index=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)
    start_ref: str = Field(default="", max_length=160)
    resolved_start_commit: str | None = Field(default=None, max_length=120)
    plan_branch: str | None = Field(default=None, max_length=160)
    checkout_path: str | None = Field(default=None, max_length=1200)
    status: str = Field(default="pending", index=True, max_length=80)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StepType(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    context_md: str = Field(default="", max_length=20000)
    main_task_md: str = Field(default="", max_length=40000)
    responsible: str = Field(default="agent", index=True, max_length=80)
    git_work: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Step(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_id: str = Field(foreign_key="plan.id", index=True)
    step_type_id: str | None = Field(default=None, foreign_key="steptype.id")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=20000)
    kind: str = Field(default="programming", index=True, max_length=80)
    position: int = Field(default=0, ge=0, index=True)
    status: str = Field(default="pending", index=True, max_length=80)
    result_md: str = Field(default="", max_length=100000)
    git_commit: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StepDependency(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    depends_on_step_id: str = Field(foreign_key="step.id", index=True)


class StepAssignment(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    instructions_md: str = Field(default="", max_length=40000)
    status: str = Field(default="pending", index=True, max_length=80)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StepRepository(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)


class StepExecution(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    status: str = Field(default="running", index=True, max_length=80)
    orchestrator_agent_thread_id: str | None = Field(default=None, foreign_key="agentthread.id", index=True)
    result_md: str = Field(default="", max_length=100000)
    started_at: datetime | None = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StepExecutionAgentThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_execution_id: str = Field(foreign_key="stepexecution.id", index=True)
    agent_thread_id: str = Field(foreign_key="agentthread.id", index=True)
    role: str = Field(default="worker", max_length=80)
    created_at: datetime = Field(default_factory=utcnow)


class Script(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True, min_length=1, max_length=120)
    slug: str = Field(index=True, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    language: str = Field(default="python", index=True, max_length=80)
    main_task_md: str = Field(default="", max_length=40000)
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScriptStep(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    script_id: str = Field(foreign_key="script.id", index=True)
    args_text: str = Field(default="", max_length=10000)
    created_at: datetime = Field(default_factory=utcnow)


class CommandStep(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    command_text: str = Field(default="", max_length=40000)
    shell: str = Field(default="/bin/sh", max_length=160)
    timeout_seconds: int = Field(default=600, ge=1)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScriptExecutionResult(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_execution_id: str = Field(foreign_key="stepexecution.id", index=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    script_id: str = Field(foreign_key="script.id", index=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)
    cwd: str = Field(default="", max_length=1200)
    status: str = Field(default="running", index=True, max_length=80)
    exit_code: int | None = Field(default=None)
    stdout: str = Field(default="", max_length=100000)
    stderr: str = Field(default="", max_length=100000)
    started_at: datetime | None = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CommandExecutionResult(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_execution_id: str = Field(foreign_key="stepexecution.id", index=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    command_step_id: str = Field(foreign_key="commandstep.id", index=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)
    cwd: str = Field(default="", max_length=1200)
    command_text: str = Field(default="", max_length=40000)
    status: str = Field(default="running", index=True, max_length=80)
    exit_code: int | None = Field(default=None)
    stdout: str = Field(default="", max_length=100000)
    stderr: str = Field(default="", max_length=100000)
    started_at: datetime | None = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StepCommit(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_execution_id: str = Field(foreign_key="stepexecution.id", index=True)
    step_id: str = Field(foreign_key="step.id", index=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)
    commit_sha: str = Field(max_length=120)
    commit_message: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=utcnow)


class AgentThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    desktop_thread_id: str = Field(index=True, max_length=160)
    agent_id: str | None = Field(default=None, foreign_key="agent.id", index=True)
    manifest_agent_id: str = Field(index=True, max_length=160)
    chat_thread_id: str | None = Field(default=None, foreign_key="chatthread.id", index=True)
    discussion_id: str | None = Field(default=None, foreign_key="discussion.id", index=True)
    owner_type: str = Field(default="agent", index=True, max_length=80)
    invocation_mode: str = Field(default="single_task", index=True, max_length=80)
    title: str = Field(default="Agent thread", max_length=200)
    status: str = Field(default="idle", index=True, max_length=80)
    initial_prompt_snapshot_md: str = Field(default="", max_length=120000)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChatAgentThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Discussion(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    title: str = Field(default="Discussion", max_length=200)
    objective_md: str = Field(default="", max_length=40000)
    status: str = Field(default="running", index=True, max_length=80)
    current_agent_id: str | None = Field(default=None, foreign_key="agent.id", index=True)
    current_round: int = Field(default=0, ge=0)
    consensus_md: str = Field(default="", max_length=100000)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class DiscussionParticipant(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    discussion_id: str = Field(foreign_key="discussion.id", index=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    agent_thread_id: str | None = Field(default=None, foreign_key="agentthread.id", index=True)
    position: int = Field(default=0, ge=0, index=True)
    status: str = Field(default="active", index=True, max_length=80)
    last_end_discussion: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DiscussionMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    discussion_id: str = Field(foreign_key="discussion.id", index=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    agent_thread_id: str | None = Field(default=None, foreign_key="agentthread.id", index=True)
    agent_run_id: str | None = Field(default=None, foreign_key="agentrun.id", index=True)
    content_md: str = Field(default="", max_length=100000)
    end_discussion: bool = Field(default=False, index=True)
    round_index: int = Field(default=0, ge=0, index=True)
    position: int = Field(default=0, ge=0, index=True)
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class PlanAgentThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_id: str = Field(foreign_key="plan.id", index=True)
    agent_thread_id: str = Field(foreign_key="agentthread.id", index=True)
    role: str = Field(default="participant", max_length=80)
    created_at: datetime = Field(default_factory=utcnow)


class PlanChatThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_id: str = Field(foreign_key="plan.id", index=True)
    chat_thread_id: str = Field(foreign_key="chatthread.id", index=True)
    role: str = Field(default="discussion", max_length=80)
    created_at: datetime = Field(default_factory=utcnow)


class StepAssignmentAgentThread(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_assignment_id: str = Field(foreign_key="stepassignment.id", index=True)
    agent_thread_id: str = Field(foreign_key="agentthread.id", index=True)
    role: str = Field(default="primary_worker", max_length=80)
    created_at: datetime = Field(default_factory=utcnow)


class AgentRun(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    agent_thread_id: str = Field(foreign_key="agentthread.id", index=True)
    desktop_run_id: str = Field(index=True, max_length=160)
    trigger_type: str = Field(default="user_message", index=True, max_length=80)
    trigger_id: str | None = Field(default=None, max_length=160)
    status: str = Field(default="queued", index=True, max_length=80)
    input_md: str = Field(default="", max_length=100000)
    context_snapshot_md: str = Field(default="", max_length=120000)
    result_md: str = Field(default="", max_length=100000)
    error: str | None = Field(default=None, max_length=10000)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class NotebookEntry(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = Field(index=True, min_length=1, max_length=160)
    short_description: str = Field(default="", max_length=500)
    long_description_md: str = Field(default="", max_length=100000)
    entry_type: str = Field(default="log", index=True, max_length=80)
    load_policy: str = Field(default="retrieval", index=True, max_length=80)
    read_when: str | None = Field(default=None, max_length=1000)
    created_by_agent_id: str | None = Field(default=None, foreign_key="agent.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RepositoryNotebookEntry(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)
    notebook_entry_id: str = Field(foreign_key="notebookentry.id", index=True)


class PlanTypeNotebookEntry(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_type_id: str = Field(foreign_key="plantype.id", index=True)
    notebook_entry_id: str = Field(foreign_key="notebookentry.id", index=True)


class PlanNotebookEntry(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    plan_id: str = Field(foreign_key="plan.id", index=True)
    notebook_entry_id: str = Field(foreign_key="notebookentry.id", index=True)


class StepTypeNotebookEntry(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_type_id: str = Field(foreign_key="steptype.id", index=True)
    notebook_entry_id: str = Field(foreign_key="notebookentry.id", index=True)


class AgentNotebookEntry(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    notebook_entry_id: str = Field(foreign_key="notebookentry.id", index=True)


class WorkspaceCheckout(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    repository_id: str = Field(foreign_key="gitrepository.id", index=True)
    owner_type: str = Field(index=True, max_length=80)
    owner_id: str = Field(index=True, max_length=160)
    path: str = Field(max_length=1200)
    branch: str = Field(default="main", max_length=120)
    base_ref: str | None = Field(default=None, max_length=160)
    status: str = Field(default="ready", index=True, max_length=80)
    last_synced_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

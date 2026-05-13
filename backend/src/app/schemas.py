from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RepositoryCreate(BaseModel):
    name: str
    description: str | None = None
    remote_url: str
    default_branch: str = "main"
    credential_mode: str = "local_git"


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    identity_md: str = ""
    tone_md: str = ""
    feature_intake_task_md: str = ""
    plan_task_md: str = ""
    free_chat_task_md: str = ""
    guardrails_md: str = ""
    provider: str = "auto"
    model: str = "auto"
    reasoning_effort: str = "default"
    model_params_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    identity_md: str | None = None
    tone_md: str | None = None
    feature_intake_task_md: str | None = None
    plan_task_md: str | None = None
    free_chat_task_md: str | None = None
    guardrails_md: str | None = None
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    model_params_json: dict[str, Any] | None = None
    enabled: bool | None = None


class PromptVariablesRequest(BaseModel):
    agent_id: str
    manifest_agent_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class PlanCreate(BaseModel):
    name: str
    description: str = ""
    plan_type_id: str | None = None
    execution_mode: str = "parallel"
    context_md: str = ""


class PlanRepositoryCreate(BaseModel):
    repository_id: str
    start_ref: str | None = None


class StepTypeCreate(BaseModel):
    name: str
    description: str | None = None
    context_md: str = ""
    main_task_md: str = ""
    responsible: str = "agent"
    git_work: bool = True


class StepTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    context_md: str | None = None
    main_task_md: str | None = None
    responsible: str | None = None
    git_work: bool | None = None


class ScriptCreate(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None
    language: str = "python"
    main_task_md: str = ""
    source_code: str = ""
    env_text: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ScriptUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    language: str | None = None
    main_task_md: str | None = None
    source_code: str | None = None
    env_text: str | None = None
    metadata_json: dict[str, Any] | None = None


class StepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    name: str
    description: str = ""
    step_type_id: str
    position: int | None = None
    depends_on_step_ids: list[str] = Field(default_factory=list)
    repository_ids: list[str] = Field(default_factory=list)
    script_id: str | None = None
    script_args_text: str = ""
    command_text: str = ""
    command_timeout_seconds: int = 600


class StepUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    step_type_id: str | None = None
    position: int | None = None
    depends_on_step_ids: list[str] | None = None
    repository_ids: list[str] | None = None
    script_id: str | None = None
    script_args_text: str | None = None
    command_text: str | None = None
    command_timeout_seconds: int | None = None


class StepAssignmentCreate(BaseModel):
    step_id: str
    agent_id: str
    instructions_md: str = ""


class StepExecutionStart(BaseModel):
    step_ids: list[str] = Field(default_factory=list)
    orchestrator_agent_thread_id: str | None = None
    worker_agent_thread_ids: list[str] = Field(default_factory=list)
    worker_agent_thread_ids_by_step_id: dict[str, list[str]] = Field(default_factory=dict)


class PlanAdvance(BaseModel):
    orchestrator_agent_thread_id: str | None = None
    worker_agent_thread_ids_by_step_id: dict[str, list[str]] = Field(default_factory=dict)


class StepExecutionComplete(BaseModel):
    result_md: str = ""
    status: str = "completed"
    commits: list[dict[str, str]] = Field(default_factory=list)


class HumanStepComplete(BaseModel):
    result_md: str = ""


class StepExecutionBlock(BaseModel):
    reason_md: str


class StepExecutionResume(BaseModel):
    resume_message_md: str


class PlanRepositorySelection(BaseModel):
    repositories: list[PlanRepositoryCreate] = Field(default_factory=list)


class ChatThreadCreate(BaseModel):
    thread_type: str
    title: str


class ChatMessageCreate(BaseModel):
    chat_thread_id: str
    source_type: str = "user"
    source_id: str | None = None
    role: str = "user"
    content_md: str
    visibility: str = "visible"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChatProgressEventCreate(BaseModel):
    chat_thread_id: str
    agent_id: str | None = None
    agent_thread_id: str | None = None
    desktop_run_id: str | None = None
    source_message_id: str | None = None
    event_type: str = "run.progress"
    content_md: str = ""


class ChatDraftCreate(BaseModel):
    chat_thread_id: str
    manifest_orchestrator_id: str = ""
    orchestrator_agent_thread_id: str | None = None
    description_md: str


class ChatDraftUpdate(BaseModel):
    status: str | None = None
    description_md: str | None = None


class ChatDraftQuestionCreate(BaseModel):
    chat_thread_id: str
    chat_draft_id: str | None = None
    question: str
    options_json: list[dict[str, Any]] = Field(default_factory=list)
    batch_id: str
    position: int = 0


class ChatDraftQuestionAnswer(BaseModel):
    selected_option: str | None = None
    answer_text: str = ""


class ChatDebugLogCreate(BaseModel):
    chat_thread_id: str | None = None
    event_type: str
    message: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChatAgentThreadCreate(BaseModel):
    agent_id: str
    enabled: bool = True


class ChatAgentThreadUpdate(BaseModel):
    enabled: bool | None = None


class NotebookEntryCreate(BaseModel):
    title: str
    short_description: str = ""
    long_description_md: str = ""
    entry_type: str = "log"
    load_policy: str = "retrieval"
    read_when: str | None = None
    created_by_agent_id: str | None = None
    scope_type: str | None = None
    scope_id: str | None = None


class AgentThreadCreate(BaseModel):
    desktop_thread_id: str
    agent_id: str | None = None
    manifest_agent_id: str
    title: str
    initial_prompt_snapshot_md: str = ""
    chat_thread_id: str | None = None
    discussion_id: str | None = None
    owner_type: str = "agent"
    invocation_mode: str = "single_task"
    plan_id: str | None = None
    step_assignment_id: str | None = None


class AgentRunCreate(BaseModel):
    agent_thread_id: str
    desktop_run_id: str
    trigger_type: str = "user_message"
    trigger_id: str | None = None
    input_md: str = ""
    context_snapshot_md: str = ""


class AgentRunUpdate(BaseModel):
    status: str | None = None
    result_md: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DiscussionCreate(BaseModel):
    chat_thread_id: str
    title: str = "Discussion"
    objective_md: str
    agent_ids: list[str] = Field(min_length=2)


class DiscussionMessageCreate(BaseModel):
    discussion_id: str
    agent_id: str
    agent_thread_id: str | None = None
    agent_run_id: str | None = None
    content_md: str
    end_discussion: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DiscussionConsensusUpdate(BaseModel):
    consensus_md: str


class PromptBuildRequest(BaseModel):
    agent_id: str
    manifest_agent_id: str
    context: dict[str, Any] = Field(default_factory=dict)
    manifest_prompt_template: str | None = None


class DashboardSummary(BaseModel):
    repositories: int
    agents: int
    active_plans: int
    active_runs: int

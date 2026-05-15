import { del, get, patch, post, put } from "./client";
import type {
  Agent,
  AgentRun,
  AgentThread,
  ChatAgentThread,
  ChatArtifactState,
  ChatMessage,
  ChatPlanDraft,
  ChatProgressEvent,
  ChatProposal,
  ChatQuestion,
  ChatThread,
  DashboardSummary,
  Discussion,
  DiscussionDetail,
  GitRepository,
  NotebookEntry,
  Plan,
  PlanDetail,
  PlanRepository,
  Script,
  Step,
  StepExecution,
  StepType,
} from "./types";

export const api = {
  dashboard: () => get<DashboardSummary>("/api/dashboard"),
  repositories: () => get<GitRepository[]>("/api/repositories"),
  createRepository: (body: {
    name: string;
    description?: string;
    remote_url: string;
    default_branch: string;
  }) => post<GitRepository>("/api/repositories", body),
  syncRepository: (id: string) => post<{ success: boolean }>(`/api/repositories/${id}/sync`, {}),

  stepTypes: () => get<StepType[]>("/api/step-types"),
  createStepType: (body: Partial<StepType> & { name: string; responsible: string }) => post<StepType>("/api/step-types", body),
  updateStepType: (id: string, body: Partial<StepType>) => patch<StepType>(`/api/step-types/${id}`, body),
  deleteStepType: (id: string) => del<void>(`/api/step-types/${id}`),

  scripts: () => get<Script[]>("/api/scripts"),
  createScript: (body: {
    name: string;
    slug?: string;
    description?: string;
    language: string;
    main_task_md?: string;
    source_code?: string;
    env_text?: string;
  }) => post<Script>("/api/scripts", body),
  updateScript: (id: string, body: Partial<Script>) => patch<Script>(`/api/scripts/${id}`, body),
  deleteScript: (id: string) => del<void>(`/api/scripts/${id}`),

  agents: () => get<Agent[]>("/api/agents"),
  createAgent: (body: Partial<Agent> & { name: string }) => post<Agent>("/api/agents", body),
  updateAgent: (id: string, body: Partial<Agent>) => patch<Agent>(`/api/agents/${id}`, body),
  interfaces: () => get<Array<{ id: string; title: string; template: string }>>("/api/agents/interfaces"),
  buildPrompt: (body: {
    agent_id: string;
    manifest_agent_id: string;
    context: Record<string, unknown>;
    manifest_prompt_template?: string;
  }) =>
    post<{ prompt: string }>("/api/agents/prompt", body),
  buildPromptVariables: (body: {
    agent_id: string;
    manifest_agent_id: string;
    context: Record<string, unknown>;
  }) =>
    post<Record<string, unknown>>("/api/agents/prompt-variables", body),

  plans: () => get<Plan[]>("/api/plans"),
  planDetail: (id: string) => get<PlanDetail>(`/api/plans/${id}/detail`),
  createPlan: (body: { name: string; description: string; context_md?: string; execution_mode?: string }) => post<Plan>("/api/plans", body),
  deletePlan: (id: string) => del<void>(`/api/plans/${id}`),
  setPlanRepositories: (planId: string, repositories: Array<{ repository_id: string; start_ref?: string }>) =>
    put<{ success: boolean; repositories: PlanRepository[] }>(`/api/plans/${planId}/repositories`, { repositories }),
  approvePlan: (planId: string) => post<{ success: boolean; plan: Plan; eligible_step_ids: string[] }>(`/api/plans/${planId}/approve`, {}),
  eligibleSteps: (planId: string) => get<{ step_ids: string[] }>(`/api/plans/${planId}/eligible-steps`),
  advancePlan: (planId: string, body: { orchestrator_agent_thread_id?: string; worker_agent_thread_ids_by_step_id?: Record<string, string[]> }) =>
    post<{ success: boolean; plan: Plan; executions: StepExecution[]; eligible_step_ids: string[]; stop_reason: string; human_step_ids: string[]; waiting_step_ids: string[] }>(`/api/plans/${planId}/advance`, body),
  startSteps: (planId: string, body: { step_ids?: string[]; orchestrator_agent_thread_id?: string; worker_agent_thread_ids?: string[]; worker_agent_thread_ids_by_step_id?: Record<string, string[]> }) =>
    post<{ success: boolean; executions: StepExecution[] }>(`/api/plans/${planId}/start-steps`, body),
  completeHumanStep: (planId: string, stepId: string, body: { result_md?: string }) =>
    post<{ success: boolean; execution: StepExecution; plan: Plan }>(`/api/plans/${planId}/steps/${stepId}/complete-human`, body),
  completeStepExecution: (executionId: string, body: { result_md?: string; status?: string; commits?: Array<{ repository_id: string; commit_sha: string; commit_message?: string }> }) =>
    post<{ success: boolean; execution: StepExecution; plan: Plan }>(`/api/plans/executions/${executionId}/complete`, body),
  blockStepExecution: (executionId: string, body: { reason_md: string }) =>
    post<{ success: boolean; execution: StepExecution; plan: Plan }>(`/api/plans/executions/${executionId}/block`, body),
  resumeStepExecution: (executionId: string, body: { resume_message_md: string }) =>
    post<{ success: boolean; execution: StepExecution; plan: Plan }>(`/api/plans/executions/${executionId}/resume`, body),
  planChats: (planId: string) => get<ChatThread[]>(`/api/plans/${planId}/chats`),
  createPlanChat: (planId: string) => post<ChatThread>(`/api/plans/${planId}/chats`, {}),
  createStep: (planId: string, body: { plan_id: string; name: string; description: string; step_type_id: string; position?: number; depends_on_step_ids?: string[]; repository_ids?: string[]; script_id?: string | null; script_args_text?: string; command_text?: string; command_timeout_seconds?: number }) =>
    post<Step>(`/api/plans/${planId}/steps`, body),
  updateStep: (planId: string, stepId: string, body: Partial<Step> & { depends_on_step_ids?: string[]; repository_ids?: string[]; script_id?: string | null; script_args_text?: string; command_text?: string; command_timeout_seconds?: number }) =>
    patch<Step>(`/api/plans/${planId}/steps/${stepId}`, body),
  deleteStep: (planId: string, stepId: string) => del<void>(`/api/plans/${planId}/steps/${stepId}`),
  createAssignment: (body: { step_id: string; agent_id: string; instructions_md: string }) =>
    post("/api/plans/assignments", body),

  chatThreads: () => get<ChatThread[]>("/api/chat/threads"),
  createChatThread: (body: { thread_type: string; title: string }) => post<ChatThread>("/api/chat/threads", body),
  chatMessages: (threadId: string) => get<ChatMessage[]>(`/api/chat/threads/${threadId}/messages`),
  chatProgress: (threadId: string) => get<ChatProgressEvent[]>(`/api/chat/threads/${threadId}/progress`),
  createChatProgress: (body: {
    chat_thread_id: string;
    agent_id?: string | null;
    agent_thread_id?: string | null;
    desktop_run_id?: string | null;
    source_message_id?: string | null;
    event_type: string;
    content_md: string;
  }) => post<ChatProgressEvent>("/api/chat/progress", body),
  activeChatArtifacts: (threadId: string) => get<ChatArtifactState>(`/api/chat/proposals/active/${threadId}`),
  updateChatProposal: (id: string, body: Partial<ChatProposal>) => patch<ChatProposal>(`/api/chat/proposals/${id}`, body),
  updateChatPlanDraft: (id: string, body: Partial<ChatPlanDraft>) => patch<ChatPlanDraft>(`/api/chat/proposals/plan-drafts/${id}`, body),
  acceptChatPlanDraft: (id: string) =>
    post<{ success: boolean; plan: Plan; chat_thread: ChatThread; step_ids: string[]; plan_draft: ChatPlanDraft }>(`/api/chat/proposals/plan-drafts/${id}/accept`, {}),
  answerChatQuestion: (id: string, body: { selected_option?: string | null; answer_text?: string }) =>
    patch<ChatQuestion>(`/api/chat/proposals/questions/${id}`, body),
  createChatDebugEvent: (body: {
    chat_thread_id?: string | null;
    event_type: string;
    message?: string;
    metadata_json?: Record<string, unknown>;
  }) => post<{ success: boolean; path: string }>("/api/chat/debug-log", body),
  chatAgents: (threadId: string) => get<ChatAgentThread[]>(`/api/chat/threads/${threadId}/agents`),
  upsertChatAgent: (threadId: string, agentId: string, body: { agent_id: string; enabled: boolean }) =>
    put<ChatAgentThread>(`/api/chat/threads/${threadId}/agents/${agentId}`, body),
  updateChatAgent: (id: string, body: Partial<ChatAgentThread>) =>
    patch<ChatAgentThread>(`/api/chat/agent-threads/${id}`, body),
  createChatMessage: (body: {
    chat_thread_id: string;
    role: string;
    source_type?: string;
    source_id?: string;
    content_md: string;
    metadata_json?: Record<string, unknown>;
  }) => post<ChatMessage>("/api/chat/messages", body),

  notebooks: () => get<NotebookEntry[]>("/api/notebooks"),
  createNotebook: (body: {
    title: string;
    short_description: string;
    long_description_md: string;
    entry_type?: string;
    load_policy?: string;
    scope_type?: string;
    scope_id?: string;
  }) => post<NotebookEntry>("/api/notebooks", body),

  agentThreads: () => get<AgentThread[]>("/api/agent-threads"),
  createAgentThread: (body: {
    desktop_thread_id: string;
    agent_id?: string | null;
    manifest_agent_id: string;
    title: string;
    initial_prompt_snapshot_md: string;
    chat_thread_id?: string;
    discussion_id?: string;
    owner_type?: string;
    invocation_mode?: string;
    plan_id?: string;
    step_assignment_id?: string;
  }) => post<AgentThread>("/api/agent-threads", body),
  createAgentRun: (body: {
    agent_thread_id: string;
    desktop_run_id: string;
    trigger_type?: string;
    trigger_id?: string;
    input_md: string;
    context_snapshot_md?: string;
  }) => post<AgentRun>("/api/agent-threads/runs", body),
  updateAgentRun: (id: string, body: Partial<AgentRun>) => patch<AgentRun>(`/api/agent-threads/runs/${id}`, body),

  discussions: (chatThreadId?: string) =>
    get<Discussion[]>(chatThreadId ? `/api/discussions?chat_thread_id=${encodeURIComponent(chatThreadId)}` : "/api/discussions"),
  createDiscussion: (body: { chat_thread_id: string; title?: string; objective_md: string; agent_ids: string[] }) =>
    post<DiscussionDetail>("/api/discussions", body),
  discussionDetail: (id: string) => get<DiscussionDetail>(`/api/discussions/${id}`),
  createDiscussionMessage: (id: string, body: { discussion_id: string; agent_id: string; agent_thread_id?: string | null; agent_run_id?: string | null; content_md: string; end_discussion?: boolean; metadata_json?: Record<string, unknown> }) =>
    post<DiscussionDetail>(`/api/discussions/${id}/messages`, body),
  updateDiscussionConsensus: (id: string, body: { consensus_md: string }) =>
    patch<DiscussionDetail>(`/api/discussions/${id}/consensus`, body),
};

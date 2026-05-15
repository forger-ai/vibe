export type Status = "draft" | "active" | "running" | "blocked" | "pending" | "completed" | "failed" | "canceled" | "idle";

export type GitRepository = {
  id: string;
  name: string;
  description?: string | null;
  remote_url: string;
  default_branch: string;
  local_path?: string | null;
  credential_mode: string;
  created_at: string;
  updated_at: string;
};

export type Agent = {
  id: string;
  name: string;
  description?: string | null;
  identity_md: string;
  tone_md: string;
  feature_intake_task_md: string;
  plan_task_md: string;
  free_chat_task_md: string;
  guardrails_md: string;
  provider: string;
  model: string;
  reasoning_effort: string;
  model_params_json: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type ChatAgentThread = {
  id: string;
  chat_thread_id: string;
  agent_id: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type Plan = {
  id: string;
  plan_type_id?: string | null;
  name: string;
  description: string;
  status: string;
  execution_mode: string;
  context_md: string;
  chat_thread_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type Step = {
  id: string;
  plan_id: string;
  step_type_id?: string | null;
  name: string;
  description: string;
  position: number;
  status: string;
  result_md: string;
  git_commit?: string | null;
  created_at: string;
  updated_at: string;
};

export type StepType = {
  id: string;
  name: string;
  description?: string | null;
  context_md: string;
  main_task_md: string;
  responsible: "agent" | "multiagents" | "human" | "script" | "command" | string;
  git_work: boolean;
  created_at: string;
  updated_at: string;
};

export type StepAssignment = {
  id: string;
  step_id: string;
  agent_id: string;
  instructions_md: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type StepDependency = {
  id: string;
  step_id: string;
  depends_on_step_id: string;
};

export type PlanRepository = {
  id: string;
  plan_id: string;
  repository_id: string;
  start_ref: string;
  resolved_start_commit?: string | null;
  plan_branch?: string | null;
  checkout_path?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type StepRepository = {
  id: string;
  step_id: string;
  repository_id: string;
};

export type Script = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  language: "python" | "javascript" | "typescript" | string;
  main_task_md: string;
  metadata_json: Record<string, unknown>;
  source_code: string;
  env_text: string;
  created_at: string;
  updated_at: string;
};

export type ScriptStep = {
  id: string;
  step_id: string;
  script_id: string;
  args_text: string;
  created_at: string;
};

export type CommandStep = {
  id: string;
  step_id: string;
  command_text: string;
  shell: string;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
};

export type ScriptExecutionResult = {
  id: string;
  step_execution_id: string;
  step_id: string;
  script_id: string;
  repository_id: string;
  cwd: string;
  status: string;
  exit_code?: number | null;
  stdout: string;
  stderr: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type CommandExecutionResult = {
  id: string;
  step_execution_id: string;
  step_id: string;
  command_step_id: string;
  repository_id: string;
  cwd: string;
  command_text: string;
  status: string;
  exit_code?: number | null;
  stdout: string;
  stderr: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type StepExecution = {
  id: string;
  step_id: string;
  status: string;
  orchestrator_agent_thread_id?: string | null;
  result_md: string;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type StepCommit = {
  id: string;
  step_execution_id: string;
  step_id: string;
  repository_id: string;
  commit_sha: string;
  commit_message: string;
  created_at: string;
};

export type StepExecutionAgentThread = {
  id: string;
  step_execution_id: string;
  agent_thread_id: string;
  role: string;
  created_at: string;
};

export type StepAssignmentAgentThread = {
  id: string;
  step_assignment_id: string;
  agent_thread_id: string;
  role: string;
  created_at: string;
};

export type PlanDetail = {
  plan: Plan;
  steps: Step[];
  step_types: StepType[];
  assignments: StepAssignment[];
  dependencies: StepDependency[];
  repositories: PlanRepository[];
  step_repositories: StepRepository[];
  executions: StepExecution[];
  commits: StepCommit[];
  script_steps: ScriptStep[];
  command_steps: CommandStep[];
  script_results: ScriptExecutionResult[];
  command_results: CommandExecutionResult[];
  step_execution_agent_threads: StepExecutionAgentThread[];
  step_assignment_agent_threads: StepAssignmentAgentThread[];
  agent_threads: AgentThread[];
  agent_runs: AgentRun[];
  eligible_step_ids: string[];
};

export type ChatThread = {
  id: string;
  thread_type: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  source_type: string;
  source_id?: string | null;
  role: string;
  content_md: string;
  visibility: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
};

export type ChatProgressEvent = {
  id: string;
  chat_thread_id: string;
  agent_id?: string | null;
  agent_thread_id?: string | null;
  desktop_run_id?: string | null;
  source_message_id?: string | null;
  event_type: string;
  content_md: string;
  created_at: string;
};

export type ChatProposal = {
  id: string;
  chat_thread_id: string;
  orchestrator_id: string;
  orchestrator_agent_thread_id?: string | null;
  description_md: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ChatPlanDraft = {
  id: string;
  chat_thread_id: string;
  orchestrator_id: string;
  name: string;
  description: string;
  context_md: string;
  repositories_json: Array<{ repository_id: string; start_ref?: string }>;
  steps_json: Array<Record<string, unknown>>;
  status: string;
  created_plan_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatQuestion = {
  id: string;
  chat_thread_id: string;
  question: string;
  options_json: Array<{ label: string; description?: string }>;
  selected_option?: string | null;
  answer_text: string;
  batch_id: string;
  status: string;
  position: number;
  created_at: string;
  updated_at: string;
};

export type ChatArtifactState = {
  proposal?: ChatProposal | null;
  plan_draft?: ChatPlanDraft | null;
  questions: ChatQuestion[];
};

export type NotebookEntry = {
  id: string;
  title: string;
  short_description: string;
  long_description_md: string;
  entry_type: string;
  load_policy: string;
  read_when?: string | null;
  created_by_agent_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentThread = {
  id: string;
  desktop_thread_id: string;
  agent_id?: string | null;
  manifest_agent_id: string;
  chat_thread_id?: string | null;
  discussion_id?: string | null;
  owner_type: "orchestrator" | "agent" | string;
  invocation_mode: "orchestrator" | "single_task" | "discussion" | "step_task" | string;
  title: string;
  status: string;
  initial_prompt_snapshot_md: string;
  created_at: string;
  updated_at: string;
};

export type Discussion = {
  id: string;
  chat_thread_id: string;
  title: string;
  objective_md: string;
  status: string;
  current_agent_id?: string | null;
  current_round: number;
  consensus_md: string;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
};

export type DiscussionParticipant = {
  id: string;
  discussion_id: string;
  agent_id: string;
  agent_thread_id?: string | null;
  position: number;
  status: string;
  last_end_discussion: boolean;
  created_at: string;
  updated_at: string;
};

export type DiscussionMessage = {
  id: string;
  discussion_id: string;
  agent_id: string;
  agent_thread_id?: string | null;
  agent_run_id?: string | null;
  content_md: string;
  end_discussion: boolean;
  round_index: number;
  position: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
};

export type DiscussionDetail = {
  discussion: Discussion;
  participants: DiscussionParticipant[];
  messages: DiscussionMessage[];
  next_agent_id?: string | null;
};

export type AgentRun = {
  id: string;
  agent_thread_id: string;
  desktop_run_id: string;
  trigger_type: string;
  trigger_id?: string | null;
  status: string;
  input_md: string;
  context_snapshot_md: string;
  result_md: string;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type DashboardSummary = {
  repositories: number;
  agents: number;
  active_plans: number;
  active_runs: number;
};

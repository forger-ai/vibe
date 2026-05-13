export type DesktopAgentThread = {
  desktop_thread_id: string;
  title: string;
  status: string;
  active_run?: DesktopAgentRun;
  messages?: Array<{ id: string; role: string; content: string; created_at: string }>;
  progressLog?: string[];
};

export type DesktopAgentRun = {
  desktop_run_id: string;
  desktop_thread_id: string;
  status: string;
};

export type AgentRuntimeApi = {
  start?: (input: {
    agentId: string;
    title?: string;
    variables?: Record<string, unknown>;
    runtime?: { provider?: string; model?: string; effort?: string; modelParams?: Record<string, unknown> };
    metadata?: Record<string, string | number | boolean | null>;
  }) => Promise<DesktopAgentThread>;
  resume?: (input: {
    threadId: string;
    variables?: Record<string, unknown>;
    runtime?: { provider?: string; model?: string; effort?: string; modelParams?: Record<string, unknown> };
  }) => Promise<DesktopAgentRun>;
  steer?: (input: {
    threadId: string;
    runId: string;
    variables?: Record<string, unknown>;
    runtime?: { provider?: string; model?: string; effort?: string; modelParams?: Record<string, unknown> };
  }) => Promise<{
    accepted: boolean;
    mode: "live" | "queued_for_next_run" | "requires_cancel_resume";
  }>;
  stop?: (input: { threadId: string; runId?: string }) => Promise<{ success: boolean }>;
  getThread?: (threadId: string) => Promise<DesktopAgentThread | null>;
  getRun?: (threadId: string, runId: string) => Promise<DesktopAgentRun | null>;
  onEvent?: (listener: (event: unknown) => void) => () => void;
  createAgentThread?: (input: {
    title: string;
    manifestAgentId: string;
    initialPrompt: string;
    runtime?: { provider?: string; model?: string; effort?: string; modelParams?: Record<string, unknown> };
    metadata?: Record<string, string | number | boolean | null>;
  }) => Promise<DesktopAgentThread>;
  startAgentThreadRun?: (input: {
    desktopThreadId: string;
    message: string;
    context?: string;
    runtime?: { provider?: string; model?: string; effort?: string; modelParams?: Record<string, unknown> };
  }) => Promise<DesktopAgentRun>;
  getAgentThread?: (desktopThreadId: string) => Promise<DesktopAgentThread | null>;
  cancelAgentThreadRun?: (input: { desktopThreadId: string; desktopRunId: string }) => Promise<{ success: boolean }>;
  steerAgentThreadRun?: (input: {
    desktopThreadId: string;
    desktopRunId: string;
    message: string;
    context?: string;
    runtime?: { provider?: string; model?: string; effort?: string; modelParams?: Record<string, unknown> };
  }) => Promise<{
    accepted: boolean;
    mode: "live" | "queued_for_next_run" | "requires_cancel_resume";
  }>;
  onAgentThreadEvent?: (listener: (event: unknown) => void) => () => void;
};

export function agentRuntime(): AgentRuntimeApi | null {
  const manifestAgents = window.forgerApp?.agents;
  if (manifestAgents) {
    return {
      ...manifestAgents,
      getAgentThread: manifestAgents.getAgentThread ?? manifestAgents.getThread,
      cancelAgentThreadRun: manifestAgents.cancelAgentThreadRun ?? ((input) =>
        manifestAgents.stop
          ? manifestAgents.stop({ threadId: input.desktopThreadId, runId: input.desktopRunId })
          : Promise.resolve({ success: false })),
      steerAgentThreadRun: manifestAgents.steerAgentThreadRun,
      onAgentThreadEvent: manifestAgents.onAgentThreadEvent ?? manifestAgents.onEvent,
    };
  }
  return window.forgerApp?.agentRuns ?? null;
}

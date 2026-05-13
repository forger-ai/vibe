/// <reference types="vite/client" />

interface Window {
  forgerApp?: {
    getContext?: () => Promise<{
      locale?: string;
      agents?: Array<{
        id: string;
        title: string;
        description?: string;
        initialPrompt: string;
        kind?: "classic" | "thread_interface" | "orchestrator" | "agent_invocation";
        initialPromptTemplate?: string;
        prompts?: Record<string, { body: string; variables?: Record<string, { type: string; required?: boolean }> }>;
      }>;
      agentDefaults?: {
        codex: { model: string; reasoningEffort: string };
        claude: { model: string; effort: string };
      };
      agentModelOptions?: {
        codex: Array<{ displayModelName: string; realModelName: string; defaultReasoningEffort: string }>;
        claude: Array<{ displayModelName: string; realModelName: string; defaultEffort: string }>;
      };
    }>;
    agents?: import("./lib/agentRuntime").AgentRuntimeApi;
    agentRuns?: import("./lib/agentRuntime").AgentRuntimeApi;
  };
}

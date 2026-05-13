export type AgentModelOption = {
  displayModelName: string;
  realModelName: string;
  defaultReasoningEffort?: string;
  defaultEffort?: string;
};

export type AgentModelContext = {
  agentDefaults?: {
    codex: { model: string; reasoningEffort: string };
    claude: { model: string; effort: string };
  };
  agentModelOptions: {
    codex: AgentModelOption[];
    claude: AgentModelOption[];
  };
};

export const fallbackAgentModelContext: AgentModelContext = {
  agentDefaults: {
    codex: { model: "gpt-5.4", reasoningEffort: "medium" },
    claude: { model: "sonnet", effort: "medium" },
  },
  agentModelOptions: {
    codex: [
      { displayModelName: "5.4", realModelName: "gpt-5.4", defaultReasoningEffort: "medium" },
      { displayModelName: "5.3 Codex", realModelName: "gpt-5.3-codex", defaultReasoningEffort: "low" },
      { displayModelName: "5.3 Spark", realModelName: "gpt-5.3-codex-spark", defaultReasoningEffort: "high" },
      { displayModelName: "5.4 Mini", realModelName: "gpt-5.4-mini", defaultReasoningEffort: "medium" },
      { displayModelName: "5.5", realModelName: "gpt-5.5", defaultReasoningEffort: "medium" },
    ],
    claude: [
      { displayModelName: "Sonnet latest", realModelName: "sonnet", defaultEffort: "medium" },
      { displayModelName: "Opus latest", realModelName: "opus", defaultEffort: "high" },
      { displayModelName: "Haiku latest", realModelName: "haiku", defaultEffort: "low" },
    ],
  },
};

export async function loadAgentModelContext(): Promise<AgentModelContext> {
  const context = await window.forgerApp?.getContext?.().catch(() => null);
  return {
    agentDefaults: context?.agentDefaults ?? fallbackAgentModelContext.agentDefaults,
    agentModelOptions: {
      codex: context?.agentModelOptions?.codex?.length
        ? context.agentModelOptions.codex
        : fallbackAgentModelContext.agentModelOptions.codex,
      claude: context?.agentModelOptions?.claude?.length
        ? context.agentModelOptions.claude
        : fallbackAgentModelContext.agentModelOptions.claude,
    },
  };
}

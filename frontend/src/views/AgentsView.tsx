import { useEffect, useMemo, useState } from "react";
import { Add, Save } from "@mui/icons-material";
import {
  Box,
  Button,
  Chip,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { api } from "../api/vibe";
import type { Agent } from "../api/types";
import { MarkdownField } from "../components/MarkdownField";
import { SectionHeader } from "../components/SectionHeader";
import { fallbackAgentModelContext, loadAgentModelContext, type AgentModelContext } from "../lib/agentModels";

type Draft = Pick<
  Agent,
  | "name"
  | "description"
  | "identity_md"
  | "tone_md"
  | "feature_intake_task_md"
  | "plan_task_md"
  | "free_chat_task_md"
  | "guardrails_md"
  | "provider"
  | "model"
  | "reasoning_effort"
  | "enabled"
>;

const blankDraft: Draft = {
  name: "",
  description: "",
  identity_md: "",
  tone_md: "",
  feature_intake_task_md: "",
  plan_task_md: "",
  free_chat_task_md: "",
  guardrails_md: "",
  provider: "auto",
  model: "auto",
  reasoning_effort: "default",
  enabled: true,
};

const effortOptions: Record<string, Array<{ value: string; label: string }>> = {
  auto: [
    { value: "default", label: "Desktop default" },
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
    { value: "xhigh", label: "Extra High" },
  ],
  codex: [
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
    { value: "xhigh", label: "Extra High" },
  ],
  claude: [
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
    { value: "xhigh", label: "Extra High" },
    { value: "max", label: "Max" },
  ],
};

export function AgentsView({
  agents,
  onChanged,
}: {
  agents: Agent[];
  onChanged: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | "new">(agents[0]?.id ?? "new");
  const selected = useMemo(() => agents.find((agent) => agent.id === selectedId), [agents, selectedId]);
  const [draft, setDraft] = useState<Draft>(blankDraft);
  const [modelContext, setModelContext] = useState<AgentModelContext>(fallbackAgentModelContext);
  const providerEfforts = effortOptions[draft.provider] ?? effortOptions.auto;
  const providerModels = draft.provider === "claude"
    ? modelContext.agentModelOptions.claude
    : draft.provider === "codex"
      ? modelContext.agentModelOptions.codex
      : [];

  useEffect(() => {
    void loadAgentModelContext().then(setModelContext);
  }, []);

  useEffect(() => {
    if (!selected) {
      setDraft(blankDraft);
      return;
    }
    setDraft({
      name: selected.name,
      description: selected.description ?? "",
      identity_md: selected.identity_md,
      tone_md: selected.tone_md,
      feature_intake_task_md: selected.feature_intake_task_md,
      plan_task_md: selected.plan_task_md,
      free_chat_task_md: selected.free_chat_task_md,
      guardrails_md: selected.guardrails_md,
      provider: selected.provider,
      model: selected.provider === "auto" ? "auto" : selected.model,
      reasoning_effort: selected.provider === "auto" ? "default" : selected.reasoning_effort ?? "medium",
      enabled: selected.enabled,
    });
  }, [selected]);

  function defaultsForProvider(provider: string) {
    if (provider === "claude") {
      return {
        model: modelContext.agentDefaults?.claude.model || modelContext.agentModelOptions.claude[0]?.realModelName || "sonnet",
        reasoning_effort: modelContext.agentDefaults?.claude.effort || "medium",
      };
    }
    if (provider === "codex") {
      return {
        model: modelContext.agentDefaults?.codex.model || modelContext.agentModelOptions.codex[0]?.realModelName || "gpt-5.4",
        reasoning_effort: modelContext.agentDefaults?.codex.reasoningEffort || "medium",
      };
    }
    return { model: "auto", reasoning_effort: "default" };
  }

  async function save() {
    const payload = {
      ...draft,
      description: draft.description || null,
    };
    if (selected) {
      await api.updateAgent(selected.id, payload);
    } else {
      await api.createAgent(payload);
    }
    await onChanged();
  }

  return (
    <Stack spacing={2}>
      <SectionHeader
        title="Agents"
        subtitle="Create local agents. Each one can be invoked through different manifest thread interfaces."
      />
      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="stretch">
        <Paper sx={{ p: 1, width: { xs: "100%", lg: 280 }, borderRadius: 1 }}>
          <Button fullWidth startIcon={<Add />} onClick={() => setSelectedId("new")}>
            New agent
          </Button>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {agents.map((agent) => (
              <Box
                key={agent.id}
                onClick={() => setSelectedId(agent.id)}
                sx={{
                  p: 1.25,
                  border: "1px solid",
                  borderColor: selectedId === agent.id ? "primary.main" : "divider",
                  borderRadius: 1,
                  cursor: "pointer",
                }}
              >
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography fontWeight={800} noWrap>
                    {agent.name}
                  </Typography>
                  <Chip size="small" label={agent.provider} />
                </Stack>
                <Typography variant="body2" color="text.secondary" noWrap>
                  {agent.description || "No description"}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Paper>
        <Paper sx={{ p: 2, flex: 1, borderRadius: 1 }}>
          <Stack spacing={1.5}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="h6" fontWeight={850}>
                {selected ? "Edit agent" : "New agent"}
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="body2" color="text.secondary">
                  Enabled
                </Typography>
                <Switch
                  checked={draft.enabled}
                  onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
                />
              </Stack>
            </Stack>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.25}>
              <TextField
                label="Name"
                value={draft.name}
                fullWidth
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              />
              <TextField
                select
                label="Provider"
                value={draft.provider}
                sx={{ minWidth: 180 }}
                onChange={(event) => {
                  const provider = event.target.value;
                  const defaults = defaultsForProvider(provider);
                  setDraft((current) => ({
                    ...current,
                    provider,
                    model: defaults.model,
                    reasoning_effort: defaults.reasoning_effort,
                  }));
                }}
              >
                {["auto", "codex", "claude"].map((provider) => (
                  <MenuItem key={provider} value={provider}>
                    {provider}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Model"
                value={draft.model}
                disabled={draft.provider === "auto"}
                sx={{ minWidth: 220 }}
                onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))}
              >
                {draft.provider === "auto" ? (
                  <MenuItem value="auto">auto</MenuItem>
                ) : (
                  providerModels.map((option) => (
                    <MenuItem key={option.realModelName} value={option.realModelName}>
                      {option.displayModelName}
                    </MenuItem>
                  ))
                )}
              </TextField>
              <TextField
                select
                label="Reasoning effort"
                value={draft.reasoning_effort}
                sx={{ minWidth: 200 }}
                onChange={(event) => setDraft((current) => ({ ...current, reasoning_effort: event.target.value }))}
              >
                {providerEfforts.map((effort) => (
                  <MenuItem key={effort.value} value={effort.value}>
                    {effort.label}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <TextField
              label="Description"
              value={draft.description ?? ""}
              fullWidth
              onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
            />
            <MarkdownField label="Identity" value={draft.identity_md} onChange={(identity_md) => setDraft((current) => ({ ...current, identity_md }))} />
            <MarkdownField label="Tone" value={draft.tone_md} minRows={3} onChange={(tone_md) => setDraft((current) => ({ ...current, tone_md }))} />
            <MarkdownField
              label="Feature intake task"
              value={draft.feature_intake_task_md}
              minRows={3}
              onChange={(feature_intake_task_md) => setDraft((current) => ({ ...current, feature_intake_task_md }))}
            />
            <MarkdownField
              label="Plan task"
              value={draft.plan_task_md}
              minRows={3}
              onChange={(plan_task_md) => setDraft((current) => ({ ...current, plan_task_md }))}
            />
            <MarkdownField
              label="Free chat task"
              value={draft.free_chat_task_md}
              minRows={3}
              onChange={(free_chat_task_md) => setDraft((current) => ({ ...current, free_chat_task_md }))}
            />
            <MarkdownField label="Guardrails" value={draft.guardrails_md} onChange={(guardrails_md) => setDraft((current) => ({ ...current, guardrails_md }))} />
            <Button variant="contained" startIcon={<Save />} disabled={!draft.name.trim()} onClick={() => void save()}>
              Save agent
            </Button>
          </Stack>
        </Paper>
      </Stack>
    </Stack>
  );
}

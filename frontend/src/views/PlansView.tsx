import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Add,
  AccountTree,
  ArrowBack,
  Chat,
  DeleteOutline,
  PauseCircle,
  PlayArrow,
  SmartToy,
  TaskAlt,
  Terminal,
} from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  CircularProgress,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import type { Agent, AgentThread, GitRepository, Plan, PlanDetail, Script, Step, StepType } from "../api/types";
import { API_BASE_URL } from "../api/client";
import { api } from "../api/vibe";
import { SectionHeader } from "../components/SectionHeader";
import { agentRuntime, type DesktopAgentThread } from "../lib/agentRuntime";
import { statusColor } from "../lib/status";
import { ChatWorkspace } from "./ChatWorkspace";

type PlanTab = "overview" | "steps";

export function PlansView({
  plans,
  agents,
  repositories,
  stepTypes,
  scripts,
  selectedPlan,
  onSelectPlan,
  onChanged,
}: {
  plans: Plan[];
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  scripts: Script[];
  selectedPlan?: Plan | null;
  onSelectPlan: (plan: Plan | null) => void;
  onChanged: () => void;
}) {
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [contextMd, setContextMd] = useState("");
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [tab, setTab] = useState<PlanTab>("overview");
  const [deletingPlanId, setDeletingPlanId] = useState<string | null>(null);

  const refreshSelectedPlan = useCallback(async () => {
    if (!selectedPlan) return;
    const nextDetail = await api.planDetail(selectedPlan.id);
    setDetail(nextDetail);
    await onChanged();
  }, [onChanged, selectedPlan]);

  useEffect(() => {
    if (!selectedPlan) {
      setDetail(null);
      return;
    }
    void api.planDetail(selectedPlan.id).then(setDetail);
  }, [selectedPlan]);

  async function createPlan() {
    const created = await api.createPlan({ name, description, context_md: contextMd });
    setName("");
    setDescription("");
    setContextMd("");
    setCreateOpen(false);
    await onChanged();
    onSelectPlan(created);
  }

  async function deletePlan(plan: Plan) {
    if (!window.confirm(`Delete "${plan.name}"? This removes its plan chats, steps, and assignments.`)) {
      return;
    }
    setDeletingPlanId(plan.id);
    try {
      await api.deletePlan(plan.id);
      await onChanged();
    } finally {
      setDeletingPlanId(null);
    }
  }

  if (selectedPlan) {
    return (
      <Box sx={{ height: "100%", minHeight: 0 }}>
        {detail ? (
          <PlanShow
            detail={detail}
            agents={agents}
            repositories={repositories}
            stepTypes={stepTypes}
            scripts={scripts}
            tab={tab}
            onTabChange={setTab}
            onBack={() => onSelectPlan(null)}
            onChanged={() => void refreshSelectedPlan()}
          />
        ) : (
          <Paper sx={{ p: 2, borderRadius: 1 }}>
            <Typography color="text.secondary">Loading plan...</Typography>
          </Paper>
        )}
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      <SectionHeader
        title="Plans"
        subtitle="Editable implementation plans with chats, steps, dependencies, and assignments."
        action={
          <Button variant="contained" startIcon={<Add />} onClick={() => setCreateOpen(true)}>
            Create plan
          </Button>
        }
      />
      <Paper sx={{ borderRadius: 1, overflow: "hidden" }}>
        {plans.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
            No plans yet.
          </Typography>
        ) : (
          <Stack divider={<Divider flexItem />}>
            {plans.map((plan) => (
              <Box
                key={plan.id}
                onClick={() => onSelectPlan(plan)}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 1,
                  px: 1.5,
                  py: 0.75,
                  cursor: "pointer",
                  "&:hover": { bgcolor: "action.hover" },
                }}
              >
                <Typography fontWeight={700} noWrap sx={{ minWidth: 0 }}>
                  {plan.name}
                </Typography>
                <Button
                  size="small"
                  color="error"
                  startIcon={<DeleteOutline />}
                  disabled={deletingPlanId === plan.id}
                  onClick={(event) => {
                    event.stopPropagation();
                    void deletePlan(plan);
                  }}
                  sx={{ flexShrink: 0 }}
                >
                  Delete
                </Button>
              </Box>
            ))}
          </Stack>
        )}
      </Paper>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create plan</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25} sx={{ pt: 1 }}>
            <TextField label="Plan name" value={name} onChange={(event) => setName(event.target.value)} />
            <TextField
              label="Description"
              value={description}
              multiline
              minRows={3}
              onChange={(event) => setDescription(event.target.value)}
            />
            <TextField
              label="Context"
              value={contextMd}
              multiline
              minRows={4}
              onChange={(event) => setContextMd(event.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!name.trim()} onClick={() => void createPlan()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function PlanShow({
  detail,
  agents,
  repositories,
  stepTypes,
  scripts,
  tab,
  onTabChange,
  onBack,
  onChanged,
}: {
  detail: PlanDetail;
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  scripts: Script[];
  tab: PlanTab;
  onTabChange: (tab: PlanTab) => void;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [advancing, setAdvancing] = useState(false);
  const [advanceError, setAdvanceError] = useState<string | null>(null);
  const [liveThreads, setLiveThreads] = useState<Record<string, DesktopAgentThread>>({});
  const [orchestratorThreads, setOrchestratorThreads] = useState<AgentThread[]>([]);
  const running = detail.steps.some((step) => step.status === "running") || detail.plan.status === "running";
  const blockedSteps = detail.steps.filter((step) => step.status === "blocked");
  const failedSteps = detail.steps.filter((step) => step.status === "failed");
  const eligibleStepIds = detail.eligible_step_ids ?? [];
  const eligibleSteps = detail.steps.filter((step) => eligibleStepIds.includes(step.id));
  const eligibleHumanSteps = eligibleSteps.filter((step) => stepTypeFor(step, stepTypes)?.responsible === "human");
  const humanReviewStep = eligibleHumanSteps[0] ?? null;
  const runnableEligibleSteps = eligibleSteps.filter((step) => stepTypeFor(step, stepTypes)?.responsible !== "human");
  const planState = planVisualState(detail, stepTypes);
  const completedCount = detail.steps.filter((step) => step.status === "completed").length;
  const progressText = `${completedCount}/${detail.steps.length} steps complete`;
  const overviewSteps = useMemo(() => currentPlanLevel(detail), [detail]);
  const autoAdvanceAttemptRef = useRef("");
  const orchestratorThinking = orchestratorThreads.some((thread) => {
    const live = liveThreads[thread.id] ?? liveThreads[thread.desktop_thread_id];
    return Boolean(live?.active_run && isActiveDesktopRun(live.active_run.status));
  });
  const canAdvance = !advancing && !running && !orchestratorThinking && !humanReviewStep && planState !== "completed" && planState !== "failed" && (detail.plan.status === "draft" || eligibleStepIds.length > 0 || blockedSteps.length > 0);
  const ctaLabel = detail.plan.status === "draft"
    ? "Approve and start"
    : humanReviewStep
      ? "Review in chat"
    : planState === "needs_you"
      ? "Continue after my input"
      : running
        ? "Running"
        : eligibleStepIds.length > 0
          ? "Run next steps"
          : "No ready steps";

  const refreshLiveThread = useCallback(async (storedThread: AgentThread) => {
    const live = await agentRuntime()?.getAgentThread?.(storedThread.desktop_thread_id).catch(() => null);
    if (!live) return;
    setLiveThreads((current) => ({ ...current, [storedThread.id]: live, [storedThread.desktop_thread_id]: live }));
  }, []);

  useEffect(() => {
    if (!running && detail.plan.status !== "failed" && detail.plan.status !== "awaiting_review") return undefined;
    const interval = window.setInterval(onChanged, 2000);
    return () => window.clearInterval(interval);
  }, [detail.plan.status, running, onChanged]);

  useEffect(() => {
    if (advancing || running || orchestratorThinking || humanReviewStep || runnableEligibleSteps.length === 0) return;
    if (!["approved", "awaiting_review"].includes(detail.plan.status)) return;
    if (blockedSteps.length > 0 || failedSteps.length > 0 || planState === "completed" || planState === "failed") return;
    const attemptKey = `${detail.plan.id}:${detail.plan.updated_at}:${runnableEligibleSteps.map((step) => step.id).join(",")}`;
    if (autoAdvanceAttemptRef.current === attemptKey) return;
    autoAdvanceAttemptRef.current = attemptKey;
    void advancePlan();
  }, [
    advancing,
    blockedSteps.length,
    detail.plan.id,
    detail.plan.status,
    detail.plan.updated_at,
    failedSteps.length,
    humanReviewStep,
    orchestratorThinking,
    planState,
    runnableEligibleSteps,
    running,
  ]);

  useEffect(() => {
    let canceled = false;
    async function loadPlanChatThreads() {
      const chats = await api.planChats(detail.plan.id).catch(() => []);
      const chatIds = new Set(chats.map((chat) => chat.id));
      const threads = await api.agentThreads().catch(() => []);
      if (canceled) return;
      const next = threads.filter((thread) => chatIds.has(thread.chat_thread_id ?? "") && thread.owner_type === "orchestrator");
      setOrchestratorThreads(next);
      next.forEach((thread) => void refreshLiveThread(thread));
    }
    void loadPlanChatThreads();
    const interval = window.setInterval(() => void loadPlanChatThreads(), 2500);
    return () => {
      canceled = true;
      window.clearInterval(interval);
    };
  }, [detail.plan.id, refreshLiveThread]);

  useEffect(() => {
    const runtime = agentRuntime();
    const unsubscribe = runtime?.onAgentThreadEvent?.((event: unknown) => {
      const payload = event as {
        desktop_thread_id?: string;
        thread?: DesktopAgentThread;
        run?: { desktop_thread_id?: string };
      };
      const desktopThreadId = payload.desktop_thread_id ?? payload.thread?.desktop_thread_id ?? payload.run?.desktop_thread_id;
      if (!desktopThreadId) return;
      const stored = [...detail.agent_threads, ...orchestratorThreads].find((thread) => thread.desktop_thread_id === desktopThreadId);
      if (stored) void refreshLiveThread(stored);
    });
    return unsubscribe;
  }, [detail.agent_threads, orchestratorThreads, refreshLiveThread]);

  useEffect(() => {
    detail.agent_threads.forEach((thread) => void refreshLiveThread(thread));
  }, [detail.agent_threads, refreshLiveThread]);

  useEffect(() => {
    const url = new URL(API_BASE_URL);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/api/realtime/ws";
    const socket = new WebSocket(url.toString());
    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ action: "subscribe", channel: `plans:${detail.plan.id}` }));
    });
    socket.addEventListener("message", () => onChanged());
    return () => socket.close();
  }, [detail.plan.id, onChanged]);

  async function advancePlan() {
    if (humanReviewStep) {
      return;
    }
    if (blockedSteps.length > 0) {
      onTabChange("overview");
      return;
    }
    if (orchestratorThinking) return;
    setAdvancing(true);
    setAdvanceError(null);
    try {
      await api.advancePlan(detail.plan.id, {});
      onChanged();
    } catch (error) {
      setAdvanceError(error instanceof Error ? error.message : "Unable to advance this plan.");
    } finally {
      setAdvancing(false);
    }
  }

  return (
    <Box sx={{ height: "100%", minHeight: 0, minWidth: 0, display: "grid", gridTemplateRows: "auto 1fr", overflow: "hidden" }}>
      <PlanTopBar
        detail={detail}
        tab={tab}
        planState={planState}
        progressText={progressText}
        ctaLabel={ctaLabel}
        advancing={advancing}
        canAdvance={canAdvance}
        orchestratorThinking={orchestratorThinking}
        onTabChange={onTabChange}
        onBack={onBack}
        onAdvance={() => void advancePlan()}
      />
      <Box sx={{ minHeight: 0, overflow: "hidden" }}>
        {tab === "overview" ? (
          <PlanOverview
            detail={detail}
            agents={agents}
            repositories={repositories}
            stepTypes={stepTypes}
            overviewSteps={overviewSteps}
            liveThreads={liveThreads}
            running={running}
            advanceError={advanceError}
            blockedSteps={blockedSteps}
            failedSteps={failedSteps}
            eligibleHumanSteps={eligibleHumanSteps}
            onChanged={onChanged}
          />
        ) : (
          <Box sx={{ height: "100%", minHeight: 0, overflowY: "auto", p: 2 }}>
            <PlanSteps detail={detail} agents={agents} repositories={repositories} stepTypes={stepTypes} scripts={scripts} onChanged={onChanged} />
          </Box>
        )}
      </Box>
    </Box>
  );
}

function PlanTopBar({
  detail,
  tab,
  planState,
  progressText,
  ctaLabel,
  advancing,
  canAdvance,
  orchestratorThinking,
  onTabChange,
  onBack,
  onAdvance,
}: {
  detail: PlanDetail;
  tab: PlanTab;
  planState: PlanVisualState;
  progressText: string;
  ctaLabel: string;
  advancing: boolean;
  canAdvance: boolean;
  orchestratorThinking: boolean;
  onTabChange: (tab: PlanTab) => void;
  onBack: () => void;
  onAdvance: () => void;
}) {
  return (
    <Box sx={{ px: 1.5, pt: 1, borderBottom: "1px solid", borderColor: "divider", bgcolor: "background.default" }}>
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ minWidth: 0, pb: 0.75 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={0.75} alignItems="center" sx={{ minWidth: 0 }}>
            <Typography fontWeight={850} noWrap sx={{ minWidth: 0 }}>
              {detail.plan.name}
            </Typography>
            <Chip size="small" label={planStateLabel(planState)} color={planStateColor(planState)} />
            <Chip size="small" variant="outlined" label={progressText} />
          </Stack>
        </Box>
        <Button
          startIcon={orchestratorThinking ? <CircularProgress size={16} /> : planState === "needs_you" ? <PauseCircle /> : <PlayArrow />}
          variant="contained"
          disabled={!canAdvance}
          onClick={onAdvance}
          sx={{ flexShrink: 0 }}
        >
          {orchestratorThinking ? "Plan chat thinking" : advancing ? "Advancing..." : ctaLabel}
        </Button>
      </Stack>
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ minWidth: 0 }}>
        <Button size="small" startIcon={<ArrowBack />} onClick={onBack} sx={{ flexShrink: 0 }}>
          Plans
        </Button>
        <Tabs value={tab} onChange={(_event, value) => onTabChange(value)} sx={{ minHeight: 36 }}>
          <Tab value="overview" icon={<Chat />} iconPosition="start" label="Overview" sx={{ minHeight: 36 }} />
          <Tab value="steps" icon={<AccountTree />} iconPosition="start" label="Steps" sx={{ minHeight: 36 }} />
        </Tabs>
        <Box sx={{ flex: 1 }} />
      </Stack>
    </Box>
  );
}

function PlanOverview({
  detail,
  agents,
  repositories,
  stepTypes,
  overviewSteps,
  liveThreads,
  running,
  advanceError,
  blockedSteps,
  failedSteps,
  eligibleHumanSteps,
  onChanged,
}: {
  detail: PlanDetail;
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  overviewSteps: Step[];
  liveThreads: Record<string, DesktopAgentThread>;
  running: boolean;
  advanceError: string | null;
  blockedSteps: Step[];
  failedSteps: Step[];
  eligibleHumanSteps: Step[];
  onChanged: () => void;
}) {
  const planComplete = detail.steps.length > 0 && detail.steps.every((step) => step.status === "completed");
  const showChatOnly = planComplete || eligibleHumanSteps.length > 0;
  return (
    <Box sx={{ height: "100%", minHeight: 0, overflow: "hidden", p: 2 }}>
      <Stack spacing={1.25} sx={{ height: "100%", minHeight: 0 }}>
        <Stack spacing={0.75}>
          {advanceError ? <Alert severity="error">{advanceError}</Alert> : null}
          {failedSteps.length > 0 ? (
            <Alert severity="error">
              A step failed. The error log and plan chat are open here so you can inspect and adjust the next move.
            </Alert>
          ) : null}
          {blockedSteps.length > 0 && !running ? (
            <Alert severity="warning">
              A step is blocked. Use the plan chat to agree on unblock guidance, then resume.
            </Alert>
          ) : null}
          {eligibleHumanSteps.length > 0 && !running ? (
            <Alert severity="info">
              The next ready step needs your input: {eligibleHumanSteps.map((step) => step.name).join(", ")}.
            </Alert>
          ) : null}
        </Stack>
        {showChatOnly ? (
          <Box sx={{ minHeight: 0, flex: 1 }}>
            <PlanChatPanel detail={detail} agents={agents} disabledInput={running} onChanged={onChanged} />
          </Box>
        ) : (
          <PlanStepLevel
            detail={detail}
            agents={agents}
            repositories={repositories}
            stepTypes={stepTypes}
            steps={overviewSteps}
            liveThreads={liveThreads}
          />
        )}
      </Stack>
    </Box>
  );
}

function PlanStepLevel({
  detail,
  agents,
  repositories,
  stepTypes,
  steps,
  liveThreads,
}: {
  detail: PlanDetail;
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  steps: Step[];
  liveThreads: Record<string, DesktopAgentThread>;
}) {
  if (steps.length === 0) {
    return (
      <Box sx={{ minHeight: 0, flex: 1 }}>
        <CurrentStepCard detail={detail} agents={agents} repositories={repositories} stepTypes={stepTypes} step={null} />
      </Box>
    );
  }
  const visibleColumns = Math.min(steps.length, 3);
  const cardWidth = steps.length === 1 ? "100%" : `calc((100% - ${(visibleColumns - 1) * 12}px) / ${visibleColumns})`;
  return (
    <Box sx={{ minHeight: 0, flex: 1, overflowX: "auto", overflowY: "hidden", pb: 0.5 }}>
      <Stack direction="row" spacing={1.5} sx={{ minWidth: "100%", height: "100%", minHeight: 0 }}>
        {steps.map((step) => (
          <Stack
            key={step.id}
            spacing={1.25}
            sx={{
              width: cardWidth,
              minWidth: steps.length === 1 ? 0 : 360,
              maxWidth: steps.length === 1 ? "100%" : "none",
              height: "100%",
              minHeight: 0,
              overflowY: "auto",
              pr: 0.5,
              flexShrink: 0,
            }}
          >
            <CurrentStepCard
              detail={detail}
              agents={agents}
              repositories={repositories}
              stepTypes={stepTypes}
              step={step}
            />
            {step.status === "running" || step.status === "failed" || step.status === "blocked" ? (
              <StepLiveLog detail={detail} agents={agents} step={step} liveThreads={liveThreads} />
            ) : null}
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

function PlanChatPanel({
  detail,
  agents,
  disabledInput,
  onChanged,
}: {
  detail: PlanDetail;
  agents: Agent[];
  disabledInput: boolean;
  onChanged: () => void;
}) {
  return (
    <ChatWorkspace
      title="Plan assistant"
      subtitle="Discuss, evaluate, and modify this plan with selected agents."
      manifestAgentId="planChatOrchestrator"
      agents={agents}
      defaultPromptContext={{
        context: "Plan-specific conversation inside Vibe.",
        plan_id: detail.plan.id,
        plan: {
          id: detail.plan.id,
          description: `${detail.plan.name}\n\n${detail.plan.description}\n\n${detail.plan.context_md}`,
          steps: describeSteps(detail),
          assignments: describeAssignments(detail, agents),
        },
      }}
      createThread={() => api.createPlanChat(detail.plan.id)}
      loadHistoryThreads={() => api.planChats(detail.plan.id)}
      historyDescription="Chats for this plan."
      disabledInput={disabledInput}
      onChanged={onChanged}
    />
  );
}

function CurrentStepCard({
  detail,
  agents,
  repositories,
  stepTypes,
  step,
}: {
  detail: PlanDetail;
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  step: Step | null;
}) {
  if (!step) {
    return (
      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Typography fontWeight={850}>No current step</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          This plan has no steps yet.
        </Typography>
      </Paper>
    );
  }
  const stepType = stepTypeFor(step, stepTypes);
  const assignments = detail.assignments.filter((assignment) => assignment.step_id === step.id);
  const dependencies = detail.dependencies
    .filter((dependency) => dependency.step_id === step.id)
    .map((dependency) => detail.steps.find((item) => item.id === dependency.depends_on_step_id)?.name ?? dependency.depends_on_step_id);
  const repositoryNames = detail.step_repositories
    .filter((link) => link.step_id === step.id)
    .map((link) => repositories.find((repository) => repository.id === link.repository_id)?.name ?? link.repository_id);
  const latestExecution = latestStepExecution(detail, step.id);
  const ready = detail.eligible_step_ids.includes(step.id) && step.status === "pending";
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack spacing={1.25}>
        <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="flex-start">
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="overline" color="text.secondary">
              Current step
            </Typography>
            <Typography variant="h6" fontWeight={850} sx={{ lineHeight: 1.2 }}>
              {step.name}
            </Typography>
          </Box>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" justifyContent="flex-end">
            {ready ? <Chip size="small" color="info" label="ready" /> : null}
            <Chip size="small" label={step.status} color={statusColor(step.status)} />
            <Chip size="small" variant="outlined" label={stepType?.name ?? "Missing type"} />
            {stepType ? <Chip size="small" variant="outlined" label={stepType.responsible} /> : null}
          </Stack>
        </Stack>
        <Typography color="text.secondary">{step.description || "No description."}</Typography>
        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
          <Chip size="small" label={`Repos: ${repositoryNames.join(", ") || "none"}`} />
          <Chip size="small" label={`Depends: ${dependencies.join(", ") || "none"}`} />
          {latestExecution ? <Chip size="small" label={`Execution: ${latestExecution.status}`} /> : null}
        </Stack>
        {assignments.length > 0 ? (
          <Stack spacing={0.75}>
            {assignments.map((assignment) => (
              <Box key={assignment.id} sx={{ p: 1, borderRadius: 1, bgcolor: "action.hover" }}>
                <Typography variant="body2" fontWeight={750}>
                  {agents.find((agent) => agent.id === assignment.agent_id)?.name ?? "Agent"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {assignment.instructions_md || "No task instructions."}
                </Typography>
              </Box>
            ))}
          </Stack>
        ) : null}
        {step.result_md ? (
          <Alert severity={step.status === "failed" ? "error" : step.status === "blocked" ? "warning" : "info"}>
            {step.result_md}
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  );
}

function StepLiveLog({
  detail,
  agents,
  step,
  liveThreads,
}: {
  detail: PlanDetail;
  agents: Agent[];
  step: Step;
  liveThreads: Record<string, DesktopAgentThread>;
}) {
  const stepType = detail.step_types.find((item) => item.id === step.step_type_id);
  if (stepType?.responsible === "script" || stepType?.responsible === "command") {
    const scriptResults = detail.script_results.filter((result) => result.step_id === step.id);
    const commandResults = detail.command_results.filter((result) => result.step_id === step.id);
    const results = [...scriptResults, ...commandResults];
    return (
      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 1 }}>
          <Terminal fontSize="small" />
          <Typography fontWeight={850}>Execution log</Typography>
        </Stack>
        {results.length === 0 ? (
          <Typography color="text.secondary">No log output yet.</Typography>
        ) : (
          <Stack spacing={1}>
            {results.map((result) => (
              <Box key={result.id}>
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.5 }}>
                  <Chip size="small" label={result.status} color={statusColor(result.status)} />
                  {"repository_id" in result ? <Typography variant="caption" color="text.secondary">{result.repository_id}</Typography> : null}
                </Stack>
                <LogBlock label="stdout" text={result.stdout} />
                <LogBlock label="stderr" text={result.stderr} error />
              </Box>
            ))}
          </Stack>
        )}
      </Paper>
    );
  }
  return <StepAgentThreadLog detail={detail} agents={agents} step={step} liveThreads={liveThreads} />;
}

function StepAgentThreadLog({
  detail,
  agents,
  step,
  liveThreads,
}: {
  detail: PlanDetail;
  agents: Agent[];
  step: Step;
  liveThreads: Record<string, DesktopAgentThread>;
}) {
  const executionIds = detail.executions.filter((execution) => execution.step_id === step.id).map((execution) => execution.id);
  const threadIds = new Set([
    ...detail.step_execution_agent_threads
      .filter((link) => executionIds.includes(link.step_execution_id))
      .map((link) => link.agent_thread_id),
    ...detail.step_assignment_agent_threads
      .filter((link) => detail.assignments.some((assignment) => assignment.step_id === step.id && assignment.id === link.step_assignment_id))
      .map((link) => link.agent_thread_id),
  ]);
  const threads = detail.agent_threads.filter((thread) => threadIds.has(thread.id));
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 1 }}>
        <SmartToy fontSize="small" />
        <Typography fontWeight={850}>Agent activity</Typography>
      </Stack>
      {threads.length === 0 ? (
        <Typography color="text.secondary">No agent threads are attached to this step yet.</Typography>
      ) : (
        <Stack spacing={1}>
          {threads.map((thread) => {
            const live = liveThreads[thread.id] ?? liveThreads[thread.desktop_thread_id];
            const latestMessage = live?.messages?.[live.messages.length - 1];
            const latestProgress = live?.progressLog?.[live.progressLog.length - 1];
            const run = detail.agent_runs.find((item) => item.agent_thread_id === thread.id);
            return (
              <Box key={thread.id} sx={{ p: 1, borderRadius: 1, bgcolor: "action.hover" }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography variant="body2" fontWeight={750}>
                    {agents.find((agent) => agent.id === thread.agent_id)?.name ?? thread.title}
                  </Typography>
                  <Chip size="small" label={live?.active_run?.status ?? run?.status ?? thread.status} />
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {latestProgress || latestMessage?.content || run?.result_md || "Waiting for the next update."}
                </Typography>
              </Box>
            );
          })}
        </Stack>
      )}
    </Paper>
  );
}

function LogBlock({ label, text, error = false }: { label: string; text: string; error?: boolean }) {
  if (!text) return null;
  return (
    <Box sx={{ mb: 0.75 }}>
      <Typography variant="caption" color={error ? "error" : "text.secondary"}>
        {label}
      </Typography>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1,
          borderRadius: 1,
          bgcolor: error ? "rgba(211, 47, 47, 0.08)" : "rgba(15, 23, 42, 0.06)",
          overflowX: "auto",
          whiteSpace: "pre-wrap",
          fontSize: 12,
          lineHeight: 1.45,
        }}
      >
        {text}
      </Box>
    </Box>
  );
}

function PlanFullSummary({ detail, stepTypes }: { detail: PlanDetail; stepTypes: StepType[] }) {
  const completed = detail.steps.filter((step) => step.status === "completed").length;
  const running = detail.steps.filter((step) => step.status === "running").length;
  const failed = detail.steps.filter((step) => step.status === "failed").length;
  const blocked = detail.steps.filter((step) => step.status === "blocked").length;
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack spacing={1}>
        <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="flex-start">
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h6" fontWeight={850}>
              {detail.plan.name}
            </Typography>
            <Typography color="text.secondary">
              {detail.plan.description || "No description."}
            </Typography>
          </Box>
          <Chip size="small" label={detail.plan.status} color={statusColor(detail.plan.status)} />
        </Stack>
        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
          <Chip size="small" label={`${completed}/${detail.steps.length} completed`} />
          <Chip size="small" label={`${running} running`} color={running ? "primary" : "default"} />
          <Chip size="small" label={`${blocked} blocked`} color={blocked ? "warning" : "default"} />
          <Chip size="small" label={`${failed} failed`} color={failed ? "error" : "default"} />
          <Chip size="small" label={`${detail.eligible_step_ids.length} ready`} color={detail.eligible_step_ids.length ? "info" : "default"} />
        </Stack>
        {detail.plan.context_md ? (
          <Typography variant="body2" color="text.secondary">
            {detail.plan.context_md}
          </Typography>
        ) : null}
        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
          {stepTypes.map((stepType) => {
            const count = detail.steps.filter((step) => step.step_type_id === stepType.id).length;
            return count > 0 ? <Chip key={stepType.id} size="small" variant="outlined" label={`${stepType.name}: ${count}`} /> : null;
          })}
        </Stack>
      </Stack>
    </Paper>
  );
}

function PlanSteps({
  detail,
  agents,
  repositories,
  stepTypes,
  scripts,
  onChanged,
}: {
  detail: PlanDetail;
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  scripts: Script[];
  onChanged: () => void;
}) {
  const [stepOpen, setStepOpen] = useState(false);
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [stepName, setStepName] = useState("");
  const [stepDescription, setStepDescription] = useState("");
  const [stepTypeId, setStepTypeId] = useState(stepTypes[0]?.id ?? "");
  const [repositoryIds, setRepositoryIds] = useState<string[]>([]);
  const [scriptId, setScriptId] = useState("");
  const [scriptArgsText, setScriptArgsText] = useState("");
  const [commandText, setCommandText] = useState("");
  const [commandTimeoutSeconds, setCommandTimeoutSeconds] = useState(600);
  const [dependsOnStepIds, setDependsOnStepIds] = useState<string[]>([]);
  const [assignmentStepId, setAssignmentStepId] = useState("");
  const [assignmentAgentId, setAssignmentAgentId] = useState(agents[0]?.id ?? "");
  const [instructions, setInstructions] = useState("");
  const stepLevels = useMemo(() => groupStepsByDependencyLevel(detail.steps, detail.dependencies), [detail]);
  const selectedStep = selectedStepId ? detail.steps.find((step) => step.id === selectedStepId) : null;
  const selectedNewStepType = stepTypes.find((stepType) => stepType.id === stepTypeId);

  async function addStep() {
    await api.createStep(detail.plan.id, {
      plan_id: detail.plan.id,
      name: stepName,
      description: stepDescription,
      step_type_id: stepTypeId,
      depends_on_step_ids: dependsOnStepIds,
      repository_ids: repositoryIds,
      script_id: selectedNewStepType?.responsible === "script" ? scriptId || undefined : undefined,
      script_args_text: selectedNewStepType?.responsible === "script" ? scriptArgsText : "",
      command_text: selectedNewStepType?.responsible === "command" ? commandText : "",
      command_timeout_seconds: commandTimeoutSeconds,
    });
    setStepName("");
    setStepDescription("");
    setStepTypeId(stepTypes[0]?.id ?? "");
    setRepositoryIds([]);
    setScriptId("");
    setScriptArgsText("");
    setCommandText("");
    setCommandTimeoutSeconds(600);
    setDependsOnStepIds([]);
    setStepOpen(false);
    onChanged();
  }

  async function addAssignment() {
    await api.createAssignment({
      step_id: assignmentStepId,
      agent_id: assignmentAgentId,
      instructions_md: instructions,
    });
    setInstructions("");
    setAssignmentOpen(false);
    onChanged();
  }

  if (selectedStep) {
    return (
      <StepShow
        detail={detail}
        step={selectedStep}
        agents={agents}
        repositories={repositories}
        stepTypes={stepTypes}
        scripts={scripts}
        onBack={() => setSelectedStepId(null)}
        onChanged={onChanged}
      />
    );
  }

  return (
    <Stack spacing={1.5}>
      <PlanFullSummary detail={detail} stepTypes={stepTypes} />
      <Stack direction="row" justifyContent="flex-end" spacing={1}>
        <Button startIcon={<Add />} onClick={() => setStepOpen(true)}>
          Add step
        </Button>
        <Button variant="outlined" onClick={() => setAssignmentOpen(true)}>
          Assign agent
        </Button>
      </Stack>
      {stepLevels.length === 0 ? (
        <Typography color="text.secondary">No steps yet.</Typography>
      ) : (
        stepLevels.map((level, index) => (
          <Stack key={`level-${index}`} spacing={1.25}>
            <Divider textAlign="left">
              <Chip
                size="small"
                icon={index === 0 ? <TaskAlt /> : undefined}
                label={stepLevelLabel(index, stepLevels.length)}
              />
            </Divider>
            {level.length > 1 ? (
              <Typography variant="caption" color="text.secondary">
                These steps are at the same dependency level and can run in parallel.
              </Typography>
            ) : null}
            {level.map((step) => {
              const assignments = detail.assignments.filter((item) => item.step_id === step.id);
              const stepType = stepTypes.find((item) => item.id === step.step_type_id);
              const eligible = detail.eligible_step_ids.includes(step.id);
              return (
                <Paper
                  key={step.id}
                  variant="outlined"
                  onClick={() => setSelectedStepId(step.id)}
                  sx={{
                    p: 1.5,
                    cursor: "pointer",
                    "&:hover": { borderColor: "primary.main", bgcolor: "action.hover" },
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" spacing={1}>
                    <Stack direction="row" spacing={0.75} alignItems="center">
                      <Typography fontWeight={850}>{step.name}</Typography>
                      <Chip size="small" label={stepType?.name ?? "Missing type"} />
                      {stepType && <Chip size="small" label={stepType.responsible} />}
                      {eligible && step.status === "pending" ? <Chip size="small" color="info" label="ready" /> : null}
                    </Stack>
                    <Stack direction="row" spacing={0.75} alignItems="center">
                      <Chip size="small" label={step.status} color={statusColor(step.status)} />
                      {step.status === "pending" && (
                        <Button
                          size="small"
                          color="error"
                          startIcon={<DeleteOutline />}
                          onClick={(event) => {
                            event.stopPropagation();
                            void api.deleteStep(detail.plan.id, step.id).then(onChanged);
                          }}
                        >
                          Delete
                        </Button>
                      )}
                    </Stack>
                  </Stack>
                  <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                    {step.description || "No description"}
                  </Typography>
                  <Stack spacing={0.75} sx={{ mt: 1 }}>
                    {assignments.length === 0 && (
                      <Typography variant="body2" color="text.secondary">No agents assigned.</Typography>
                    )}
                    {assignments.map((assignment) => (
                      <Paper key={assignment.id} variant="outlined" sx={{ p: 1, bgcolor: "background.default" }}>
                        <Stack direction="row" justifyContent="space-between" spacing={1}>
                          <Typography variant="body2" fontWeight={750}>
                            {agents.find((agent) => agent.id === assignment.agent_id)?.name ?? "Agent"}
                          </Typography>
                          <Chip size="small" label={assignment.status} />
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {assignment.instructions_md || "No task instructions."}
                        </Typography>
                      </Paper>
                    ))}
                  </Stack>
                </Paper>
              );
            })}
          </Stack>
        ))
      )}

      <Dialog open={stepOpen} onClose={() => setStepOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add step</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25} sx={{ pt: 1 }}>
            <TextField label="Step name" value={stepName} onChange={(event) => setStepName(event.target.value)} />
            <TextField
              select
              label="Step type"
              value={stepTypeId}
              onChange={(event) => setStepTypeId(event.target.value)}
            >
              {stepTypes.map((stepType) => (
                <MenuItem key={stepType.id} value={stepType.id}>{stepType.name} ({stepType.responsible})</MenuItem>
              ))}
            </TextField>
            <TextField
              label="Description"
              value={stepDescription}
              multiline
              minRows={3}
              onChange={(event) => setStepDescription(event.target.value)}
            />
            <TextField
              select
              SelectProps={{ multiple: true }}
              label="Repositories"
              value={repositoryIds}
              onChange={(event) => {
                const value = event.target.value;
                setRepositoryIds(typeof value === "string" ? value.split(",") : value);
              }}
            >
              {repositories.map((repository) => (
                <MenuItem key={repository.id} value={repository.id}>{repository.name}</MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Script"
              value={scriptId}
              disabled={selectedNewStepType?.responsible !== "script"}
              onChange={(event) => setScriptId(event.target.value)}
            >
              <MenuItem value="">No script</MenuItem>
              {scripts.map((script) => (
                <MenuItem key={script.id} value={script.id}>{script.name}</MenuItem>
              ))}
            </TextField>
            <TextField
              label="Script arguments"
              value={scriptArgsText}
              disabled={selectedNewStepType?.responsible !== "script"}
              onChange={(event) => setScriptArgsText(event.target.value)}
            />
            <TextField
              label="Command"
              value={commandText}
              disabled={selectedNewStepType?.responsible !== "command"}
              multiline
              minRows={5}
              onChange={(event) => setCommandText(event.target.value)}
            />
            <TextField
              label="Command timeout seconds"
              type="number"
              value={commandTimeoutSeconds}
              disabled={selectedNewStepType?.responsible !== "command"}
              onChange={(event) => setCommandTimeoutSeconds(Number(event.target.value) || 600)}
            />
            <TextField
              select
              SelectProps={{ multiple: true }}
              label="Depends on"
              value={dependsOnStepIds}
              onChange={(event) => {
                const value = event.target.value;
                setDependsOnStepIds(typeof value === "string" ? value.split(",") : value);
              }}
            >
              {detail.steps.map((step) => (
                <MenuItem key={step.id} value={step.id}>{step.name}</MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStepOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!stepName.trim()} onClick={() => void addStep()}>
            Add
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={assignmentOpen} onClose={() => setAssignmentOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Assign agent</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25} sx={{ pt: 1 }}>
            <TextField
              select
              label="Step"
              value={assignmentStepId}
              onChange={(event) => setAssignmentStepId(event.target.value)}
            >
              {detail.steps.map((step) => (
                <MenuItem key={step.id} value={step.id}>{step.name}</MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Agent"
              value={assignmentAgentId}
              onChange={(event) => setAssignmentAgentId(event.target.value)}
            >
              {agents.map((agent) => (
                <MenuItem key={agent.id} value={agent.id}>{agent.name}</MenuItem>
              ))}
            </TextField>
            <TextField
              label="Agent task for this step"
              value={instructions}
              multiline
              minRows={4}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAssignmentOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!assignmentStepId || !assignmentAgentId}
            onClick={() => void addAssignment()}
          >
            Assign
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function StepShow({
  detail,
  step,
  agents,
  repositories,
  stepTypes,
  scripts,
  onBack,
  onChanged,
}: {
  detail: PlanDetail;
  step: Step;
  agents: Agent[];
  repositories: GitRepository[];
  stepTypes: StepType[];
  scripts: Script[];
  onBack: () => void;
  onChanged: () => void;
}) {
  const [name, setName] = useState(step.name);
  const [description, setDescription] = useState(step.description);
  const [stepTypeId, setStepTypeId] = useState(step.step_type_id ?? "");
  const [repositoryIds, setRepositoryIds] = useState<string[]>(
    detail.step_repositories.filter((link) => link.step_id === step.id).map((link) => link.repository_id),
  );
  const [scriptId, setScriptId] = useState(detail.script_steps.find((link) => link.step_id === step.id)?.script_id ?? "");
  const [scriptArgsText, setScriptArgsText] = useState(detail.script_steps.find((link) => link.step_id === step.id)?.args_text ?? "");
  const [commandText, setCommandText] = useState(detail.command_steps.find((link) => link.step_id === step.id)?.command_text ?? "");
  const [commandTimeoutSeconds, setCommandTimeoutSeconds] = useState(detail.command_steps.find((link) => link.step_id === step.id)?.timeout_seconds ?? 600);
  const [dependsOnStepIds, setDependsOnStepIds] = useState<string[]>(
    detail.dependencies
      .filter((dependency) => dependency.step_id === step.id)
      .map((dependency) => dependency.depends_on_step_id),
  );
  const [assignmentAgentId, setAssignmentAgentId] = useState(agents[0]?.id ?? "");
  const [assignmentInstructions, setAssignmentInstructions] = useState("");
  const [saving, setSaving] = useState(false);
  const mutable = step.status === "pending" && detail.plan.status !== "running";
  const assignments = detail.assignments.filter((assignment) => assignment.step_id === step.id);
  const selectedStepType = stepTypes.find((stepType) => stepType.id === stepTypeId);

  useEffect(() => {
    setName(step.name);
    setDescription(step.description);
    setStepTypeId(step.step_type_id ?? "");
    setRepositoryIds(detail.step_repositories.filter((link) => link.step_id === step.id).map((link) => link.repository_id));
    setScriptId(detail.script_steps.find((link) => link.step_id === step.id)?.script_id ?? "");
    setScriptArgsText(detail.script_steps.find((link) => link.step_id === step.id)?.args_text ?? "");
    setCommandText(detail.command_steps.find((link) => link.step_id === step.id)?.command_text ?? "");
    setCommandTimeoutSeconds(detail.command_steps.find((link) => link.step_id === step.id)?.timeout_seconds ?? 600);
    setDependsOnStepIds(
      detail.dependencies
        .filter((dependency) => dependency.step_id === step.id)
        .map((dependency) => dependency.depends_on_step_id),
    );
  }, [detail.command_steps, detail.dependencies, detail.script_steps, detail.step_repositories, step]);

  async function saveStep() {
    setSaving(true);
    try {
      await api.updateStep(detail.plan.id, step.id, {
        name,
        description,
        step_type_id: stepTypeId || undefined,
        depends_on_step_ids: dependsOnStepIds,
        repository_ids: repositoryIds,
        script_id: selectedStepType?.responsible === "script" ? scriptId || null : null,
        script_args_text: selectedStepType?.responsible === "script" ? scriptArgsText : "",
        command_text: selectedStepType?.responsible === "command" ? commandText : "",
        command_timeout_seconds: commandTimeoutSeconds,
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  async function addAssignment() {
    await api.createAssignment({
      step_id: step.id,
      agent_id: assignmentAgentId,
      instructions_md: assignmentInstructions,
    });
    setAssignmentInstructions("");
    onChanged();
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="center">
        <Button size="small" startIcon={<ArrowBack />} onClick={onBack}>
          Steps
        </Button>
        <Chip size="small" label={step.status} color={statusColor(step.status)} />
      </Stack>

      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Stack spacing={1.25}>
          <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="center">
            <Typography variant="h6" fontWeight={850}>
              Step detail
            </Typography>
            <Chip size="small" label={selectedStepType?.name ?? "Missing type"} />
          </Stack>
          {!mutable && (
            <Typography variant="body2" color="text.secondary">
              This step is not editable because it is not pending.
            </Typography>
          )}
          <TextField
            label="Step name"
            value={name}
            disabled={!mutable}
            onChange={(event) => setName(event.target.value)}
          />
          <TextField
            select
            label="Step type"
            value={stepTypeId}
            disabled={!mutable}
            onChange={(event) => setStepTypeId(event.target.value)}
          >
            {stepTypes.map((stepType) => (
              <MenuItem key={stepType.id} value={stepType.id}>{stepType.name} ({stepType.responsible})</MenuItem>
            ))}
          </TextField>
          <TextField
            label="Description"
            value={description}
            disabled={!mutable}
            multiline
            minRows={5}
            onChange={(event) => setDescription(event.target.value)}
          />
          <TextField
            select
            SelectProps={{ multiple: true }}
            label="Repositories"
            value={repositoryIds}
            disabled={!mutable}
            onChange={(event) => {
              const value = event.target.value;
              setRepositoryIds(typeof value === "string" ? value.split(",") : value);
            }}
          >
            {repositories.map((repository) => (
              <MenuItem key={repository.id} value={repository.id}>{repository.name}</MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Script"
            value={scriptId}
            disabled={!mutable || selectedStepType?.responsible !== "script"}
            onChange={(event) => setScriptId(event.target.value)}
          >
            <MenuItem value="">No script</MenuItem>
            {scripts.map((script) => (
              <MenuItem key={script.id} value={script.id}>{script.name}</MenuItem>
            ))}
          </TextField>
          <TextField
            label="Script arguments"
            value={scriptArgsText}
            disabled={!mutable || selectedStepType?.responsible !== "script"}
            onChange={(event) => setScriptArgsText(event.target.value)}
          />
          <TextField
            label="Command"
            value={commandText}
            disabled={!mutable || selectedStepType?.responsible !== "command"}
            multiline
            minRows={5}
            onChange={(event) => setCommandText(event.target.value)}
          />
          <TextField
            label="Command timeout seconds"
            type="number"
            value={commandTimeoutSeconds}
            disabled={!mutable || selectedStepType?.responsible !== "command"}
            onChange={(event) => setCommandTimeoutSeconds(Number(event.target.value) || 600)}
          />
          <TextField
            select
            SelectProps={{ multiple: true }}
            label="Depends on"
            value={dependsOnStepIds}
            disabled={!mutable}
            onChange={(event) => {
              const value = event.target.value;
              setDependsOnStepIds(typeof value === "string" ? value.split(",") : value);
            }}
          >
            {detail.steps
              .filter((candidate) => candidate.id !== step.id)
              .map((candidate) => (
                <MenuItem key={candidate.id} value={candidate.id}>{candidate.name}</MenuItem>
              ))}
          </TextField>
          <Button
            variant="contained"
            disabled={!mutable || !name.trim() || saving}
            onClick={() => void saveStep()}
            sx={{ alignSelf: "flex-start" }}
          >
            Save step
          </Button>
        </Stack>
      </Paper>

      <StepLiveLog detail={detail} agents={agents} step={step} liveThreads={{}} />

      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Stack spacing={1.25}>
          <Typography variant="h6" fontWeight={850}>
            Assignments
          </Typography>
          {assignments.length === 0 ? (
            <Typography variant="body2" color="text.secondary">No agents assigned.</Typography>
          ) : (
            assignments.map((assignment) => (
              <Paper key={assignment.id} variant="outlined" sx={{ p: 1, bgcolor: "background.default" }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography variant="body2" fontWeight={750}>
                    {agents.find((agent) => agent.id === assignment.agent_id)?.name ?? "Agent"}
                  </Typography>
                  <Chip size="small" label={assignment.status} />
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {assignment.instructions_md || "No task instructions."}
                </Typography>
              </Paper>
            ))
          )}
          <Divider />
          <Typography fontWeight={750}>Assign agent</Typography>
          <TextField
            select
            label="Agent"
            value={assignmentAgentId}
            disabled={!mutable}
            onChange={(event) => setAssignmentAgentId(event.target.value)}
          >
            {agents.map((agent) => (
              <MenuItem key={agent.id} value={agent.id}>{agent.name}</MenuItem>
            ))}
          </TextField>
          <TextField
            label="Agent task for this step"
            value={assignmentInstructions}
            disabled={!mutable}
            multiline
            minRows={4}
            onChange={(event) => setAssignmentInstructions(event.target.value)}
          />
          <Button
            variant="outlined"
            disabled={!mutable || !assignmentAgentId || !assignmentInstructions.trim()}
            onClick={() => void addAssignment()}
            sx={{ alignSelf: "flex-start" }}
          >
            Add assignment
          </Button>
        </Stack>
      </Paper>
    </Stack>
  );
}

type PlanVisualState = "draft" | "ready" | "running" | "needs_you" | "completed" | "failed";

function currentPlanLevel(detail: PlanDetail) {
  const active = detail.steps.filter((step) => step.status === "running");
  if (active.length > 0) return active;
  const waiting = detail.steps.filter((step) => step.status === "failed" || step.status === "blocked");
  if (waiting.length > 0) return waiting;
  const eligible = detail.steps.filter((step) => detail.eligible_step_ids.includes(step.id));
  if (eligible.length > 0) return eligible;
  const levels = groupStepsByDependencyLevel(detail.steps.filter((step) => step.status === "pending"), detail.dependencies);
  return levels[0] ?? [];
}

function latestStepExecution(detail: PlanDetail, stepId: string) {
  const executions = detail.executions.filter((execution) => execution.step_id === stepId);
  return executions.length > 0 ? executions[executions.length - 1] : null;
}

function isActiveDesktopRun(status: string | undefined) {
  return Boolean(status && !["completed", "failed", "canceled"].includes(status));
}

function planVisualState(detail: PlanDetail, stepTypes: StepType[]): PlanVisualState {
  if (detail.plan.status === "draft") return "draft";
  if (detail.steps.some((step) => step.status === "running") || detail.plan.status === "running") return "running";
  if (detail.steps.some((step) => step.status === "failed") || detail.plan.status === "failed") return "failed";
  if (detail.steps.length > 0 && detail.steps.every((step) => step.status === "completed")) return "completed";
  const eligibleSteps = detail.steps.filter((step) => detail.eligible_step_ids.includes(step.id));
  if (detail.steps.some((step) => step.status === "blocked")) return "needs_you";
  if (eligibleSteps.some((step) => stepTypeFor(step, stepTypes)?.responsible === "human")) return "needs_you";
  return "ready";
}

function planStateLabel(state: PlanVisualState) {
  if (state === "needs_you") return "Needs you";
  return state[0].toUpperCase() + state.slice(1);
}

function planStateColor(state: PlanVisualState): "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning" {
  if (state === "draft") return "warning";
  if (state === "running") return "info";
  if (state === "needs_you") return "warning";
  if (state === "completed") return "success";
  if (state === "failed") return "error";
  return "primary";
}

function stepTypeFor(step: Step, stepTypes: StepType[]) {
  return stepTypes.find((item) => item.id === step.step_type_id);
}

function stepLevelLabel(index: number, total: number) {
  if (index === 0) return "First";
  if (index === total - 1) return "Finally";
  return "Then";
}

function groupStepsByDependencyLevel(steps: Step[], dependencies: PlanDetail["dependencies"]) {
  const remaining = new Set(steps.map((step) => step.id));
  const byId = new Map(steps.map((step) => [step.id, step]));
  const dependencyMap = new Map<string, Set<string>>();
  for (const step of steps) {
    dependencyMap.set(step.id, new Set());
  }
  for (const dependency of dependencies) {
    dependencyMap.get(dependency.step_id)?.add(dependency.depends_on_step_id);
  }
  const levels: Step[][] = [];
  const resolved = new Set<string>();
  while (remaining.size > 0) {
    const level = [...remaining]
      .filter((stepId) => [...(dependencyMap.get(stepId) ?? [])].every((dependencyId) => resolved.has(dependencyId)))
      .map((stepId) => byId.get(stepId))
      .filter((step): step is Step => Boolean(step));
    if (level.length === 0) {
      const fallback = [...remaining].map((stepId) => byId.get(stepId)).filter((step): step is Step => Boolean(step));
      levels.push(fallback);
      break;
    }
    levels.push(level);
    for (const step of level) {
      remaining.delete(step.id);
      resolved.add(step.id);
    }
  }
  return levels;
}

function describeSteps(detail: PlanDetail) {
  return detail.steps
    .map((step) => {
      const dependencyIds = detail.dependencies
        .filter((dependency) => dependency.step_id === step.id)
        .map((dependency) => dependency.depends_on_step_id);
      const repositoryIds = detail.step_repositories
        .filter((link) => link.step_id === step.id)
        .map((link) => link.repository_id);
      const stepType = detail.step_types.find((item) => item.id === step.step_type_id);
      const scriptStep = detail.script_steps.find((link) => link.step_id === step.id);
      const commandStep = detail.command_steps.find((link) => link.step_id === step.id);
      const executions = detail.executions.filter((execution) => execution.step_id === step.id);
      const latestExecution = executions[executions.length - 1];
      const commits = detail.commits
        .filter((commit) => commit.step_id === step.id)
        .map((commit) => `${commit.repository_id}:${commit.commit_sha}`);
      const result = step.result_md ? `\n  Current result/guidance: ${step.result_md}` : "";
      const executionText = latestExecution
        ? `\n  latest_execution_id=${latestExecution.id}; latest_execution_status=${latestExecution.status}`
        : "";
      const commitsText = commits.length > 0 ? `\n  commits=${commits.join(", ")}` : "";
      return [
        `- ${step.name}`,
        `  plan_id=${detail.plan.id}; step_id=${step.id}; step_type=${stepType?.name ?? "none"}; responsible=${stepType?.responsible ?? "unknown"}; status=${step.status}; position=${step.position}`,
        `  depends_on_step_ids=${dependencyIds.length > 0 ? dependencyIds.join(", ") : "none"}`,
        `  repository_ids=${repositoryIds.length > 0 ? repositoryIds.join(", ") : "none"}`,
        `  script_id=${scriptStep?.script_id ?? "none"}; script_args=${scriptStep?.args_text ?? ""}`,
        `  command=${commandStep ? commandStep.command_text : "none"}`,
        `  description=${step.description || "No description."}`,
        `${executionText}${commitsText}${result}`,
      ].filter(Boolean).join("\n");
    })
    .join("\n");
}

function describeAssignments(detail: PlanDetail, agents: Agent[]) {
  return detail.assignments
    .map((assignment) => {
      const step = detail.steps.find((item) => item.id === assignment.step_id);
      const agent = agents.find((item) => item.id === assignment.agent_id);
      return [
        `- assignment_id=${assignment.id}; plan_id=${detail.plan.id}; step_id=${assignment.step_id}; step_name=${step?.name ?? "step"}`,
        `  agent_id=${assignment.agent_id}; agent_name=${agent?.name ?? "Agent"}; status=${assignment.status}`,
        `  instructions=${assignment.instructions_md || "No instructions."}`,
      ].join("\n");
    })
    .join("\n");
}

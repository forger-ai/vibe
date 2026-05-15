import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Stack } from "@mui/material";
import { API_BASE_URL } from "./api/client";
import { api } from "./api/vibe";
import type { Agent, GitRepository, NotebookEntry, Plan, Script, StepType } from "./api/types";
import { AppShell, type ViewMode } from "./components/AppShell";
import { AgentsView } from "./views/AgentsView";
import { ChatWorkspace } from "./views/ChatWorkspace";
import { DatabasesView } from "./views/DatabasesView";
import { NotebookView } from "./views/NotebookView";
import { PlansView } from "./views/PlansView";
import { RepositoriesView } from "./views/RepositoriesView";
import { ScriptsView } from "./views/ScriptsView";
import { StepTypesView } from "./views/StepTypesView";

export default function App() {
  const [viewMode, setViewMode] = useState<ViewMode>("feature-intake");
  const [repositories, setRepositories] = useState<GitRepository[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookEntry[]>([]);
  const [stepTypes, setStepTypes] = useState<StepType[]>([]);
  const [scripts, setScripts] = useState<Script[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextRepos, nextAgents, nextPlans, nextNotebooks, nextStepTypes, nextScripts] = await Promise.all([
        api.repositories(),
        api.agents(),
        api.plans(),
        api.notebooks(),
        api.stepTypes(),
        api.scripts(),
      ]);
      setRepositories(nextRepos);
      setAgents(nextAgents);
      setPlans(nextPlans);
      setNotebooks(nextNotebooks);
      setStepTypes(nextStepTypes);
      setScripts(nextScripts);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Unable to load Vibe.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (plans.length === 0) return undefined;
    const url = new URL(API_BASE_URL);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/api/realtime/ws";
    const socket = new WebSocket(url.toString());
    socket.addEventListener("open", () => {
      for (const plan of plans) {
        socket.send(JSON.stringify({ action: "subscribe", channel: `plans:${plan.id}` }));
      }
    });
    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(String(event.data)) as { type?: string };
        if (payload.type === "subscription.confirmed") return;
      } catch {
        // Ignore malformed realtime events and refresh from the source of truth.
      }
      void load();
    });
    return () => socket.close();
  }, [load, plans.map((plan) => plan.id).join(",")]);

  const activePlans = useMemo(
    () =>
      plans.filter((plan) =>
        ["draft", "approved", "active", "running", "awaiting_review", "blocked"].includes(plan.status),
      ),
    [plans],
  );
  const isFullHeightView = viewMode === "feature-intake" || viewMode === "free-chat" || (viewMode === "plans" && Boolean(selectedPlan));

  function selectPlan(plan: Plan) {
    setSelectedPlan(plan);
    setViewMode("plans");
  }

  function handlePlanCreated(plan: Plan) {
    setPlans((current) => current.some((item) => item.id === plan.id) ? current : [plan, ...current]);
    setSelectedPlan(plan);
    setViewMode("plans");
    void load();
  }

  function changeView(nextView: ViewMode) {
    if (nextView === "plans") {
      setSelectedPlan(null);
    }
    setViewMode(nextView);
  }

  return (
    <AppShell
      viewMode={viewMode}
      activePlans={activePlans}
      onViewChange={changeView}
      onPlanSelect={selectPlan}
    >
      <Stack
        spacing={2}
        sx={{
          height: "calc(100vh - 96px)",
          minHeight: 0,
          overflow: isFullHeightView ? "hidden" : "auto",
        }}
      >
        {loadError && <Alert severity="error">{loadError}</Alert>}
        {viewMode === "feature-intake" && (
          <ChatWorkspace
            title="Feature Intake"
            subtitle="Shape a rough idea with the manifest orchestrator, then turn it into an editable plan."
            manifestAgentId="featureIntakeOrchestrator"
            agents={agents}
            onChanged={() => void load()}
            onPlanCreated={handlePlanCreated}
          />
        )}
        {viewMode === "free-chat" && (
          <ChatWorkspace
            title="Free Chat"
            subtitle="Chat with the manifest orchestrator and let it invoke selected Agents."
            manifestAgentId="freeChatOrchestrator"
            agents={agents}
            onChanged={() => void load()}
          />
        )}
        {viewMode === "repositories" && (
          <RepositoriesView repositories={repositories} onChanged={() => void load()} />
        )}
        {viewMode === "databases" && <DatabasesView />}
        {viewMode === "agents" && <AgentsView agents={agents} onChanged={() => void load()} />}
        {viewMode === "plans" && (
          <PlansView
            plans={plans}
            agents={agents}
            repositories={repositories}
            stepTypes={stepTypes}
            scripts={scripts}
            selectedPlan={selectedPlan}
            onSelectPlan={setSelectedPlan}
            onChanged={() => void load()}
          />
        )}
        {viewMode === "step-types" && <StepTypesView stepTypes={stepTypes} onChanged={() => void load()} />}
        {viewMode === "scripts" && <ScriptsView scripts={scripts} onChanged={() => void load()} />}
        {viewMode === "settings" && <NotebookView entries={notebooks} onChanged={() => void load()} />}
      </Stack>
    </AppShell>
  );
}

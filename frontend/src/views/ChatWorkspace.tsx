import { useEffect, useMemo, useRef, useState } from "react";
import { AddComment, ArrowBackIosNew, ArrowForwardIos, Cancel, CheckCircle, Close, ExpandMore, Groups, History, Psychology, Send, StopCircle } from "@mui/icons-material";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  Agent,
  AgentThread,
  ChatDraft,
  ChatDraftQuestion,
  ChatMessage,
  ChatProgressEvent,
  ChatThread,
  Discussion,
  DiscussionDetail,
} from "../api/types";
import { api } from "../api/vibe";
import { SectionHeader } from "../components/SectionHeader";
import { agentRuntime, type DesktopAgentThread } from "../lib/agentRuntime";

type SidePanelMode = "agents" | "history";
type ChatHistoryItem = { thread: ChatThread; preview: string };
type ManifestPromptKind = "initial" | "resume";
type ThreadVisualState = "running" | "ready" | "error";

const MANIFEST_PROMPT_VARIABLES: Record<string, Partial<Record<ManifestPromptKind, string[]>>> = {
  freeChatOrchestrator: {
    initial: ["runtimeContract", "agentsInChat", "repositoryContext", "interfaceNotebook", "userMessage"],
    resume: ["runtimeContract", "turnPayload", "userMessage"],
  },
  featureIntakeOrchestrator: {
    initial: ["runtimeContract", "agentsInChat", "repositoryContext", "interfaceNotebook", "userMessage"],
    resume: ["runtimeContract", "turnPayload", "userMessage"],
  },
  planChatOrchestrator: {
    initial: ["runtimeContract", "agentsInChat", "planDescription", "planSteps", "repositoryContext", "userMessage"],
    resume: ["runtimeContract", "turnPayload", "userMessage"],
  },
  agentChatDiscussion: {
    initial: [
      "agentIdentity",
      "agentId",
      "discussionId",
      "discussionObjective",
      "discussionMessages",
      "repositoryContext",
      "agentTone",
      "globalGuardrails",
      "agentGuardrails",
    ],
    resume: ["runtimeContract", "turnPayload"],
  },
};

type ThoughtTimelineItem =
  | { kind: "message"; id: string; role: string; content: string; created_at: string }
  | { kind: "progress"; id: string; event_type: string; content_md: string; desktop_run_id?: string | null; created_at: string };

export function ChatWorkspace({
  title,
  subtitle,
  manifestAgentId,
  agents,
  defaultPromptContext,
  createThread,
  loadHistoryThreads,
  historyDescription,
  disabledInput,
  onChanged,
}: {
  title: string;
  subtitle: string;
  manifestAgentId: string;
  agents: Agent[];
  defaultPromptContext?: Record<string, unknown>;
  createThread?: () => Promise<ChatThread>;
  loadHistoryThreads?: () => Promise<ChatThread[]>;
  historyDescription?: string;
  disabledInput?: boolean;
  onChanged: () => void;
}) {
  const enabledAgents = useMemo(() => agents.filter((agent) => agent.enabled), [agents]);
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [orchestratorThread, setOrchestratorThread] = useState<AgentThread | null>(null);
  const [agentThreads, setAgentThreads] = useState<AgentThread[]>([]);
  const [liveThreads, setLiveThreads] = useState<Record<string, DesktopAgentThread>>({});
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [progressEvents, setProgressEvents] = useState<ChatProgressEvent[]>([]);
  const [activeDraft, setActiveDraft] = useState<ChatDraft | null>(null);
  const [draftQuestions, setDraftQuestions] = useState<ChatDraftQuestion[]>([]);
  const [draftQuestionIndex, setDraftQuestionIndex] = useState(0);
  const [draftMode, setDraftMode] = useState(true);
  const [discussions, setDiscussions] = useState<Discussion[]>([]);
  const [discussionDetail, setDiscussionDetail] = useState<DiscussionDetail | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelMode, setPanelMode] = useState<SidePanelMode>("agents");
  const [chatHistory, setChatHistory] = useState<ChatHistoryItem[]>([]);
  const [thoughtThreadId, setThoughtThreadId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const initializedHistoryScope = useRef("");
  const processedDesktopMessages = useRef(new Set<string>());
  const persistedProgressEvents = useRef(new Set<string>());
  const activeDiscussionStarts = useRef(new Set<string>());
  const resumedQuestionBatches = useRef(new Set<string>());

  const started = Boolean(threadId);
  const historyScopeKey = `${manifestAgentId}:${String((defaultPromptContext?.plan as { id?: unknown } | undefined)?.id ?? "")}`;

  useEffect(() => {
    const runtime = agentRuntime();
    if (!runtime?.onAgentThreadEvent) return undefined;
    return runtime.onAgentThreadEvent((rawEvent) => {
      const event = rawEvent as {
        type?: string;
        desktop_thread_id?: string;
        thread?: DesktopAgentThread;
        run?: { desktop_thread_id?: string; desktop_run_id?: string; status?: string; progressLog?: string[] };
        progress?: string;
      };
      const desktopThreadId = event.desktop_thread_id ?? event.thread?.desktop_thread_id ?? event.run?.desktop_thread_id;
      if (!desktopThreadId) return;
      void refreshLiveThread(desktopThreadId);
      void persistProgressFromRuntimeEvent(event);
    });
  }, [threadId, agentThreads]);

  useEffect(() => {
    if (!threadId) return undefined;
    let canceled = false;
    async function poll() {
      if (!threadId || canceled) return;
      const [nextMessages, nextProgress, nextThreads, nextDiscussions, nextDraftState] = await Promise.all([
        api.chatMessages(threadId),
        api.chatProgress(threadId),
        api.agentThreads(),
        api.discussions(threadId),
        api.activeDraft(threadId).catch(() => ({ draft: null, questions: [] })),
      ]);
      const relevantThreads = nextThreads.filter((item) => item.chat_thread_id === threadId);
      setMessages(nextMessages.filter((item) => item.visibility === "visible"));
      setProgressEvents(nextProgress);
      setActiveDraft(nextDraftState.draft ?? null);
      setDraftQuestions(nextDraftState.questions ?? []);
      setAgentThreads(relevantThreads);
      setDiscussions(nextDiscussions);
      const nextOrchestrator = relevantThreads.find((item) => item.owner_type === "orchestrator") ?? orchestratorThread;
      if (nextOrchestrator) setOrchestratorThread(nextOrchestrator);
      await ingestOrchestratorMessages(nextOrchestrator);
      await advanceDiscussionRuns(nextDiscussions, relevantThreads);
    }
    void poll();
    const interval = window.setInterval(() => void poll(), 2500);
    return () => {
      canceled = true;
      window.clearInterval(interval);
    };
  }, [threadId, orchestratorThread?.id, selectedAgentIds.join(","), agents]);

  useEffect(() => {
    if (!panelOpen || panelMode !== "history") return;
    void loadChatHistory();
  }, [panelOpen, panelMode, manifestAgentId, threadId]);

  useEffect(() => {
    if (initializedHistoryScope.current === historyScopeKey) return;
    initializedHistoryScope.current = historyScopeKey;
    let canceled = false;
    async function initializeChatWorkspace() {
      const items = await loadChatHistory();
      if (canceled) return;
      const latestChat = items[0];
      if (latestChat) {
        setPanelMode("history");
        setPanelOpen(true);
        await loadHistoricalChat(latestChat);
        return;
      }
      setPanelMode("agents");
      setPanelOpen(true);
    }
    void initializeChatWorkspace();
    return () => {
      canceled = true;
    };
  }, [historyScopeKey]);

  const pendingDraftQuestions = draftQuestions.filter((question) => question.status === "pending");
  const currentDraftQuestion = pendingDraftQuestions[Math.min(draftQuestionIndex, Math.max(0, pendingDraftQuestions.length - 1))];
  const activeGatePending = Boolean(currentDraftQuestion || activeDraft?.status === "active");
  const singleAgentThreads = agentThreads.filter((item) => item.owner_type === "agent" && item.invocation_mode === "single_task");

  useEffect(() => {
    if (!stickToBottomRef.current || !scrollRef.current) return;
    scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, pendingDraftQuestions.length, activeDraft?.id, activeDraft?.description_md]);

  const thoughtThread = thoughtThreadId ? liveThreads[thoughtThreadId] : undefined;
  const thoughtStoredThread = thoughtThreadId ? agentThreads.find((item) => item.id === thoughtThreadId) : undefined;
  const thoughtProgressEvents = thoughtThreadId
    ? progressEvents.filter((item) => item.agent_thread_id === thoughtThreadId)
    : [];
  const thoughtTimeline = useMemo<ThoughtTimelineItem[]>(() => {
    const threadMessages: ThoughtTimelineItem[] = (thoughtThread?.messages ?? []).map((item) => ({
      kind: "message",
      id: item.id,
      role: item.role,
      content: item.content,
      created_at: item.created_at,
    }));
    const savedProgress: ThoughtTimelineItem[] = thoughtProgressEvents.map((item) => ({
      kind: "progress",
      id: item.id,
      event_type: item.event_type,
      content_md: item.content_md,
      desktop_run_id: item.desktop_run_id,
      created_at: item.created_at,
    }));
    return [...threadMessages, ...savedProgress].sort((left, right) => timestampMs(left.created_at) - timestampMs(right.created_at));
  }, [thoughtProgressEvents, thoughtThread?.messages]);
  const orchestratorLiveThread = orchestratorThread
    ? liveThreads[orchestratorThread.id] ?? liveThreads[orchestratorThread.desktop_thread_id]
    : undefined;
  const orchestratorThinking = Boolean(orchestratorLiveThread?.active_run && isActiveDesktopRun(orchestratorLiveThread.active_run.status));
  const orchestratorThinkingText = orchestratorThread
    ? latestThreadProgress(orchestratorThread) ?? latestRuntimeProgress(orchestratorLiveThread) ?? "Orchestrator is thinking..."
    : "Orchestrator is thinking...";

  useEffect(() => {
    if (!thoughtStoredThread) return;
    void refreshLiveThread(thoughtStoredThread.desktop_thread_id);
  }, [thoughtStoredThread?.desktop_thread_id]);

  function toggleAgent(agentId: string) {
    if (started) return;
    setSelectedAgentIds((current) =>
      current.includes(agentId) ? current.filter((id) => id !== agentId) : [...current, agentId],
    );
  }

  function handleScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 96;
  }

  function newChat() {
    setThreadId(null);
    setOrchestratorThread(null);
    setAgentThreads([]);
    setLiveThreads({});
    setMessages([]);
    setProgressEvents([]);
    setActiveDraft(null);
    setDraftQuestions([]);
    setDraftQuestionIndex(0);
    setDraftMode(true);
    setDiscussions([]);
    setDiscussionDetail(null);
    setMessage("");
    setError(null);
    processedDesktopMessages.current.clear();
    persistedProgressEvents.current.clear();
    activeDiscussionStarts.current.clear();
    resumedQuestionBatches.current.clear();
    stickToBottomRef.current = true;
    setPanelMode("agents");
    setPanelOpen(true);
    void loadChatHistory();
  }

  async function createChatRecord() {
    const chat = createThread
      ? await createThread()
      : await api.createChatThread({ thread_type: manifestAgentId, title });
    await Promise.all(
      selectedAgentIds.map((agentId) =>
        api.upsertChatAgent(chat.id, agentId, { agent_id: agentId, enabled: true }),
      ),
    );
    setThreadId(chat.id);
    return chat;
  }

  async function createOrchestratorThread(chatThreadId: string, initialText: string, triggerId: string) {
    const runtime = agentRuntime();
    const variables = await buildInitialVariables(chatThreadId, initialText);
    const prompt = await renderManifestPrompt(manifestAgentId, "initial", variables);
    let legacyNeedsRun = false;
    const desktop = runtime?.start
      ? await runtime.start({
          agentId: manifestAgentId,
          title: `${title} Orchestrator`,
          variables,
          metadata: { chatThreadId, manifestAgentId, vibeOwnerType: "orchestrator" },
        })
      : runtime?.createAgentThread
        ? await runtime.createAgentThread({
            title: `${title} Orchestrator`,
            manifestAgentId,
            initialPrompt: prompt,
            metadata: { chatThreadId, manifestAgentId, vibeOwnerType: "orchestrator" },
          }).then((thread) => {
            legacyNeedsRun = true;
            return thread;
          })
        : { desktop_thread_id: `local-${chatThreadId}-orchestrator`, title: `${title} Orchestrator`, status: "idle" };
    const stored = await api.createAgentThread({
      desktop_thread_id: desktop.desktop_thread_id,
      agent_id: null,
      manifest_agent_id: manifestAgentId,
      title: `${title} Orchestrator`,
      initial_prompt_snapshot_md: prompt,
      chat_thread_id: chatThreadId,
      owner_type: "orchestrator",
      invocation_mode: "orchestrator",
    });
    setLiveThreads((current) => ({ ...current, [stored.id]: desktop, [desktop.desktop_thread_id]: desktop }));
    if (desktop.active_run?.desktop_run_id) {
      await api.createAgentRun({
        agent_thread_id: stored.id,
        desktop_run_id: desktop.active_run.desktop_run_id,
        trigger_type: "user_message",
        trigger_id: triggerId,
        input_md: initialText,
        context_snapshot_md: JSON.stringify(variables, null, 2),
      });
    } else if (legacyNeedsRun) {
      await sendToThread(stored, initialText, "user_message", triggerId, await buildResumeVariables(chatThreadId, initialText));
    }
    return stored;
  }

  async function send() {
    const text = message.trim();
    if (disabledInput || !text) return;
    setError(null);
    try {
      setMessage("");
      const existing = threadId && orchestratorThread
        ? { chatThreadId: threadId, orchestrator: orchestratorThread }
        : null;
      const chatThreadId = existing?.chatThreadId ?? (await createChatRecord()).id;
      const userMessage = await api.createChatMessage({
        chat_thread_id: chatThreadId,
        role: "user",
        source_type: "user",
        content_md: text,
      });
      setMessages((current) => [...current, userMessage]);
      if (existing) {
        await sendToThread(existing.orchestrator, text, "user_message", userMessage.id, await buildResumeVariables(chatThreadId, text));
      } else {
        const orchestrator = await createOrchestratorThread(chatThreadId, text, userMessage.id);
        setOrchestratorThread(orchestrator);
        setAgentThreads((current) => current.some((item) => item.id === orchestrator.id) ? current : [...current, orchestrator]);
      }
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send message.");
    }
  }

  async function sendToThread(
    storedThread: AgentThread,
    text: string,
    triggerType: string,
    triggerId: string,
    variables: Record<string, unknown>,
  ) {
    const runtime = agentRuntime();
    if (!runtime) {
      const assistant = await api.createChatMessage({
        chat_thread_id: storedThread.chat_thread_id ?? threadId ?? "",
        role: "assistant",
        source_type: "system",
        content_md: "Desktop agent runtime is not available in this browser context.",
      });
      setMessages((current) => [...current, assistant]);
      return;
    }
    const desktopThreadId = storedThread.desktop_thread_id;
    const live = await runtime.getAgentThread?.(desktopThreadId).catch(() => null);
    const manifestVariables = await filterManifestVariables(storedThread.manifest_agent_id, "resume", variables);
    const promptContext = JSON.stringify(manifestVariables, null, 2);
    const run = await withTimeout(
      runtime.resume
        ? runtime.resume({ threadId: desktopThreadId, variables: manifestVariables })
        : runtime.startAgentThreadRun
          ? runtime.startAgentThreadRun({ desktopThreadId, message: text, context: promptContext })
          : Promise.reject(new Error("Desktop agent runtime cannot start runs.")),
      10000,
      "Agent run start timed out.",
    );
    await api.createAgentRun({
      agent_thread_id: storedThread.id,
      desktop_run_id: run.desktop_run_id,
      trigger_type: triggerType,
      trigger_id: triggerId,
      input_md: text,
      context_snapshot_md: promptContext,
    });
    setLiveThreads((current) => ({
      ...current,
      [storedThread.id]: live ?? current[storedThread.id],
      [desktopThreadId]: live ?? current[desktopThreadId],
    }));
    await refreshLiveThread(desktopThreadId);
  }

  async function advanceDiscussionRuns(nextDiscussions: Discussion[], storedThreads: AgentThread[]) {
    if (!threadId) return;
    for (const discussion of nextDiscussions) {
      if (discussion.status !== "running" || !discussion.current_agent_id) continue;
      const key = `${discussion.id}:${discussion.current_agent_id}:${discussion.current_round}`;
      if (activeDiscussionStarts.current.has(key)) continue;
      const detail = await api.discussionDetail(discussion.id).catch(() => null);
      if (!detail?.next_agent_id) continue;
      const participant = detail.participants.find((item) => item.agent_id === detail.next_agent_id);
      const agent = agents.find((item) => item.id === detail.next_agent_id);
      if (!participant || !agent) continue;
      let stored = participant.agent_thread_id
        ? storedThreads.find((item) => item.id === participant.agent_thread_id)
        : undefined;
      if (!stored) {
        stored = await createDiscussionAgentThread(detail, agent);
        storedThreads = [...storedThreads, stored];
        setAgentThreads((current) => current.some((item) => item.id === stored!.id) ? current : [...current, stored!]);
      }
      const live = await agentRuntime()?.getAgentThread?.(stored.desktop_thread_id).catch(() => null);
      if (live?.active_run && isActiveDesktopRun(live.active_run.status)) continue;
      activeDiscussionStarts.current.add(key);
      const variables = await discussionVariables(detail, agent);
      await sendToThread(stored, `Discussion turn: ${detail.discussion.title}`, "discussion", discussion.id, variables);
    }
  }

  async function createDiscussionAgentThread(detail: DiscussionDetail, agent: Agent) {
    const runtime = agentRuntime();
    const variables = await filterManifestVariables("agentChatDiscussion", "initial", await discussionVariables(detail, agent));
    const prompt = await renderManifestPrompt("agentChatDiscussion", "initial", variables);
    const desktop = runtime?.start
      ? await runtime.start({
          agentId: "agentChatDiscussion",
          title: detail.discussion.title,
          variables,
          runtime: runtimeFor(agent),
          metadata: { vibeAgentId: agent.id, chatThreadId: detail.discussion.chat_thread_id, discussionId: detail.discussion.id },
        })
      : runtime?.createAgentThread
        ? await runtime.createAgentThread({
            title: detail.discussion.title,
            manifestAgentId: "agentChatDiscussion",
            initialPrompt: prompt,
            runtime: runtimeFor(agent),
            metadata: { vibeAgentId: agent.id, chatThreadId: detail.discussion.chat_thread_id, discussionId: detail.discussion.id },
          })
        : { desktop_thread_id: `local-${detail.discussion.id}-${agent.id}`, title: agent.name, status: "idle" };
    const stored = await api.createAgentThread({
      desktop_thread_id: desktop.desktop_thread_id,
      agent_id: agent.id,
      manifest_agent_id: "agentChatDiscussion",
      title: detail.discussion.title,
      initial_prompt_snapshot_md: prompt,
      chat_thread_id: detail.discussion.chat_thread_id,
      discussion_id: detail.discussion.id,
      owner_type: "agent",
      invocation_mode: "discussion",
    });
    setLiveThreads((current) => ({ ...current, [stored.id]: desktop, [desktop.desktop_thread_id]: desktop }));
    return stored;
  }

  async function ingestOrchestratorMessages(storedThread: AgentThread | null) {
    if (!threadId || !storedThread) return;
    const runtime = agentRuntime();
    const live = await runtime?.getAgentThread?.(storedThread.desktop_thread_id).catch(() => null);
    if (!live) return;
    setLiveThreads((current) => ({ ...current, [storedThread.id]: live, [storedThread.desktop_thread_id]: live }));
    for (const item of live.messages ?? []) {
      if (item.role !== "assistant") continue;
      const key = `${storedThread.id}:${item.id}`;
      if (processedDesktopMessages.current.has(key)) continue;
      processedDesktopMessages.current.add(key);
      const saved = await api.createChatMessage({
        chat_thread_id: threadId,
        role: "assistant",
        source_type: "orchestrator",
        source_id: storedThread.id,
        content_md: item.content,
        metadata_json: { desktop_message_id: item.id },
      }).catch(() => null);
      if (saved) setMessages((current) => current.some((existing) => existing.id === saved.id) ? current : [...current, saved]);
    }
  }

  async function refreshLiveThread(desktopThreadId: string) {
    const runtime = agentRuntime();
    if (!runtime) return;
    const summary = await runtime.getAgentThread?.(desktopThreadId).catch(() => null);
    if (!summary) return;
    const stored = await api.agentThreads().then((items) => items.find((item) => item.desktop_thread_id === desktopThreadId)).catch(() => null);
    setLiveThreads((current) => ({
      ...current,
      [desktopThreadId]: summary,
      ...(stored ? { [stored.id]: summary } : {}),
    }));
  }

  async function loadChatHistory(): Promise<ChatHistoryItem[]> {
    const threads = loadHistoryThreads
      ? await loadHistoryThreads()
      : (await api.chatThreads()).filter((item) => item.thread_type === manifestAgentId);
    const withPreviews = await Promise.all(
      threads.map(async (thread) => {
        const threadMessages = await api.chatMessages(thread.id).catch(() => []);
        const firstUserMessage = threadMessages.find((item) => item.role === "user");
        return {
          thread,
          preview: truncatePreview(firstUserMessage?.content_md || thread.title),
        };
      }),
    );
    const sorted = withPreviews.sort((first, second) => timestampMs(second.thread.updated_at) - timestampMs(first.thread.updated_at));
    setChatHistory(sorted);
    return sorted;
  }

  async function loadHistoricalChat(item: ChatHistoryItem) {
    setError(null);
    const [threadMessages, threadParticipants, storedThreads, nextProgress, nextDiscussions, nextDraftState] = await Promise.all([
      api.chatMessages(item.thread.id),
      api.chatAgents(item.thread.id),
      api.agentThreads(),
      api.chatProgress(item.thread.id),
      api.discussions(item.thread.id),
      api.activeDraft(item.thread.id).catch(() => ({ draft: null, questions: [] })),
    ]);
    processedDesktopMessages.current.clear();
    persistedProgressEvents.current.clear();
    activeDiscussionStarts.current.clear();
    resumedQuestionBatches.current.clear();
    const relevantThreads = storedThreads.filter((thread) => thread.chat_thread_id === item.thread.id);
    setThreadId(item.thread.id);
    setMessages(threadMessages.filter((message) => message.visibility === "visible"));
    setProgressEvents(nextProgress);
    setActiveDraft(nextDraftState.draft ?? null);
    setDraftQuestions(nextDraftState.questions ?? []);
    setDraftQuestionIndex(0);
    setSelectedAgentIds(threadParticipants.filter((participant) => participant.enabled).map((participant) => participant.agent_id));
    setAgentThreads(relevantThreads);
    setDiscussions(nextDiscussions);
    setOrchestratorThread(relevantThreads.find((thread) => thread.owner_type === "orchestrator") ?? null);
    for (const stored of relevantThreads) void refreshLiveThread(stored.desktop_thread_id);
    stickToBottomRef.current = true;
  }

  async function persistProgressFromRuntimeEvent(event: {
    type?: string;
    desktop_thread_id?: string;
    run?: { desktop_thread_id?: string; desktop_run_id?: string; status?: string; progressLog?: string[] };
    progress?: string;
  }) {
    if (!threadId || !event.type || !shouldPersistProgressEvent(event.type)) return;
    const desktopThreadId = event.desktop_thread_id ?? event.run?.desktop_thread_id;
    const desktopRunId = event.run?.desktop_run_id;
    if (!desktopThreadId || !desktopRunId) return;
    const stored = await api.agentThreads().then((items) => items.find((item) => item.desktop_thread_id === desktopThreadId)).catch(() => null);
    if (!stored) return;
    const content = progressContent(event);
    if (!content) return;
    const dedupeKey = `${threadId}:${stored.id}:${desktopRunId}:${event.type}:${content}`;
    if (persistedProgressEvents.current.has(dedupeKey)) return;
    persistedProgressEvents.current.add(dedupeKey);
    const saved = await api.createChatProgress({
      chat_thread_id: threadId,
      agent_id: stored.agent_id,
      agent_thread_id: stored.id,
      desktop_run_id: desktopRunId,
      event_type: event.type,
      content_md: content,
    }).catch(() => null);
    if (saved) setProgressEvents((current) => current.some((item) => item.id === saved.id) ? current : [...current, saved]);
  }

  async function cancelThread(storedThread: AgentThread) {
    const live = await agentRuntime()?.getAgentThread?.(storedThread.desktop_thread_id);
    const runId = live?.active_run?.desktop_run_id;
    if (!runId) return;
    const runtime = agentRuntime();
    if (runtime?.stop) {
      await runtime.stop({ threadId: storedThread.desktop_thread_id, runId });
    } else {
      await runtime?.cancelAgentThreadRun?.({ desktopThreadId: storedThread.desktop_thread_id, desktopRunId: runId });
    }
    await refreshLiveThread(storedThread.desktop_thread_id);
  }

  async function answerCurrentDraftQuestion(optionLabel: string) {
    const question = pendingDraftQuestions[draftQuestionIndex];
    if (!question || !threadId || !orchestratorThread) return;
    await api.answerDraftQuestion(question.id, { selected_option: optionLabel, answer_text: optionLabel });
    const nextQuestions = draftQuestions.map((item) =>
      item.id === question.id
        ? { ...item, selected_option: optionLabel, answer_text: optionLabel, status: "answered" }
        : item,
    );
    const nextState = await api.activeDraft(question.chat_thread_id);
    setDraftQuestions(nextState.questions ?? []);
    setActiveDraft(nextState.draft ?? null);
    setDraftQuestionIndex((current) => Math.min(current + 1, Math.max(0, pendingDraftQuestions.length - 2)));
    const batchQuestions = nextQuestions.filter((item) => item.batch_id === question.batch_id);
    const batchComplete = batchQuestions.length > 0 && batchQuestions.every((item) => item.status === "answered");
    if (batchComplete && !resumedQuestionBatches.current.has(question.batch_id)) {
      resumedQuestionBatches.current.add(question.batch_id);
      const answers = batchQuestions.map((item) => ({
        question: item.question,
        selected_option: item.selected_option,
        answer_text: item.answer_text,
      }));
      const text = `The user answered the pending Draft Mode questions:\n\n${answers
        .map((item, index) => `${index + 1}. ${item.question}\nAnswer: ${item.answer_text || item.selected_option || ""}`)
        .join("\n\n")}`;
      await sendToThread(
        orchestratorThread,
        text,
        "draft_questions_answered",
        question.batch_id,
        await buildResumeVariables(threadId, text),
      );
    }
  }

  async function acceptDraft() {
    if (!activeDraft || !threadId || !orchestratorThread) return;
    const updated = await api.updateDraft(activeDraft.id, { status: "accepted" });
    setActiveDraft(updated);
    setDraftMode(false);
    const text = `The user accepted the active draft.\n\ndraft_id: ${updated.id}\n\n${updated.description_md}`;
    await sendToThread(orchestratorThread, text, "draft_accepted", updated.id, await buildResumeVariables(threadId, text));
  }

  async function requestDraftChanges() {
    if (!activeDraft || !threadId || !orchestratorThread) return;
    const updated = await api.updateDraft(activeDraft.id, { status: "changes_requested" });
    setActiveDraft(updated);
    const text = `The user requested changes to the active draft.\n\ndraft_id: ${activeDraft.id}\n\nCurrent draft:\n${activeDraft.description_md}`;
    await sendToThread(
      orchestratorThread,
      text,
      "draft_changes_requested",
      activeDraft.id,
      await buildResumeVariables(threadId, text),
    );
  }

  async function buildInitialVariables(chatThreadId: string, text: string) {
    const repositories = await repositoryContext();
    const plan = defaultPromptContext?.plan && typeof defaultPromptContext.plan === "object"
      ? defaultPromptContext.plan as Record<string, unknown>
      : {};
    return filterManifestVariables(manifestAgentId, "initial", {
      ...defaultPromptContext,
      runtimeContract: [
        `chat_thread_id: ${chatThreadId}`,
        `manifest_orchestrator_id: ${manifestAgentId}`,
        "You are the manifest-defined Vibe orchestrator for this chat.",
        "The database Agent records are invokable coworkers only.",
        "Use MCP reads before claiming Vibe state.",
        `draft_mode: ${draftMode ? "active" : "inactive"}`,
      ].join("\n"),
      agentsInChat: describeSelectedAgents(),
      planDescription: typeof plan.description === "string" ? plan.description : "",
      planSteps: typeof plan.steps === "string" ? plan.steps : "",
      planAssignments: typeof plan.assignments === "string" ? plan.assignments : "",
      repositoryContext: repositories.text,
      interfaceNotebook: "Notebook context is provided by Vibe MCP when needed.",
      userMessage: text,
    });
  }

  async function buildResumeVariables(chatThreadId: string, text: string) {
    const repositories = await repositoryContext();
    return filterManifestVariables(manifestAgentId, "resume", {
      runtimeContract: [
        `chat_thread_id: ${chatThreadId}`,
        `manifest_orchestrator_id: ${manifestAgentId}`,
        "You are the manifest-defined Vibe orchestrator for this chat.",
        "The database Agent records are invokable coworkers only.",
        "Use MCP reads before claiming Vibe state.",
        `draft_mode: ${draftMode ? "active" : "inactive"}`,
      ].join("\n"),
      turnPayload: {
        chat_thread_id: chatThreadId,
        selected_agent_ids: selectedAgentIds,
        repository_ids: repositories.ids,
        context: defaultPromptContext ?? {},
      },
      userMessage: text,
    });
  }

  async function discussionVariables(detail: DiscussionDetail, agent: Agent) {
    const repositories = await repositoryContext();
    return {
      runtimeContract: [
        `discussion_id: ${detail.discussion.id}`,
        `agent_id: ${agent.id}`,
        "This is a deterministic discussion turn.",
        "Do not steer another thread. Write exactly one discussion message through MCP.",
      ].join("\n"),
      turnPayload: detail,
      agentIdentity: agent.identity_md,
      agentId: agent.id,
      discussionId: detail.discussion.id,
      discussionObjective: detail.discussion.objective_md,
      discussionMessages: detail.messages.length
        ? detail.messages.map((item) => `${agentName(item.agent_id)}: ${item.content_md}`).join("\n\n")
        : "No previous discussion messages.",
      repositoryContext: repositories.text,
      agentTone: agent.tone_md,
      globalGuardrails: "",
      agentGuardrails: agent.guardrails_md,
    };
  }

  async function repositoryContext() {
    const repositories = await api.repositories().catch(() => []);
    if (repositories.length === 0) return { text: "No repositories are configured in Vibe.", ids: [] as string[] };
    return {
      ids: repositories.map((repository) => repository.id),
      text: repositories
        .map((repository) => {
          const localPath = repository.local_path ? `; local_path=${repository.local_path}` : "";
          const description = repository.description ? `; description=${repository.description}` : "";
          return `- ${repository.name}: id=${repository.id}; remote=${repository.remote_url}; default_branch=${repository.default_branch}${localPath}${description}`;
        })
        .join("\n"),
    };
  }

  async function renderManifestPrompt(manifestId: string, kind: "initial" | "resume", variables: Record<string, unknown>) {
    const context = await window.forgerApp?.getContext?.().catch(() => null);
    const manifestAgent = context?.agents?.find((item) => item.id === manifestId);
    const template = manifestAgent?.prompts?.[kind]?.body ?? manifestAgent?.initialPrompt ?? "";
    const manifestVariables = await filterManifestVariables(manifestId, kind, variables);
    return template.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_match, key: string) => {
      const value = manifestVariables[key.trim()];
      if (typeof value === "string") return value;
      if (value == null) return "";
      return JSON.stringify(value, null, 2);
    });
  }

  async function filterManifestVariables(manifestId: string, kind: ManifestPromptKind, variables: Record<string, unknown>) {
    const context = await window.forgerApp?.getContext?.().catch(() => null);
    const manifestAgent = context?.agents?.find((item) => item.id === manifestId);
    const declared = manifestAgent?.prompts?.[kind]?.variables
      ?? MANIFEST_PROMPT_VARIABLES[manifestId]?.[kind]?.reduce<Record<string, { type: string }>>((output, key) => {
        output[key] = { type: "text" };
        return output;
      }, {});
    if (!declared) return {};
    return Object.fromEntries(
      Object.keys(declared)
        .filter((key) => Object.prototype.hasOwnProperty.call(variables, key))
        .map((key) => [key, variables[key]]),
    );
  }

  function describeSelectedAgents() {
    return selectedAgentIds
      .map((agentId) => {
        const agent = agents.find((item) => item.id === agentId);
        return `- ${agent?.name ?? agentId}: agent_id=${agentId}`;
      })
      .join("\n") || "No Agents selected.";
  }

  function agentName(agentId: string) {
    return agents.find((agent) => agent.id === agentId)?.name ?? "Agent";
  }

  function discussionThreads(discussionId: string) {
    return agentThreads.filter((item) => item.discussion_id === discussionId || item.invocation_mode === "discussion" && item.discussion_id === discussionId);
  }

  function agentSingleTaskThreads(agentId: string) {
    return singleAgentThreads.filter((item) => item.agent_id === agentId);
  }

  function shouldPersistProgressEvent(type: string) {
    return ["run.started", "run.progress", "run.canceled", "run.failed", "run.completed"].includes(type);
  }

  function progressContent(event: { type?: string; run?: { status?: string; progressLog?: string[] }; progress?: string }) {
    if (event.progress) return event.progress;
    if (event.type === "run.started") return "Run started.";
    if (event.type === "run.completed") return "Run completed.";
    if (event.type === "run.canceled") return "Run canceled.";
    if (event.type === "run.failed") return "Run failed.";
    const progressLog = event.run?.progressLog ?? [];
    return progressLog.length > 0 ? progressLog[progressLog.length - 1] : "";
  }

  function runtimeFor(agent: Agent) {
    if (agent.provider === "auto") return { provider: "auto" };
    return { provider: agent.provider, model: agent.model, effort: agent.reasoning_effort };
  }

  function truncatePreview(text: string) {
    const compact = text.replace(/\s+/g, " ").trim();
    return compact.length > 76 ? `${compact.slice(0, 73)}...` : compact || "Untitled chat";
  }

  function formatThreadDate(value: string) {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(parseTimestamp(value));
  }

  function timestampMs(value: string) {
    return parseTimestamp(value).getTime();
  }

  function parseTimestamp(value: string) {
    const normalized = value.includes("T") ? value : value.replace(" ", "T");
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
    return new Date(hasTimezone ? normalized : `${normalized}Z`);
  }

  function isActiveDesktopRun(status: string | undefined) {
    return Boolean(status && !["completed", "failed", "canceled"].includes(status));
  }

  function latestThreadProgress(storedThread: AgentThread) {
    const items = progressEvents.filter((item) => item.agent_thread_id === storedThread.id);
    return items.length > 0 ? items[items.length - 1].content_md : "";
  }

  function latestRuntimeProgress(live?: DesktopAgentThread) {
    const progressLog = live?.progressLog ?? [];
    return progressLog.length > 0 ? progressLog[progressLog.length - 1] : "";
  }

  function liveThreadFor(storedThread: AgentThread) {
    return liveThreads[storedThread.id] ?? liveThreads[storedThread.desktop_thread_id];
  }

  function threadStatusText(storedThread: AgentThread) {
    const live = liveThreadFor(storedThread);
    return live?.active_run?.status ?? live?.status ?? storedThread.status;
  }

  function threadVisualState(storedThread: AgentThread): ThreadVisualState {
    const status = threadStatusText(storedThread);
    if (isActiveDesktopRun(status)) return "running";
    if (["failed", "canceled", "error"].includes(status)) return "error";
    return "ready";
  }

  function ThreadStateIcon({ state }: { state: ThreadVisualState }) {
    if (state === "running") return <CircularProgress size={16} thickness={5} />;
    if (state === "error") return <Cancel fontSize="small" color="error" />;
    return <CheckCircle fontSize="small" color="success" />;
  }

  function ThreadRow({ storedThread, agentLabel }: { storedThread: AgentThread; agentLabel?: string }) {
    const state = threadVisualState(storedThread);
    const status = threadStatusText(storedThread);
    const running = state === "running";
    const title = threadDisplayTitle(storedThread, agentLabel);
    return (
      <Box sx={{ p: 0.75, borderRadius: 1, bgcolor: "rgba(148, 163, 184, 0.08)" }}>
        <Stack direction="row" alignItems="center" spacing={0.75}>
          <ThreadStateIcon state={state} />
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="caption" sx={{ display: "block", lineHeight: 1.25 }} noWrap>
              {agentLabel ? `${agentLabel} · ` : ""}{title}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2 }} noWrap>
              {status}
            </Typography>
          </Box>
          <Tooltip title="Thoughts">
            <IconButton size="small" color="primary" onClick={(event) => {
              event.stopPropagation();
              setThoughtThreadId(storedThread.id);
            }}>
              <Psychology fontSize="small" />
            </IconButton>
          </Tooltip>
          {running && (
            <Tooltip title="Stop">
              <IconButton size="small" color="error" onClick={(event) => {
                event.stopPropagation();
                void cancelThread(storedThread);
              }}>
                <StopCircle fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Stack>
      </Box>
    );
  }

  function threadDisplayTitle(storedThread: AgentThread, agentLabel?: string) {
    if (!agentLabel) return storedThread.title;
    const prefix = `${agentLabel} · `;
    return storedThread.title.startsWith(prefix) ? storedThread.title.slice(prefix.length) : storedThread.title;
  }

  function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error(message)), timeoutMs);
      promise.then(resolve).catch(reject).finally(() => window.clearTimeout(timeout));
    });
  }

  return (
    <Stack spacing={2} sx={{ flex: 1, height: "100%", minHeight: 0, overflow: "hidden" }}>
      <SectionHeader
        title={title}
        subtitle={subtitle}
        action={
          <Stack direction="row" spacing={1}>
            <Tooltip title="Show Agents">
              <Button size="small" variant={panelOpen && panelMode === "agents" ? "contained" : "outlined"} startIcon={<Groups />} onClick={() => {
                setPanelMode("agents");
                setPanelOpen((current) => (panelMode === "agents" ? !current : true));
              }}>
                Agents
              </Button>
            </Tooltip>
            <Tooltip title="Show chat history">
              <Button size="small" variant={panelOpen && panelMode === "history" ? "contained" : "outlined"} startIcon={<History />} onClick={() => {
                setPanelMode("history");
                setPanelOpen((current) => (panelMode === "history" ? !current : true));
              }}>
                History
              </Button>
            </Tooltip>
          </Stack>
        }
      />
      {!agentRuntime() && <Alert severity="info">Desktop agent runtime is unavailable in standalone browser mode. Chat state still saves locally.</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="stretch" sx={{ flex: 1, minHeight: 0 }}>
        <Stack spacing={1.5} sx={{ flex: 1, minWidth: 0, minHeight: 0, overflow: "hidden" }}>
          <Paper ref={scrollRef} onScroll={handleScroll} sx={{ p: 1.5, borderRadius: 1, flex: 1, minHeight: 0, overflowY: "auto", bgcolor: "background.default" }}>
            <Stack spacing={1.25} sx={{ minHeight: "100%" }}>
              {messages.length === 0 ? (
                <Box sx={{ minHeight: "100%", display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
                  <Typography color="text.secondary">Start a conversation with the orchestrator.</Typography>
                </Box>
              ) : messages.map((item) => (
                <Paper key={item.id} variant="outlined" sx={{ p: 1.25, alignSelf: item.role === "user" ? "flex-end" : "flex-start", maxWidth: "82%", bgcolor: item.role === "user" ? "rgba(125, 211, 252, 0.09)" : "background.paper" }}>
                  {item.source_type === "orchestrator" && <Typography variant="caption" color="text.secondary">Orchestrator</Typography>}
                  <MarkdownContent content={item.content_md} />
                </Paper>
              ))}
              {orchestratorThinking && (
                <Paper variant="outlined" sx={{ px: 1.25, py: 0.9, alignSelf: "flex-start", maxWidth: "82%", bgcolor: "background.paper" }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <CircularProgress size={16} thickness={5} />
                    <Typography variant="body2" color="text.secondary" noWrap>{orchestratorThinkingText}</Typography>
                  </Stack>
                </Paper>
              )}
              {currentDraftQuestion && (
                <Paper variant="outlined" sx={{ p: 1.25, borderRadius: 1, bgcolor: "background.paper" }}>
                  <Stack spacing={1}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Typography fontWeight={850}>{currentDraftQuestion.question}</Typography>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <IconButton size="small" disabled={draftQuestionIndex <= 0} onClick={() => setDraftQuestionIndex((current) => Math.max(0, current - 1))}>
                          <ArrowBackIosNew fontSize="inherit" />
                        </IconButton>
                        <Typography variant="caption" color="text.secondary">
                          {Math.min(draftQuestionIndex + 1, pendingDraftQuestions.length)} of {pendingDraftQuestions.length}
                        </Typography>
                        <IconButton size="small" disabled={draftQuestionIndex >= pendingDraftQuestions.length - 1} onClick={() => setDraftQuestionIndex((current) => Math.min(pendingDraftQuestions.length - 1, current + 1))}>
                          <ArrowForwardIos fontSize="inherit" />
                        </IconButton>
                      </Stack>
                    </Stack>
                    <Stack spacing={0.75}>
                      {currentDraftQuestion.options_json.map((option, index) => (
                        <Button key={`${currentDraftQuestion.id}-${option.label}`} variant={index === 0 ? "contained" : "outlined"} onClick={() => void answerCurrentDraftQuestion(option.label)} sx={{ justifyContent: "flex-start", textAlign: "left" }}>
                          {index + 1}. {option.label}{option.description ? ` - ${option.description}` : ""}
                        </Button>
                      ))}
                    </Stack>
                  </Stack>
                </Paper>
              )}
              {activeDraft && activeDraft.status === "active" && (
                <Paper variant="outlined" sx={{ p: 1.25, borderRadius: 1, bgcolor: "background.paper" }}>
                  <Stack spacing={1}>
                    <Typography variant="caption" color="text.secondary">Draft</Typography>
                    <Box sx={{ maxHeight: { xs: 260, md: 360 }, overflowY: "auto", pr: 0.5 }}>
                      <MarkdownContent content={activeDraft.description_md} />
                    </Box>
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      <Button size="small" startIcon={<Close />} onClick={() => void requestDraftChanges()}>Request changes</Button>
                      <Button size="small" variant="contained" startIcon={<CheckCircle />} onClick={() => void acceptDraft()}>Accept draft</Button>
                    </Stack>
                  </Stack>
                </Paper>
              )}
            </Stack>
          </Paper>
          <Stack spacing={1}>
            <TextField value={message} fullWidth multiline maxRows={5} placeholder={activeGatePending ? "Answer the pending draft item to continue..." : "Message the orchestrator..."} disabled={disabledInput || activeGatePending} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => {
              if (event.key === "Tab" && event.shiftKey) {
                event.preventDefault();
                setDraftMode((current) => !current);
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }} />
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Stack direction="row" spacing={1} alignItems="center">
                <Button size="small" startIcon={<AddComment />} onClick={newChat}>New chat</Button>
                <Button size="small" variant={draftMode ? "contained" : "outlined"} onClick={() => setDraftMode((current) => !current)}>
                  Draft Mode {draftMode ? "on" : "off"}
                </Button>
              </Stack>
              <Button size="small" variant="contained" endIcon={<Send />} disabled={disabledInput || activeGatePending || !message.trim()} onClick={() => void send()} sx={{ minWidth: 96 }}>Send</Button>
            </Stack>
          </Stack>
        </Stack>
        {panelOpen && panelMode === "agents" && (
          <Paper sx={{ p: 1.25, borderRadius: 1, width: { xs: "100%", lg: 340 }, flexShrink: 0, minHeight: 0, overflowY: "auto" }}>
            <Stack spacing={1}>
              <Typography variant="subtitle2" fontWeight={850}>Available Agents</Typography>
              <Typography variant="caption" color="text.secondary">
                {started ? "Selected Agents are available to the orchestrator." : "Agents are optional. Leave all unselected to chat only with the orchestrator."}
              </Typography>
              <Divider />
              {enabledAgents.map((agent) => {
                const selected = selectedAgentIds.includes(agent.id);
                const relatedThreads = agentSingleTaskThreads(agent.id);
                return (
                  <Box key={agent.id} onClick={() => toggleAgent(agent.id)} sx={{ p: 1, border: "1px solid", borderColor: selected ? "primary.main" : "divider", borderRadius: 1, cursor: started ? "default" : "pointer", bgcolor: selected ? "rgba(125, 211, 252, 0.06)" : "transparent" }}>
                    <Stack spacing={0.75}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                        <Typography fontWeight={800}>{agent.name}</Typography>
                        {!started && selected && <CheckCircle fontSize="small" color="primary" />}
                      </Stack>
                      {relatedThreads.length > 0 && (
                        <Stack spacing={0.5}>
                          {relatedThreads.map((stored) => (
                            <ThreadRow key={stored.id} storedThread={stored} agentLabel={agent.name} />
                          ))}
                        </Stack>
                      )}
                    </Stack>
                  </Box>
                );
              })}
              {discussions.length > 0 && (
                <>
                  <Divider />
                  <Typography variant="subtitle2" fontWeight={850}>Discussions</Typography>
                  {discussions.map((discussion) => {
                    const relatedThreads = discussionThreads(discussion.id);
                    return (
                      <Box key={discussion.id} onClick={() => void api.discussionDetail(discussion.id).then(setDiscussionDetail)} sx={{ p: 1, border: "1px solid", borderColor: "divider", borderRadius: 1, cursor: "pointer" }}>
                        <Typography fontWeight={750} noWrap>{discussion.title}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {discussion.status} · round {discussion.current_round} · current {discussion.current_agent_id ? agentName(discussion.current_agent_id) : "none"}
                        </Typography>
                        {relatedThreads.length > 0 && (
                          <Stack spacing={0.5} sx={{ mt: 1 }}>
                            {relatedThreads.map((stored) => (
                              <ThreadRow key={stored.id} storedThread={stored} agentLabel={stored.agent_id ? agentName(stored.agent_id) : undefined} />
                            ))}
                          </Stack>
                        )}
                      </Box>
                    );
                  })}
                </>
              )}
            </Stack>
          </Paper>
        )}
        {panelOpen && panelMode === "history" && (
          <Paper sx={{ p: 1.25, borderRadius: 1, width: { xs: "100%", lg: 320 }, flexShrink: 0, minHeight: 0, overflowY: "auto" }}>
            <Stack spacing={1}>
              <Typography variant="subtitle2" fontWeight={850}>History</Typography>
              <Typography variant="caption" color="text.secondary">{historyDescription ?? "Orchestrator chats."}</Typography>
              <Divider />
              {chatHistory.length === 0 ? <Typography variant="body2" color="text.secondary">No saved chats yet.</Typography> : chatHistory.map((item) => (
                <Box key={item.thread.id} onClick={() => void loadHistoricalChat(item)} sx={{ px: 0.9, py: 0.75, border: "1px solid", borderColor: item.thread.id === threadId ? "primary.main" : "divider", borderRadius: 1, cursor: "pointer", bgcolor: item.thread.id === threadId ? "rgba(125, 211, 252, 0.08)" : "transparent" }}>
                  <Typography variant="body2" noWrap sx={{ fontWeight: 650, lineHeight: 1.35, maxWidth: "100%" }}>{item.preview}</Typography>
                  <Typography variant="caption" color="text.secondary">{formatThreadDate(item.thread.updated_at)}</Typography>
                </Box>
              ))}
            </Stack>
          </Paper>
        )}
      </Stack>
      <Dialog open={Boolean(thoughtThreadId)} onClose={() => setThoughtThreadId(null)} fullWidth maxWidth="md">
        <DialogTitle>{thoughtStoredThread ? `${thoughtStoredThread.title} thoughts` : "Thoughts"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25}>
            {!thoughtThread && <Typography color="text.secondary">This thread has no runtime activity saved yet.</Typography>}
            {thoughtTimeline.map((item) => (
              <Paper key={`${item.kind}-${item.id}`} variant="outlined" sx={{ p: 1 }}>
                <Stack direction="row" justifyContent="space-between" spacing={1} sx={{ mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">{item.kind === "message" ? item.role : item.event_type}</Typography>
                  <Typography variant="caption" color="text.secondary">{formatThreadDate(item.created_at)}</Typography>
                </Stack>
                <MarkdownContent content={item.kind === "message" ? item.content : item.content_md} subtle={item.kind === "progress"} />
              </Paper>
            ))}
          </Stack>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(discussionDetail)} onClose={() => setDiscussionDetail(null)} fullWidth maxWidth="md">
        <DialogTitle>{discussionDetail?.discussion.title ?? "Discussion"}</DialogTitle>
        <DialogContent>
          {discussionDetail && (
            <Stack spacing={1.25}>
              <Stack direction="row" spacing={1} alignItems="center">
                <ThreadStateIcon state={discussionDetail.discussion.status === "running" ? "running" : discussionDetail.discussion.status === "failed" ? "error" : "ready"} />
                <Typography variant="body2" color="text.secondary">{discussionDetail.discussion.status}</Typography>
                <Typography variant="body2" color="text.secondary">Round {discussionDetail.discussion.current_round}</Typography>
              </Stack>
              <MarkdownContent content={discussionDetail.discussion.objective_md} subtle />
              {discussionDetail.messages.map((item) => (
                <Paper key={item.id} variant="outlined" sx={{ p: 1 }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                    <Typography variant="caption" color="text.secondary">{agentName(item.agent_id)}</Typography>
                    <Typography variant="caption" color="text.secondary">round {item.round_index}</Typography>
                    {item.end_discussion && <CheckCircle fontSize="small" color="success" />}
                  </Stack>
                  <MarkdownContent content={item.content_md} />
                </Paper>
              ))}
              {discussionDetail.discussion.consensus_md && (
                <Accordion defaultExpanded variant="outlined">
                  <AccordionSummary expandIcon={<ExpandMore />}>Consensus</AccordionSummary>
                  <AccordionDetails><MarkdownContent content={discussionDetail.discussion.consensus_md} /></AccordionDetails>
                </Accordion>
              )}
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </Stack>
  );
}

function MarkdownContent({ content, subtle = false }: { content: string; subtle?: boolean }) {
  return (
    <Box
      sx={{
        color: subtle ? "text.secondary" : "text.primary",
        fontSize: subtle ? "0.875rem" : "1rem",
        lineHeight: 1.55,
        overflowWrap: "anywhere",
        "& p": { m: 0, mb: 0.75 },
        "& p:last-child": { mb: 0 },
        "& ul, & ol": { my: 0.75, pl: 2.5 },
        "& li": { mb: 0.25 },
        "& a": { color: "primary.main" },
        "& code": { px: 0.35, py: 0.1, borderRadius: 0.5, bgcolor: "rgba(148, 163, 184, 0.15)", fontSize: "0.9em" },
        "& pre": { m: 0, mt: 0.75, p: 1, overflowX: "auto", borderRadius: 1, bgcolor: "rgba(2, 6, 23, 0.45)" },
        "& pre code": { p: 0, bgcolor: "transparent", whiteSpace: "pre" },
        "& blockquote": { my: 0.75, mx: 0, pl: 1.25, borderLeft: "2px solid", borderColor: "divider", color: "text.secondary" },
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </Box>
  );
}

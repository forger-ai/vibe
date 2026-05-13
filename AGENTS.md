# AGENTS

## Source of Truth

This file is the main functional and operational context source for Vibe agents.

`manifest.json` describes installation, services, MCP, scripts, catalog metadata, and thread-interface agents. It is not the list of user-created coworkers. User-created coworkers live in the Vibe local database.

## Product Identity

- id: `vibe`
- visible name: `Vibe`
- type: local coding-agent workspace
- stack: `vite-fastapi-sqlite`

## Functional Goal

Vibe helps one person coordinate coding coworkers over local Git repositories. It keeps repositories, agents, feature intake, task plans, step assignments, notebooks, chat threads, agent threads, and run history in the app private workspace.

## User-Visible Capabilities

### 1. Manage Coding Coworkers

The user can create and edit agents with long Markdown fields:

- identity;
- tone;
- guardrails;
- provider;
- model;
- model parameters.

These agents are local user data. They are not written into `manifest.json`.

### 2. Start Feature Intake And Free Chat

The user can start a conversation with a coworker through a manifest-declared thread interface. Vibe stores the chat locally and asks Forger Desktop to create or resume the underlying agent thread when the Desktop runtime is available.

### 3. Manage Repositories

The user can register Git repositories by remote URL and default branch. Vibe uses local Git credentials, SSH, HTTPS, or `gh` already configured on the machine. Vibe does not store GitHub tokens in V1.

### 4. Plan Work

The user can create plans that involve one or more repositories. Plans start as drafts, record repository start refs, and use plan-specific checkouts inside the private workspace. Pending programming and review steps are editable, reorderable, and deletable. Running, blocked, and completed steps are not editable. A blocked step is paused for user help; the user can chat with the manifest orchestrator while the plan is paused, then resume the step with concrete unblock guidance.

Programming steps end with one or more recorded commits. Review steps end with a concrete review result and do not require commits unless they change code.

### 5. Keep Notebook Entries

The user and agents can write notebook entries. Notebook entries act as local memory and can be associated with repositories, agents, task types, tasks, or step types.

## Manifest Agent Contract

Vibe uses `manifest.agents[]` for manifest-defined orchestrators and invocation prompts, not as the roster of final user-created agents.

Current orchestrators:

- `freeChatOrchestrator`;
- `featureIntakeOrchestrator`;
- `planChatOrchestrator`.

Current Agent invocation prompts:

- `agentChatTask`;
- `agentChatDiscussion`;
- `agentStepTask`.

Each orchestrator supplies the user-facing chat prompt. Each invocation prompt is combined with a database `Agent` when the orchestrator delegates work.

Each chat is operated by one manifest-defined orchestrator. The orchestrator does not live in the local `Agent` database and is not selected by the user. Local `Agent` records are invokable coworkers selected as the pool available to that chat. The orchestrator owns user-visible replies, durable notebook writes, feature-intake plan creation, plan edits, execution orchestration, discussions, and final plan writing. Invoked Agents do work in their own Desktop threads and return results for the orchestrator to inspect.

## Internal Agent Tools

Vibe exposes an app MCP server. Use MCP for structured writes when an agent needs to:

- add a discussion message;
- write a notebook entry;
- inspect app status.

Do not present MCP, endpoints, paths, scripts, or database tables as user-facing steps unless the user explicitly asks for technical details.

## Boundaries

- Vibe V1 prioritizes the coding-agent core.
- The Databases view is a placeholder registry for future DB Manager tooling.
- Architecture/cloud coworkers are modeled as agents but do not receive special cloud tools in V1.
- Vibe must not read files outside the private app workspace unless the user explicitly shares them.
- Vibe does not store external provider or Git tokens in V1.

## Verification

Use the app `verify` script to run backend and frontend checks. For Dockerized execution, prefer Docker Compose according to the workspace convention.

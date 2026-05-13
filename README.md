# Vibe

Vibe is a local Forger app for coordinating coding coworkers over local Git repositories.

It stores agents, feature intake, free chat, tasks, steps, assignments, notebooks, agent threads, and run history in the app's private SQLite database. Agent execution is delegated to Forger Desktop's agent runtime when the app is installed and opened from Forger.

## Stack

- FastAPI backend
- SQLite local database
- Vite + React frontend
- MUI interface
- HTTP MCP tools for Vibe agents

## Local Development

Use the repository's Docker Compose setup for dependency, runtime, and verification commands when developing in the workspace.

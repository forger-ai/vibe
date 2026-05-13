from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.main import app
from app.mcp_runtime import ToolError
from app.mcp_server import (
    ask_user,
    call_agent,
    create_plan_from_intake,
    create_plan_step,
    create_step_assignment,
    delete_plan,
    delete_plan_step,
    delete_step_assignment,
    draft,
    get_active_draft,
    get_notebook_entry,
    get_plan_detail,
    list_plans,
    list_repositories,
    mark_step_blocked,
    resume_blocked_step,
    run_discussion,
    start_discussion,
    update_plan,
    update_plan_step,
    update_step_assignment,
    write_chat_message,
    write_discussion_message,
)
from app.models import (
    ChatDraft,
    ChatThread,
    CommandExecutionResult,
    CommandStep,
    Plan,
    PlanChatThread,
    PlanRepository,
    ScriptStep,
    Step,
    StepAssignment,
    StepExecution,
    StepExecutionAgentThread,
    StepRepository,
)
from app.services import workspaces


def _step_type_id(client: TestClient, name: str) -> str:
    return next(item["id"] for item in client.get("/api/step-types").json() if item["name"] == name)


def _step_type_by_responsible(client: TestClient, responsible: str) -> dict:
    return next(item for item in client.get("/api/step-types").json() if item["responsible"] == responsible)


def _plan_creation_counts() -> dict[str, int]:
    with Session(engine) as session:
        return {
            "plans": len(session.exec(select(Plan)).all()),
            "plan_chats": len(
                session.exec(
                    select(ChatThread).where(
                        ChatThread.thread_type == "planChatOrchestrator"
                    )
                ).all()
            ),
            "plan_chat_links": len(session.exec(select(PlanChatThread)).all()),
            "plan_repositories": len(session.exec(select(PlanRepository)).all()),
            "steps": len(session.exec(select(Step)).all()),
            "step_repositories": len(session.exec(select(StepRepository)).all()),
            "script_steps": len(session.exec(select(ScriptStep)).all()),
            "command_steps": len(session.exec(select(CommandStep)).all()),
            "step_assignments": len(session.exec(select(StepAssignment)).all()),
        }


def _create_step_worker_thread(
    client: TestClient,
    *,
    plan_id: str,
    step_id: str,
    assignment_id: str,
    agent_id: str,
    title: str = "Step worker",
) -> dict:
    return client.post(
        "/api/agent-threads",
        json={
            "desktop_thread_id": f"desktop-{uuid4()}",
            "agent_id": agent_id,
            "manifest_agent_id": "agentStepTask",
            "title": title,
            "initial_prompt_snapshot_md": title,
            "owner_type": "agent",
            "invocation_mode": "step_task",
            "plan_id": plan_id,
            "step_assignment_id": assignment_id,
        },
    ).json()


def _wait_for_step_status(client: TestClient, plan_id: str, step_id: str, status: str) -> dict:
    deadline = time.monotonic() + 5
    detail: dict = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/api/plans/{plan_id}/detail").json()
        step = next(item for item in detail["steps"] if item["id"] == step_id)
        if step["status"] == status:
            return detail
        time.sleep(0.05)
    return detail


def test_dashboard_seeds_default_agents() -> None:
    with TestClient(app) as client:
        response = client.get("/api/dashboard")
        agents = client.get("/api/agents").json()
        notebook_titles = {entry["title"] for entry in client.get("/api/notebooks").json()}

    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"] >= 5
    names = {agent["name"] for agent in agents}
    assert {"Product", "UX", "Tech Lead", "Programmer", "Reviewer"}.issubset(names)
    assert "Product + UI" not in names
    assert "Task creation guide" in notebook_titles


def test_agents_expose_reasoning_effort() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        response = client.patch(
            f"/api/agents/{agent['id']}",
            json={"reasoning_effort": "xhigh"},
        )

    assert response.status_code == 200
    assert response.json()["reasoning_effort"] == "xhigh"


def test_agents_expose_context_task_fields() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        response = client.patch(
            f"/api/agents/{agent['id']}",
            json={"plan_task_md": "Review and improve the plan."},
        )

    assert response.status_code == 200
    assert response.json()["plan_task_md"] == "Review and improve the plan."


def test_create_plan_step_and_assignment() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()
        plan = client.post(
            "/api/plans",
            json={"name": "Implement command palette", "description": "Add a first pass."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Build shell",
                "description": "Create the command palette surface.",
                "step_type_id": _step_type_id(client, "Programming"),
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={
                "step_id": step["id"],
                "agent_id": agents[0]["id"],
                "instructions_md": "Implement the visible shell.",
            },
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    assert assignment.status_code == 200
    assert len(detail["steps"]) == 1
    assert len(detail["assignments"]) == 1
    assert detail["plan"]["id"] == plan["id"]


def test_step_creation_requires_step_type_and_rejects_legacy_kind() -> None:
    with TestClient(app) as client:
        plan = client.post(
            "/api/plans",
            json={"name": "Typed only", "description": "Reject legacy fields."},
        ).json()
        missing_type = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={"plan_id": plan["id"], "name": "Missing", "description": "No type."},
        )
        legacy_kind = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Legacy",
                "description": "Old field.",
                "step_type_id": _step_type_id(client, "Review"),
                "kind": "review",
            },
        )

    assert missing_type.status_code == 422
    assert legacy_kind.status_code == 422


def test_plan_can_have_multiple_chats() -> None:
    with TestClient(app) as client:
        plan = client.post(
            "/api/plans",
            json={"name": "Multi chat plan", "description": "Discuss in separate chats."},
        ).json()
        first = client.post(f"/api/plans/{plan['id']}/chats")
        second = client.post(f"/api/plans/{plan['id']}/chats")
        listed = client.get(f"/api/plans/{plan['id']}/chats").json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(listed) == 2
    assert {first.json()["id"], second.json()["id"]} == {item["id"] for item in listed}


def test_chat_message_create_is_idempotent_for_desktop_message() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "freeChatOrchestrator", "title": "Chat"}).json()
        body = {
            "chat_thread_id": chat["id"],
            "role": "assistant",
            "source_type": "orchestrator",
            "source_id": "thread-1",
            "content_md": "Same desktop message.",
            "metadata_json": {"desktop_message_id": "desktop-message-1"},
        }
        first = client.post("/api/chat/messages", json=body)
        second = client.post("/api/chat/messages", json=body)
        messages = client.get(f"/api/chat/threads/{chat['id']}/messages").json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len([item for item in messages if item["metadata_json"].get("desktop_message_id") == "desktop-message-1"]) == 1


def test_build_prompt_uses_agent_and_interface() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        response = client.post(
            "/api/agents/prompt",
            json={
                "agent_id": agent["id"],
                "manifest_agent_id": "agentChatDiscussion",
                "context": {
                    "discussion_id": "discussion-123",
                    "discussion_objective": "Add plan graph editing",
                    "discussion_messages": "No previous messages.",
                },
            },
        )

    assert response.status_code == 200
    assert "Add plan graph editing" in response.json()["prompt"]
    assert agent["id"] in response.json()["prompt"]
    assert "# Identity" in response.json()["prompt"]
    assert "write_discussion_message" in response.json()["prompt"]
    assert "respond_to_user" not in response.json()["prompt"]
    assert "propagate" not in response.json()["prompt"]


def test_plan_prompt_requires_clear_assignment_instructions() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        response = client.post(
            "/api/agents/prompt",
            json={
                "agent_id": agent["id"],
                "manifest_agent_id": "agentStepTask",
                "context": {
                    "plan_id": "plan-123",
                    "plan": {
                        "id": "plan-123",
                        "description": "Plan id: plan-123",
                        "steps": "step_id=step-123; step_type=Programming; status=pending",
                        "assignments": (
                            "assignment_id=assignment-123; step_id=step-123; "
                            "agent_id=agent-123; instructions_md=Do the work."
                        ),
                    },
                    "assignment": {"instructions": "instructions_md=Do the work."},
                },
            },
        )

    prompt = response.json()["prompt"]
    assert response.status_code == 200
    assert "assigned to plan step work" in prompt
    assert "Do the work." in prompt


def test_build_prompt_uses_manifest_template_and_notebook_context() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        plan = client.post(
            "/api/plans",
            json={"name": "Notebook plan", "description": "Use memory."},
        ).json()
        client.post(
            "/api/notebooks",
            json={
                "title": "Agent preference",
                "short_description": "Use concise answers.",
                "long_description_md": "The user prefers concise implementation plans.",
                "entry_type": "prompt",
                "load_policy": "always",
                "scope_type": "agent",
                "scope_id": agent["id"],
            },
        )
        client.post(
            "/api/notebooks",
            json={
                "title": "Plan risk",
                "short_description": "Check migrations.",
                "long_description_md": "Long plan risk should not be loaded.",
                "entry_type": "log",
                "load_policy": "retrieval",
                "read_when": "Read when editing migration steps.",
                "scope_type": "plan",
                "scope_id": plan["id"],
            },
        )
        response = client.post(
            "/api/agents/prompt",
            json={
                "agent_id": agent["id"],
                "manifest_agent_id": "plan-agent",
                "manifest_prompt_template": (
                    "# Identity\n{{agent.identity}}\n\n"
                    "# Notebook\n{{notebooks.agent}}\n\n{{notebooks.plan}}\n\n"
                    "# Context\n{{plan.description}}"
                ),
                "context": {
                    "plan_id": plan["id"],
                    "plan": {"id": plan["id"], "description": "Notebook plan context"},
                },
            },
        )

    prompt = response.json()["prompt"]
    assert response.status_code == 200
    assert "The user prefers concise implementation plans." in prompt
    assert "Slug:" in prompt
    assert "Plan risk" in prompt
    assert "slug:" in prompt
    assert "Read when editing migration steps." in prompt
    assert "Long plan risk should not be loaded." not in prompt
    assert "Notebook plan context" in prompt


def test_mcp_get_notebook_entry_by_id_or_slug() -> None:
    with TestClient(app) as client:
        entry = client.post(
            "/api/notebooks",
            json={
                "title": "User style preference",
                "short_description": "Use compact plans.",
                "long_description_md": "The user prefers compact, actionable plans.",
                "entry_type": "preference",
                "load_policy": "retrieval",
                "read_when": "Read before drafting implementation plans.",
            },
        ).json()

        by_id = get_notebook_entry({"identifier": entry["id"]})
        slug = by_id["entry"]["slug"]
        by_slug = get_notebook_entry({"identifier": slug})

    assert by_id["success"] is True
    assert by_id["entry"]["title"] == "User style preference"
    assert by_slug["entry"]["id"] == entry["id"]
    assert by_slug["entry"]["long_description_md"] == "The user prefers compact, actionable plans."


def test_mcp_draft_mode_requires_orchestrator_and_batches_questions() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Draft"}).json()

        with pytest.raises(ToolError) as forbidden_draft:
            draft({"chat_thread_id": chat["id"], "agent_id": "agent-123", "description_md": "Plan it."})
        with pytest.raises(ToolError) as forbidden_questions:
            ask_user(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": "agent-123",
                    "questions": [{"question": "Choose", "options": [{"label": "A"}]}],
                }
            )
        with pytest.raises(ToolError) as too_many_questions:
            ask_user(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": "manifest-orchestrator",
                    "questions": [{"question": f"Q{i}", "options": [{"label": "A"}]} for i in range(5)],
                }
            )
        with pytest.raises(ToolError) as too_many_options:
            ask_user(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": "manifest-orchestrator",
                    "questions": [
                        {
                            "question": "Choose",
                            "options": [{"label": "A"}, {"label": "B"}, {"label": "C"}, {"label": "D"}],
                        }
                    ],
                }
            )
        first = ask_user(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "questions": [{"question": f"Q{i}", "options": [{"label": "A"}]} for i in range(4)],
            }
        )
        second = ask_user(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "questions": [{"question": "Q4", "options": [{"label": "B"}]}],
            }
        )
        created = draft({"chat_thread_id": chat["id"], "agent_id": "manifest-orchestrator", "description_md": "Implement this."})
        state = get_active_draft({"chat_thread_id": chat["id"]})

    assert forbidden_draft.value.code == "forbidden"
    assert forbidden_questions.value.code == "forbidden"
    assert too_many_questions.value.code == "invalid_input"
    assert too_many_options.value.code == "invalid_input"
    assert len(first["questions"]) == 4
    assert len(second["questions"]) == 1
    assert created["draft"]["status"] == "active"
    assert state["draft"]["id"] == created["draft"]["id"]
    assert state["questions"] == []


def test_mcp_call_agent_rejects_non_orchestrator_before_runtime() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Call"}).json()
        agent = client.get("/api/agents").json()[0]

    with pytest.raises(ToolError) as error:
        call_agent(
            {
                "chat_thread_id": chat["id"],
                "agent_id": agent["id"],
                "orchestrator_agent_id": agent["id"],
                "instructions_md": "Review this.",
            }
        )

    assert error.value.code == "forbidden"


def test_mcp_orchestration_rejects_active_draft_gate_before_runtime() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Gate"}).json()
        agents = client.get("/api/agents").json()[:2]
        agent = agents[0]
        draft({"chat_thread_id": chat["id"], "agent_id": "manifest-orchestrator", "description_md": "Review this first."})

    with pytest.raises(ToolError) as call_error:
        call_agent(
            {
                "chat_thread_id": chat["id"],
                "agent_id": agent["id"],
                "orchestrator_agent_id": "manifest-orchestrator",
                "instructions_md": "Review this.",
            }
        )
    with pytest.raises(ToolError) as discussion_error:
        run_discussion(
            {
                "chat_thread_id": chat["id"],
                "orchestrator_agent_id": "manifest-orchestrator",
                "objective_md": "Discuss this.",
                "agent_ids": [item["id"] for item in agents],
            }
        )

    assert call_error.value.code == "draft_gate_active"
    assert discussion_error.value.code == "draft_gate_active"


def test_chat_agent_thread_can_exist_before_agent_thread() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Chat"}).json()
        participant = client.put(
            f"/api/chat/threads/{chat['id']}/agents/{agent['id']}",
            json={"agent_id": agent["id"], "enabled": True},
        )
        listed = client.get(f"/api/chat/threads/{chat['id']}/agents").json()

    assert participant.status_code == 200
    assert "agent_thread_id" not in participant.json()
    assert listed[0]["agent_id"] == agent["id"]


def test_mcp_lists_configured_repositories() -> None:
    with TestClient(app) as client:
        repository = client.post(
            "/api/repositories",
            json={
                "name": "Forger Cloud",
                "remote_url": "git@github.com:forger-ai/forger-backend.git",
                "default_branch": "main",
            },
        ).json()
        result = list_repositories({})

    assert result["success"] is True
    assert any(item["id"] == repository["id"] for item in result["repositories"])


def test_git_commands_run_without_interactive_prompts(monkeypatch, tmp_path) -> None:
    captured: dict[str, str] = {}

    def fake_run(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs["env"])

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setattr(workspaces.subprocess, "run", fake_run)

    workspaces._run_git(["status"], tmp_path)

    assert captured["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in captured["GIT_SSH_COMMAND"]


def test_git_command_failure_writes_diagnostic_log(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "git-sync.jsonl"

    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        class Completed:
            returncode = 128
            stdout = ""
            stderr = "fatal: could not read from remote repository"

        return Completed()

    monkeypatch.setenv("VIBE_GIT_SYNC_LOG", str(log_path))
    monkeypatch.setattr(workspaces.subprocess, "run", fake_run)

    with pytest.raises(workspaces.GitWorkspaceError):
        workspaces._run_git(
            [
                "clone",
                "https://user:secret@example.com/repo.git",
                str(tmp_path / "repo"),
            ],
            tmp_path,
        )

    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert events[-1]["event"] == "git_command_failed"
    assert events[-1]["returncode"] == 128
    assert events[-1]["stderr"] == "fatal: could not read from remote repository"
    assert events[-1]["args"][1] == "https://***:***@example.com/repo.git"


def test_git_command_timeout_writes_diagnostic_log(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "git-sync.jsonl"

    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(
            ["git", "fetch"],
            timeout=120,
            output="partial",
            stderr="still waiting",
        )

    monkeypatch.setenv("VIBE_GIT_SYNC_LOG", str(log_path))
    monkeypatch.setattr(workspaces.subprocess, "run", fake_run)

    with pytest.raises(workspaces.GitWorkspaceError, match="timed out"):
        workspaces._run_git(["fetch", "--all", "--prune"], tmp_path)

    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert events[-1]["event"] == "git_command_timeout"
    assert events[-1]["timeout_seconds"] == 120
    assert events[-1]["stdout"] == "partial"
    assert events[-1]["stderr"] == "still waiting"


def test_sync_repository_timeout_returns_client_error(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "git-sync.jsonl"

    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(
            ["git", "clone"],
            timeout=120,
            output="partial",
            stderr="still waiting",
        )

    monkeypatch.setenv("VIBE_GIT_SYNC_LOG", str(log_path))
    monkeypatch.setattr(workspaces.subprocess, "run", fake_run)

    with TestClient(app) as client:
        repository = client.post(
            "/api/repositories",
            json={
                "name": "Timeout repo",
                "remote_url": "git@example.com:timeout.git",
                "default_branch": "main",
            },
        ).json()
        response = client.post(f"/api/repositories/{repository['id']}/sync")

    assert response.status_code == 400
    assert "timed out" in response.json()["detail"]
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [event["event"] for event in events] == [
        "repository_sync_start",
        "git_command_timeout",
        "repository_sync_failed",
    ]


def test_chat_selects_invokable_agents_without_orchestrator_agent_record() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()[:2]
        chat = client.post("/api/chat/threads", json={"thread_type": "featureIntakeOrchestrator", "title": "Intake"}).json()
        for agent in agents:
            client.put(
                f"/api/chat/threads/{chat['id']}/agents/{agent['id']}",
                json={"agent_id": agent["id"], "enabled": True},
            )
        listed = client.get(f"/api/chat/threads/{chat['id']}/agents").json()

    assert {item["agent_id"] for item in listed} == {agent["id"] for agent in agents}
    assert all("role" not in item for item in listed)


def test_discussion_advances_in_deterministic_order() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()[:3]
        chat = client.post("/api/chat/threads", json={"thread_type": "freeChatOrchestrator", "title": "Discuss"}).json()
        started = start_discussion(
            {
                "chat_thread_id": chat["id"],
                "title": "Architecture discussion",
                "objective_md": "Choose the safest implementation.",
                "agent_ids": [agent["id"] for agent in agents],
            }
        )
        after_a = write_discussion_message(
            {
                "discussion_id": started["discussion"]["id"],
                "agent_id": agents[0]["id"],
                "content_md": "A says use the simple path.",
                "end_discussion": False,
            }
        )
        after_b = write_discussion_message(
            {
                "discussion_id": started["discussion"]["id"],
                "agent_id": agents[1]["id"],
                "content_md": "B has no more concerns.",
                "end_discussion": True,
            }
        )
        after_c = write_discussion_message(
            {
                "discussion_id": started["discussion"]["id"],
                "agent_id": agents[2]["id"],
                "content_md": "C has no more concerns.",
                "end_discussion": True,
            }
        )

    assert started["next_agent_id"] == agents[0]["id"]
    assert after_a["next_agent_id"] == agents[1]["id"]
    assert after_b["next_agent_id"] == agents[2]["id"]
    assert after_c["next_agent_id"] == agents[0]["id"]
    assert after_c["discussion"]["current_round"] == 1


def test_progress_event_dedupes() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Progress"}).json()
        payload = {
            "chat_thread_id": chat["id"],
            "agent_id": agent["id"],
            "agent_thread_id": None,
            "desktop_run_id": "run-1",
            "source_message_id": "message-1",
            "event_type": "run.progress",
            "content_md": "The agent is thinking.",
        }
        first = client.post("/api/chat/progress", json=payload)
        second = client.post("/api/chat/progress", json=payload)
        listed = client.get(f"/api/chat/threads/{chat['id']}/progress").json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(listed) == 1


def test_write_chat_message_cannot_create_visible_agent_response() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Internal"}).json()
        try:
            write_chat_message(
                {
                    "chat_thread_id": chat["id"],
                    "role": "assistant",
                    "content_md": "This should not become visible.",
                }
            )
            denied = False
        except ToolError as error:
            denied = error.code == "visible_chat_forbidden"

    assert denied is True


def test_chat_messages_hide_internal_messages() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Internal"}).json()
        internal = client.post(
            "/api/chat/messages",
            json={
                "chat_thread_id": chat["id"],
                "role": "system",
                "source_type": "system",
                "content_md": "Internal thought.",
                "visibility": "internal",
            },
        )
        visible = client.post(
            "/api/chat/messages",
            json={
                "chat_thread_id": chat["id"],
                "role": "user",
                "source_type": "user",
                "content_md": "Visible user message.",
            },
        )
        messages = client.get(f"/api/chat/threads/{chat['id']}/messages").json()

    assert internal.status_code == 200
    assert visible.status_code == 200
    assert [item["content_md"] for item in messages] == ["Visible user message."]


def test_create_chat_message_returns_id_after_thread_link() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Ids"}).json()
        created = client.post(
            "/api/chat/messages",
            json={
                "chat_thread_id": chat["id"],
                "role": "user",
                "source_type": "user",
                "content_md": "First message with an id.",
            },
        )

    assert created.status_code == 200
    assert created.json()["id"]


def test_chat_debug_events_are_written_to_file(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "chat-debug.jsonl"
    monkeypatch.setenv("VIBE_CHAT_DEBUG_LOG", str(log_path))
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "free-chat-agent", "title": "Debug"}).json()
        created = client.post(
            "/api/chat/debug-log",
            json={
                "chat_thread_id": chat["id"],
                "event_type": "send.start",
                "message": "Started send",
                "metadata_json": {"messageLength": 12},
            },
        )

    assert created.status_code == 200
    assert created.json()["path"] == str(log_path)
    content = log_path.read_text()
    assert '"event_type": "send.start"' in content
    assert '"messageLength": 12' in content


def test_create_plan_from_intake_uses_orchestrator_authority() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()[:2]
        programming_type_id = _step_type_id(client, "Programming")
        chat = client.post("/api/chat/threads", json={"thread_type": "featureIntakeOrchestrator", "title": "Build"}).json()
        client.put(
            f"/api/chat/threads/{chat['id']}/agents/{agents[0]['id']}",
            json={"agent_id": agents[0]["id"], "enabled": True},
        )
        client.put(
            f"/api/chat/threads/{chat['id']}/agents/{agents[1]['id']}",
            json={"agent_id": agents[1]["id"], "enabled": True},
        )
        created_draft = draft(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "description_md": "Plan the work.",
            }
        )
        client.patch(f"/api/chat/drafts/{created_draft['draft']['id']}", json={"status": "accepted"})
        result = create_plan_from_intake(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "name": "Draft plan",
                "description": "Plan the work.",
                "steps": [
                    {
                        "name": "Scope",
                        "description": "Clarify scope.",
                        "step_type_id": programming_type_id,
                        "assignments": [
                            {"agent_id": agents[1]["id"], "instructions_md": "Advise on implementation."}
                        ],
                    }
                ],
            }
        )

    assert result["success"] is True
    assert result["plan_id"]
    assert result["chat_thread_id"]
    assert len(result["step_ids"]) == 1
    assert get_active_draft({"chat_thread_id": chat["id"]})["draft"] is None


def test_create_plan_from_intake_rolls_back_invalid_command_step() -> None:
    with TestClient(app) as client:
        command_type = _step_type_by_responsible(client, "command")
        chat = client.post(
            "/api/chat/threads",
            json={"thread_type": "featureIntakeOrchestrator", "title": "Build"},
        ).json()
        repository = client.post(
            "/api/repositories",
            json={
                "name": "Atomic repo",
                "remote_url": "git@example.com:forger/atomic.git",
                "default_branch": "main",
            },
        ).json()
        created_draft = draft(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "description_md": "Plan the work.",
            }
        )
        client.patch(
            f"/api/chat/drafts/{created_draft['draft']['id']}",
            json={"status": "accepted"},
        )
        before_counts = _plan_creation_counts()

        with pytest.raises(ToolError) as error:
            create_plan_from_intake(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": "manifest-orchestrator",
                    "name": "Atomic invalid plan",
                    "description": "Should not persist.",
                    "repositories": [
                        {"repository_id": repository["id"], "start_ref": "main"}
                    ],
                    "steps": [
                        {
                            "name": "Checkout",
                            "description": "Checkout branch.",
                            "step_type_id": command_type["id"],
                            "repository_ids": [repository["id"]],
                        }
                    ],
                }
            )
        after_counts = _plan_creation_counts()
        active_draft = get_active_draft({"chat_thread_id": chat["id"]})["draft"]

    assert error.value.code == "invalid_input"
    assert str(error.value) == "command steps require a command"
    assert after_counts == before_counts
    assert active_draft["id"] == created_draft["draft"]["id"]
    assert active_draft["status"] == "accepted"


def test_create_plan_from_intake_creates_command_step_atomically() -> None:
    with TestClient(app) as client:
        command_type = _step_type_by_responsible(client, "command")
        chat = client.post(
            "/api/chat/threads",
            json={"thread_type": "featureIntakeOrchestrator", "title": "Build"},
        ).json()
        repository = client.post(
            "/api/repositories",
            json={
                "name": "Atomic command repo",
                "remote_url": "git@example.com:forger/command.git",
                "default_branch": "main",
            },
        ).json()
        created_draft = draft(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "description_md": "Plan the work.",
            }
        )
        client.patch(
            f"/api/chat/drafts/{created_draft['draft']['id']}",
            json={"status": "accepted"},
        )
        result = create_plan_from_intake(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "name": "Atomic command plan",
                "description": "Persist a valid command step.",
                "repositories": [
                    {"repository_id": repository["id"], "start_ref": "main"}
                ],
                "steps": [
                    {
                        "name": "Checkout",
                        "description": "Checkout branch.",
                        "step_type_id": command_type["id"],
                        "repository_ids": [repository["id"]],
                        "command_text": "git status --short",
                    }
                ],
            }
        )
        detail = get_plan_detail({"plan_id": result["plan_id"]})
        active_draft = get_active_draft({"chat_thread_id": chat["id"]})["draft"]
        with Session(engine) as session:
            draft_record = session.get(ChatDraft, created_draft["draft"]["id"])

    assert result["success"] is True
    assert len(result["step_ids"]) == 1
    assert detail["command_steps"][0]["command_text"] == "git status --short"
    assert active_draft is None
    assert draft_record is not None
    assert draft_record.status == "implemented"


def test_create_plan_from_intake_requires_manifest_orchestrator_and_accepted_draft() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        programming_type_id = _step_type_id(client, "Programming")
        chat = client.post("/api/chat/threads", json={"thread_type": "featureIntakeOrchestrator", "title": "Build"}).json()

        with pytest.raises(ToolError) as missing_draft:
            create_plan_from_intake(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": "manifest-orchestrator",
                    "name": "Draft plan",
                    "description": "Plan the work.",
                    "steps": [{"name": "Build", "description": "Do work.", "step_type_id": programming_type_id}],
                }
            )
        created_draft = draft(
            {
                "chat_thread_id": chat["id"],
                "agent_id": "manifest-orchestrator",
                "description_md": "Plan the work.",
            }
        )
        client.patch(f"/api/chat/drafts/{created_draft['draft']['id']}", json={"status": "accepted"})
        with pytest.raises(ToolError) as wrong_agent:
            create_plan_from_intake(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": agent["id"],
                    "name": "Draft plan",
                    "description": "Plan the work.",
                    "steps": [{"name": "Build", "description": "Do work.", "step_type_id": programming_type_id}],
                }
            )

    assert missing_draft.value.code == "draft_not_accepted"
    assert wrong_agent.value.code == "forbidden"


def test_mcp_plan_creation_requires_step_type_and_rejects_kind() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        chat = client.post("/api/chat/threads", json={"thread_type": "featureIntakeOrchestrator", "title": "Build"}).json()
        client.put(
            f"/api/chat/threads/{chat['id']}/agents/{agent['id']}",
            json={"agent_id": agent["id"], "enabled": True},
        )
        try:
            create_plan_from_intake(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": agent["id"],
                    "name": "Missing type",
                    "description": "Plan the work.",
                    "steps": [{"name": "Build", "description": "Do work."}],
                }
            )
            missing_type_denied = False
        except ToolError:
            missing_type_denied = True
        try:
            create_plan_from_intake(
                {
                    "chat_thread_id": chat["id"],
                    "agent_id": agent["id"],
                    "name": "Legacy kind",
                    "description": "Plan the work.",
                    "steps": [
                        {
                            "name": "Build",
                            "description": "Do work.",
                            "step_type_id": _step_type_id(client, "Programming"),
                            "kind": "programming",
                        }
                    ],
                }
            )
            kind_denied = False
        except ToolError:
            kind_denied = True

    assert missing_type_denied is True
    assert kind_denied is True


def test_delete_plan_removes_plan_detail() -> None:
    with TestClient(app) as client:
        plan = client.post(
            "/api/plans",
            json={"name": "Delete me", "description": "Temporary plan."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Implement",
                "description": "Do the work.",
                "step_type_id": _step_type_id(client, "Programming"),
            },
        ).json()
        agent = client.get("/api/agents").json()[0]
        client.post(
            "/api/plans/assignments",
            json={"step_id": step["id"], "agent_id": agent["id"], "instructions_md": "Implement it."},
        )
        chat = client.post(f"/api/plans/{plan['id']}/chats", json={}).json()
        client.post(
            "/api/chat/messages",
            json={
                "chat_thread_id": chat["id"],
                "role": "user",
                "source_type": "user",
                "content_md": "hello",
            },
        )

        deleted = client.delete(f"/api/plans/{plan['id']}")
        plans = client.get("/api/plans").json()
        detail = client.get(f"/api/plans/{plan['id']}/detail")
        threads = client.get("/api/chat/threads").json()

    assert deleted.status_code == 204
    assert plan["id"] not in {item["id"] for item in plans}
    assert detail.status_code == 404
    assert chat["id"] not in {item["id"] for item in threads}


def test_mcp_update_and_delete_plan() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        plan = client.post(
            "/api/plans",
            json={"name": "MCP editable", "description": "Before"},
        ).json()
        updated = update_plan(
            {
                "plan_id": plan["id"],
                "agent_id": agent["id"],
                "name": "MCP edited",
                "description": "After",
                "context_md": "Updated context.",
                "status": "active",
            }
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()
        try:
            delete_plan({"plan_id": plan["id"], "agent_id": agent["id"], "confirm_delete": False})
            denied = False
        except ToolError:
            denied = True
        deleted = delete_plan({"plan_id": plan["id"], "agent_id": agent["id"], "confirm_delete": True})
        missing = client.get(f"/api/plans/{plan['id']}/detail")

    assert updated["success"] is True
    assert updated["plan"]["name"] == "MCP edited"
    assert detail["plan"]["description"] == "After"
    assert detail["plan"]["context_md"] == "Updated context."
    assert detail["plan"]["status"] == "active"
    assert denied is True
    assert deleted == {"success": True, "plan_id": plan["id"]}
    assert missing.status_code == 404


def test_plan_execution_records_review_and_programming_commits() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        repository = client.post(
            "/api/repositories",
            json={
                "name": "Execution repo",
                "remote_url": "git@example.com:execution.git",
                "default_branch": "develop",
            },
        ).json()
        plan = client.post(
            "/api/plans",
            json={
                "name": "Execution plan",
                "description": "Run gated steps.",
                "execution_mode": "parallel",
            },
        ).json()
        selected = client.put(
            f"/api/plans/{plan['id']}/repositories",
            json={"repositories": [{"repository_id": repository["id"], "start_ref": "develop"}]},
        )
        programming = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Implement",
                "description": "Change code.",
                "step_type_id": _step_type_id(client, "Programming"),
                "repository_ids": [repository["id"]],
            },
        ).json()
        review = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Review",
                "description": "Review code.",
                "step_type_id": _step_type_id(client, "Review"),
                "depends_on_step_ids": [programming["id"]],
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": programming["id"], "agent_id": agent["id"], "instructions_md": "Implement code."},
        ).json()
        worker_thread = client.post(
            "/api/agent-threads",
            json={
                "desktop_thread_id": f"desktop-{uuid4()}",
                "agent_id": agent["id"],
                "manifest_agent_id": "agentStepTask",
                "title": "Implement",
                "initial_prompt_snapshot_md": "Implement code.",
                "owner_type": "agent",
                "invocation_mode": "step_task",
                "plan_id": plan["id"],
                "step_assignment_id": assignment["id"],
            },
        ).json()
        update_plan({"plan_id": plan["id"], "agent_id": agent["id"], "status": "approved"})
        started = client.post(
            f"/api/plans/{plan['id']}/start-steps",
            json={"step_ids": [programming["id"]], "worker_agent_thread_ids_by_step_id": {programming["id"]: [worker_thread["id"]]}},
        )
        execution = started.json()["executions"][0]
        missing_commit = client.post(
            f"/api/plans/executions/{execution['id']}/complete",
            json={"result_md": "Done.", "commits": []},
        )
        completed = client.post(
            f"/api/plans/executions/{execution['id']}/complete",
            json={
                "result_md": "Done.",
                "commits": [
                    {
                        "repository_id": repository["id"],
                        "commit_sha": "abc123",
                        "commit_message": "Implement step",
                    }
                ],
            },
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()
        edit_completed = client.patch(
            f"/api/plans/{plan['id']}/steps/{programming['id']}",
            json={"name": "Cannot edit"},
        )

    assert selected.status_code == 200
    assert started.status_code == 200
    assert missing_commit.status_code == 400
    assert completed.status_code == 200
    assert programming["id"] not in detail["eligible_step_ids"]
    assert review["id"] in detail["eligible_step_ids"]
    assert detail["commits"][0]["commit_sha"] == "abc123"
    assert edit_completed.status_code == 400


def test_plan_advance_approves_and_runs_parallel_ready_level() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        agent_type = client.post(
            "/api/step-types",
            json={"name": f"Agent task {uuid4().hex[:6]}", "responsible": "agent", "git_work": False},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Advance parallel", "description": "Run first level."},
        ).json()
        first = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "First",
                "description": "Run first.",
                "step_type_id": agent_type["id"],
            },
        ).json()
        second = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Second",
                "description": "Run second.",
                "step_type_id": agent_type["id"],
            },
        ).json()
        after = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "After",
                "description": "Run after.",
                "step_type_id": agent_type["id"],
                "depends_on_step_ids": [first["id"], second["id"]],
            },
        ).json()
        assignments = {}
        threads = {}
        for step in [first, second, after]:
            assignments[step["id"]] = client.post(
                "/api/plans/assignments",
                json={"step_id": step["id"], "agent_id": agent["id"], "instructions_md": f"Work on {step['name']}."},
            ).json()
            threads[step["id"]] = client.post(
                "/api/agent-threads",
                json={
                    "desktop_thread_id": f"desktop-{uuid4()}",
                    "agent_id": agent["id"],
                    "manifest_agent_id": "agentStepTask",
                    "title": step["name"],
                    "initial_prompt_snapshot_md": "Do the work.",
                    "owner_type": "agent",
                    "invocation_mode": "step_task",
                    "plan_id": plan["id"],
                    "step_assignment_id": assignments[step["id"]]["id"],
                },
            ).json()
        advanced = client.post(
            f"/api/plans/{plan['id']}/advance",
            json={"worker_agent_thread_ids_by_step_id": {
                first["id"]: [threads[first["id"]]["id"]],
                second["id"]: [threads[second["id"]]["id"]],
                after["id"]: [threads[after["id"]]["id"]],
            }},
        )
        first_executions = advanced.json()["executions"]
        for execution in first_executions:
            client.post(
                f"/api/plans/executions/{execution['id']}/complete",
                json={"result_md": "Done.", "commits": []},
            )
        advanced_after = client.post(
            f"/api/plans/{plan['id']}/advance",
            json={"worker_agent_thread_ids_by_step_id": {
                after["id"]: [threads[after["id"]]["id"]],
            }},
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    assert advanced.status_code == 200
    assert {execution["step_id"] for execution in first_executions} == {first["id"], second["id"]}
    assert advanced.json()["stop_reason"] == "running"
    assert advanced_after.status_code == 200
    assert {execution["step_id"] for execution in advanced_after.json()["executions"]} == {after["id"]}
    assert detail["plan"]["status"] == "running"
    assert next(step for step in detail["steps"] if step["id"] == after["id"])["status"] == "running"


def test_plan_advance_stops_at_human_step() -> None:
    with TestClient(app) as client:
        human_type = client.post(
            "/api/step-types",
            json={"name": f"Human approval {uuid4().hex[:6]}", "responsible": "human", "git_work": False},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Human stop", "description": "Stop for user."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Approve",
                "description": "Needs user approval.",
                "step_type_id": human_type["id"],
            },
        ).json()
        advanced = client.post(f"/api/plans/{plan['id']}/advance")
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    assert advanced.status_code == 200
    assert advanced.json()["stop_reason"] == "needs_human"
    assert advanced.json()["human_step_ids"] == [step["id"]]
    assert detail["plan"]["status"] == "awaiting_review"
    assert detail["steps"][0]["status"] == "pending"


def test_complete_human_step_finishes_plan() -> None:
    with TestClient(app) as client:
        human_type = client.post(
            "/api/step-types",
            json={"name": f"Human approval {uuid4().hex[:6]}", "responsible": "human", "git_work": False},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Human complete", "description": "Finish after user approval."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Approve",
                "description": "Needs user approval.",
                "step_type_id": human_type["id"],
            },
        ).json()
        client.post(f"/api/plans/{plan['id']}/advance")
        completed = client.post(
            f"/api/plans/{plan['id']}/steps/{step['id']}/complete-human",
            json={"result_md": "Approved by user."},
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    assert completed.status_code == 200
    assert completed.json()["execution"]["status"] == "completed"
    assert completed.json()["execution"]["result_md"] == "Approved by user."
    assert detail["plan"]["status"] == "completed"
    assert detail["steps"][0]["status"] == "completed"
    assert detail["steps"][0]["result_md"] == "Approved by user."
    assert detail["executions"][0]["step_id"] == step["id"]


def test_complete_human_step_unlocks_dependent_step() -> None:
    with TestClient(app) as client:
        human_type = client.post(
            "/api/step-types",
            json={"name": f"Human gate {uuid4().hex[:6]}", "responsible": "human", "git_work": False},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Human dependency", "description": "Unlock next work."},
        ).json()
        first = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Approve",
                "description": "Needs user approval.",
                "step_type_id": human_type["id"],
            },
        ).json()
        second = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Review after approval",
                "description": "Run after approval.",
                "step_type_id": _step_type_id(client, "Review"),
                "depends_on_step_ids": [first["id"]],
            },
        ).json()
        client.post(f"/api/plans/{plan['id']}/advance")
        completed = client.post(
            f"/api/plans/{plan['id']}/steps/{first['id']}/complete-human",
            json={},
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    assert completed.status_code == 200
    assert detail["plan"]["status"] == "awaiting_review"
    assert first["id"] not in detail["eligible_step_ids"]
    assert second["id"] in detail["eligible_step_ids"]
    assert next(item for item in detail["steps"] if item["id"] == first["id"])["result_md"] == "Human review completed."


def test_complete_human_step_rejects_invalid_steps() -> None:
    with TestClient(app) as client:
        human_type = client.post(
            "/api/step-types",
            json={"name": f"Human invalid {uuid4().hex[:6]}", "responsible": "human", "git_work": False},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Human invalid", "description": "Reject invalid completions."},
        ).json()
        human_step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Approve",
                "description": "Needs user approval.",
                "step_type_id": human_type["id"],
            },
        ).json()
        blocked_human_step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Later approve",
                "description": "Not eligible yet.",
                "step_type_id": human_type["id"],
                "depends_on_step_ids": [human_step["id"]],
            },
        ).json()
        review_step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Agent review",
                "description": "Not human.",
                "step_type_id": _step_type_id(client, "Review"),
            },
        ).json()
        not_human = client.post(
            f"/api/plans/{plan['id']}/steps/{review_step['id']}/complete-human",
            json={},
        )
        not_eligible = client.post(
            f"/api/plans/{plan['id']}/steps/{blocked_human_step['id']}/complete-human",
            json={},
        )
        first_complete = client.post(
            f"/api/plans/{plan['id']}/steps/{human_step['id']}/complete-human",
            json={},
        )
        not_pending = client.post(
            f"/api/plans/{plan['id']}/steps/{human_step['id']}/complete-human",
            json={},
        )

    assert not_human.status_code == 400
    assert not_eligible.status_code == 400
    assert first_complete.status_code == 200
    assert not_pending.status_code == 400


def test_plan_advance_creates_backend_worker_run_for_agent_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import agent_runtime

    thread_id = f"desktop-thread-{uuid4()}"
    run_id = f"desktop-run-{uuid4()}"

    def create_agent_thread(**_kwargs: object) -> dict:
        return {"desktop_thread_id": thread_id, "status": "idle"}

    def start_agent_run(**_kwargs: object) -> dict:
        return {"desktop_run_id": run_id, "status": "queued"}

    monkeypatch.setattr(agent_runtime, "desktop_create_agent_thread", create_agent_thread)
    monkeypatch.setattr(agent_runtime, "desktop_start_agent_run", start_agent_run)

    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        plan = client.post(
            "/api/plans",
            json={"name": "Agent workers", "description": "Needs worker thread."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Implement",
                "description": "Agent work.",
                "step_type_id": _step_type_id(client, "Programming"),
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": step["id"], "agent_id": agent["id"], "instructions_md": "Do the work."},
        ).json()
        advanced = client.post(f"/api/plans/{plan['id']}/advance")
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()
        stored_thread = next(item for item in detail["agent_threads"] if item["desktop_thread_id"] == thread_id)
        stored_run = next(item for item in detail["agent_runs"] if item["desktop_run_id"] == run_id)
        asyncio.run(
            agent_runtime.handle_desktop_event(
                {
                    "type": "assistant.message.appended",
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "status": "running",
                    "payload": {"message": {"content": "Done from backend worker."}},
                }
            )
        )
        asyncio.run(
            agent_runtime.handle_desktop_event(
                {
                    "type": "run.completed",
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "status": "completed",
                    "payload": {"run": {"status": "completed"}},
                }
            )
        )
        completed_detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    assert advanced.status_code == 200
    assert advanced.json()["stop_reason"] == "running"
    assert assignment["id"]
    assert stored_thread["status"] == "running"
    assert stored_run["status"] == "queued"
    assert detail["steps"][0]["status"] == "running"
    assert completed_detail["steps"][0]["status"] == "completed"
    assert completed_detail["steps"][0]["result_md"] == "Done from backend worker."
    assert completed_detail["plan"]["status"] == "completed"
    assert any(item["id"] == stored_thread["id"] for item in detail["agent_threads"])
    assert any(item["step_assignment_id"] == assignment["id"] for item in detail["step_assignment_agent_threads"])
    assert any(item["agent_thread_id"] == stored_thread["id"] for item in detail["step_execution_agent_threads"])
    with Session(engine) as session:
        links = session.exec(select(StepExecutionAgentThread)).all()
    assert any(link.agent_thread_id == stored_thread["id"] for link in links)


def test_orchestrator_thread_can_exist_without_database_agent() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat/threads", json={"thread_type": "freeChatOrchestrator", "title": "Chat"}).json()
        thread = client.post(
            "/api/agent-threads",
            json={
                "desktop_thread_id": "desktop-orchestrator-1",
                "agent_id": None,
                "manifest_agent_id": "freeChatOrchestrator",
                "title": "Chat Orchestrator",
                "initial_prompt_snapshot_md": "orchestrator prompt",
                "chat_thread_id": chat["id"],
                "owner_type": "orchestrator",
                "invocation_mode": "orchestrator",
            },
        )

    assert thread.status_code == 200
    assert thread.json()["agent_id"] is None
    assert thread.json()["owner_type"] == "orchestrator"


def test_blocked_step_allows_chat_pause_and_resume_guidance() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        plan = client.post(
            "/api/plans",
            json={"name": "Blocked plan", "description": "Handle blocked work."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Run Docker",
                "description": "Start services.",
                "step_type_id": _step_type_id(client, "Review"),
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": step["id"], "agent_id": agent["id"], "instructions_md": "Run review."},
        ).json()
        worker_thread = _create_step_worker_thread(
            client,
            plan_id=plan["id"],
            step_id=step["id"],
            assignment_id=assignment["id"],
            agent_id=agent["id"],
            title="Run Docker",
        )
        update_plan({"plan_id": plan["id"], "agent_id": agent["id"], "status": "approved"})
        started = client.post(
            f"/api/plans/{plan['id']}/start-steps",
            json={"step_ids": [step["id"]], "worker_agent_thread_ids_by_step_id": {step["id"]: [worker_thread["id"]]}},
        )
        execution = started.json()["executions"][0]
        blocked = client.post(
            f"/api/plans/executions/{execution['id']}/block",
            json={"reason_md": "Docker is not available in this environment."},
        )
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()
        resumed = client.post(
            f"/api/plans/executions/{execution['id']}/resume",
            json={"resume_message_md": "Use the already-running backend service instead of starting Docker."},
        )

    assert blocked.status_code == 200
    assert blocked.json()["execution"]["status"] == "blocked"
    assert blocked.json()["plan"]["status"] == "awaiting_review"
    assert detail["steps"][0]["status"] == "blocked"
    assert resumed.status_code == 200
    assert resumed.json()["execution"]["status"] == "running"
    assert "Resume guidance" in resumed.json()["execution"]["result_md"]


def test_mcp_orchestrator_can_block_and_resume_step() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()[:2]
        plan = client.post(
            "/api/plans",
            json={"name": "MCP blocked plan", "description": "Resume blocked step."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Install deps",
                "description": "Run setup.",
                "step_type_id": _step_type_id(client, "Review"),
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": step["id"], "agent_id": agents[0]["id"], "instructions_md": "Run review."},
        ).json()
        worker_thread = _create_step_worker_thread(
            client,
            plan_id=plan["id"],
            step_id=step["id"],
            assignment_id=assignment["id"],
            agent_id=agents[0]["id"],
            title="Install deps",
        )
        update_plan({"plan_id": plan["id"], "agent_id": agents[0]["id"], "status": "approved"})
        execution = client.post(
            f"/api/plans/{plan['id']}/start-steps",
            json={"step_ids": [step["id"]], "worker_agent_thread_ids_by_step_id": {step["id"]: [worker_thread["id"]]}},
        ).json()["executions"][0]
        blocked = mark_step_blocked(
            {
                "plan_id": plan["id"],
                "step_id": step["id"],
                "agent_id": "manifest-orchestrator",
                "reason_md": "Command unavailable.",
            }
        )
        resumed = resume_blocked_step(
            {
                "plan_id": plan["id"],
                "step_id": step["id"],
                "agent_id": "manifest-orchestrator",
                "resume_message_md": "Skip that command and use the existing service.",
            }
        )

    assert execution["status"] == "running"
    assert blocked["step"]["status"] == "blocked"
    assert blocked["plan"]["status"] == "awaiting_review"
    assert resumed["step"]["status"] == "running"
    assert "Resume guidance" in resumed["execution"]["result_md"]


def test_mcp_orchestrator_can_manage_pending_steps_and_assignments() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()[:2]
        review_type_id = _step_type_id(client, "Review")
        programming_type_id = _step_type_id(client, "Programming")
        repository = client.post(
            "/api/repositories",
            json={"name": "MCP repo", "remote_url": "git@example.com:mcp.git", "default_branch": "main"},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "MCP step plan", "description": "Edit steps."},
        ).json()
        created = create_plan_step(
            {
                "plan_id": plan["id"],
                "agent_id": agents[0]["id"],
                "name": "Draft step",
                "description": "Initial description.",
                "step_type_id": review_type_id,
                "repository_ids": [repository["id"]],
            }
        )
        step_id = created["step"]["id"]
        updated = update_plan_step(
            {
                "plan_id": plan["id"],
                "step_id": step_id,
                "agent_id": agents[0]["id"],
                "name": "Updated step",
                "description": "Detailed instructions.",
                "step_type_id": programming_type_id,
                "position": 3,
            }
        )
        assignment = create_step_assignment(
            {
                "plan_id": plan["id"],
                "step_id": step_id,
                "agent_id": agents[0]["id"],
                "assigned_agent_id": agents[1]["id"],
                "instructions_md": "Implement this.",
            }
        )
        edited_assignment = update_step_assignment(
            {
                "plan_id": plan["id"],
                "assignment_id": assignment["assignment"]["id"],
                "agent_id": agents[0]["id"],
                "instructions_md": "Implement this with tests.",
            }
        )
        deleted_assignment = delete_step_assignment(
            {
                "plan_id": plan["id"],
                "assignment_id": assignment["assignment"]["id"],
                "agent_id": agents[0]["id"],
                "confirm_delete": True,
            }
        )
        deleted_step = delete_plan_step(
            {
                "plan_id": plan["id"],
                "step_id": step_id,
                "agent_id": agents[0]["id"],
                "confirm_delete": True,
            }
        )

    assert created["success"] is True
    assert updated["step"]["name"] == "Updated step"
    assert updated["step"]["step_type_id"] == programming_type_id
    assert edited_assignment["assignment"]["instructions_md"] == "Implement this with tests."
    assert deleted_assignment == {"success": True, "assignment_id": assignment["assignment"]["id"]}
    assert deleted_step == {"success": True, "step_id": step_id}


def test_mcp_delete_plan_step_removes_command_step_execution_results() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        command_type = _step_type_by_responsible(client, "command")
        repository = client.post(
            "/api/repositories",
            json={
                "name": "Delete result repo",
                "remote_url": "git@example.com:delete/result.git",
                "default_branch": "main",
            },
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Command delete plan", "description": "Delete pending command step."},
        ).json()
        created = create_plan_step(
            {
                "plan_id": plan["id"],
                "agent_id": agent["id"],
                "name": "Command cleanup",
                "description": "Can be deleted while pending.",
                "step_type_id": command_type["id"],
                "command_text": "echo ok",
            }
        )["step"]

        with Session(engine) as session:
            command_step = session.exec(select(CommandStep).where(CommandStep.step_id == created["id"])).one()
            execution = StepExecution(step_id=created["id"], status="completed", result_md="Old run.")
            session.add(execution)
            session.commit()
            session.refresh(execution)
            session.add(
                CommandExecutionResult(
                    step_execution_id=execution.id,
                    step_id=created["id"],
                    command_step_id=command_step.id,
                    repository_id=repository["id"],
                    cwd="/tmp",
                    command_text="echo ok",
                    status="completed",
                )
            )
            session.commit()

        deleted = delete_plan_step(
            {
                "plan_id": plan["id"],
                "step_id": created["id"],
                "agent_id": agent["id"],
                "confirm_delete": True,
            }
        )

    assert deleted == {"success": True, "step_id": created["id"]}
    with Session(engine) as session:
        assert session.get(Step, created["id"]) is None
        assert session.exec(select(CommandStep).where(CommandStep.step_id == created["id"])).all() == []
        assert session.exec(select(CommandExecutionResult).where(CommandExecutionResult.step_id == created["id"])).all() == []


def test_mcp_step_tools_allow_orchestrator_and_reject_completed_step_edits() -> None:
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()[:2]
        plan = client.post(
            "/api/plans",
            json={"name": "MCP guarded plan", "description": "Guard mutations."},
        ).json()
        step = create_plan_step(
            {
                "plan_id": plan["id"],
                "agent_id": agents[0]["id"],
                "name": "Complete me",
                "description": "Review step.",
                "step_type_id": _step_type_id(client, "Review"),
            }
        )["step"]
        updated_by_orchestrator = update_plan_step(
            {
                "plan_id": plan["id"],
                "step_id": step["id"],
                "agent_id": "manifest-orchestrator",
                "name": "Allowed by orchestrator",
            }
        )
        assignment = create_step_assignment(
            {
                "plan_id": plan["id"],
                "step_id": step["id"],
                "agent_id": agents[0]["id"],
                "assigned_agent_id": agents[0]["id"],
                "instructions_md": "Review before completing.",
            }
        )
        worker_thread = _create_step_worker_thread(
            client,
            plan_id=plan["id"],
            step_id=step["id"],
            assignment_id=assignment["assignment"]["id"],
            agent_id=agents[0]["id"],
            title="Complete me",
        )
        update_plan({"plan_id": plan["id"], "agent_id": agents[0]["id"], "status": "approved"})
        execution = client.post(
            f"/api/plans/{plan['id']}/start-steps",
            json={"step_ids": [step["id"]], "worker_agent_thread_ids_by_step_id": {step["id"]: [worker_thread["id"]]}},
        ).json()["executions"][0]
        client.post(
            f"/api/plans/executions/{execution['id']}/complete",
            json={"result_md": "Reviewed.", "commits": []},
        )
        try:
            delete_plan_step(
                {
                    "plan_id": plan["id"],
                    "step_id": step["id"],
                    "agent_id": agents[0]["id"],
                    "confirm_delete": True,
                }
            )
            completed_deleted = True
        except ToolError:
            completed_deleted = False

    assert updated_by_orchestrator["step"]["name"] == "Allowed by orchestrator"
    assert completed_deleted is False


def test_mcp_lists_plans_and_returns_full_plan_detail() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        repository = client.post(
            "/api/repositories",
            json={"name": "Detail repo", "remote_url": "git@example.com:detail.git", "default_branch": "main"},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Readable plan", "description": "Inspect this."},
        ).json()
        client.put(
            f"/api/plans/{plan['id']}/repositories",
            json={"repositories": [{"repository_id": repository["id"], "start_ref": "main"}]},
        )
        first = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "First",
                "description": "First step.",
                "step_type_id": _step_type_id(client, "Review"),
                "repository_ids": [repository["id"]],
            },
        ).json()
        second = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Second",
                "description": "Second step.",
                "step_type_id": _step_type_id(client, "Review"),
                "depends_on_step_ids": [first["id"]],
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": first["id"], "agent_id": agent["id"], "instructions_md": "Review it."},
        ).json()
        plans = list_plans({})
        detail = get_plan_detail({"plan_id": plan["id"]})

    assert any(item["id"] == plan["id"] and item["status"] == "draft" for item in plans["plans"])
    assert detail["plan"]["id"] == plan["id"]
    assert {item["id"] for item in detail["steps"]} == {first["id"], second["id"]}
    assert detail["dependencies"][0]["depends_on_step_id"] == first["id"]
    assert detail["assignments"][0]["id"] == assignment["id"]
    assert detail["step_repositories"][0]["repository_id"] == repository["id"]
    assert detail["eligible_step_ids"] == [first["id"]]


def test_plan_prompt_context_includes_step_and_assignment_ids() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        plan = client.post(
            "/api/plans",
            json={"name": "Prompt ids", "description": "Expose ids."},
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Editable",
                "description": "Can edit.",
                "step_type_id": _step_type_id(client, "Review"),
            },
        ).json()
        assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": step["id"], "agent_id": agent["id"], "instructions_md": "Review with ids."},
        ).json()
        response = client.post(
            "/api/agents/prompt",
            json={
                "agent_id": agent["id"],
                "manifest_agent_id": "agentStepTask",
                "manifest_prompt_template": (
                    "Plan steps:\n{{plan.steps}}\n\n"
                    "Plan assignments:\n{{plan.assignments}}\n"
                ),
                "context": {
                    "plan": {
                        "id": plan["id"],
                        "steps": (
                            f"- Editable\n  plan_id={plan['id']}; step_id={step['id']}; "
                            "step_type=Review; status=pending; position=0"
                        ),
                        "assignments": (
                            f"- assignment_id={assignment['id']}; plan_id={plan['id']}; "
                            f"step_id={step['id']}; agent_id={agent['id']}"
                        ),
                    }
                },
            },
        )

    prompt = response.json()["prompt"]
    assert response.status_code == 200
    assert f"step_id={step['id']}" in prompt
    assert f"assignment_id={assignment['id']}" in prompt


def test_step_type_and_script_crud_supports_typed_script_steps() -> None:
    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        step_type = client.post(
            "/api/step-types",
            json={
                "name": f"Smoke script {suffix}",
                "description": "Run a smoke script.",
                "responsible": "script",
                "main_task_md": "Run the selected smoke script.",
            },
        )
        script = client.post(
            "/api/scripts",
            json={
                "name": f"Smoke {suffix}",
                "slug": f"smoke-test-{suffix}",
                "language": "python",
                "source_code": "print('ok')\n",
                "env_text": "EXAMPLE=1\n",
            },
        )
        listed_types = client.get("/api/step-types").json()
        listed_scripts = client.get("/api/scripts").json()

    assert step_type.status_code == 200
    assert script.status_code == 200
    assert any(item["id"] == step_type.json()["id"] for item in listed_types)
    assert any(item["slug"] == f"smoke-test-{suffix}" and item["env_text"] == "EXAMPLE=1\n" for item in listed_scripts)


def test_typed_assignment_rules_and_dependency_cycle_validation() -> None:
    with TestClient(app) as client:
        agent = client.get("/api/agents").json()[0]
        human_type = client.post(
            "/api/step-types",
            json={"name": "Human gate", "responsible": "human", "git_work": False},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Typed rules", "description": "Validate rules."},
        ).json()
        first = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Human review",
                "description": "Approve manually.",
                "step_type_id": human_type["id"],
            },
        ).json()
        second = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "After",
                "description": "Run after review.",
                "step_type_id": _step_type_id(client, "Review"),
                "depends_on_step_ids": [first["id"]],
            },
        ).json()
        rejected_assignment = client.post(
            "/api/plans/assignments",
            json={"step_id": first["id"], "agent_id": agent["id"], "instructions_md": "Should fail."},
        )
        rejected_cycle = client.patch(
            f"/api/plans/{plan['id']}/steps/{first['id']}",
            json={"depends_on_step_ids": [second["id"]]},
        )

    assert rejected_assignment.status_code == 400
    assert rejected_cycle.status_code == 400


def test_plan_setup_keeps_default_branch_and_script_runs_per_repo(monkeypatch, tmp_path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is not available in the backend test container")
    suffix = uuid4().hex[:8]
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("VIBE_WORKSPACE_ROOT", str(workspace))
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=origin, check=True)
    (origin / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=origin, check=True)

    with TestClient(app) as client:
        repository = client.post(
            "/api/repositories",
            json={"name": "Local script repo", "remote_url": str(origin), "default_branch": "main"},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Script plan", "description": "Run script."},
        ).json()
        client.put(
            f"/api/plans/{plan['id']}/repositories",
            json={"repositories": [{"repository_id": repository["id"], "start_ref": "main"}]},
        )
        approved = client.post(f"/api/plans/{plan['id']}/approve")
        script_type = next(item for item in client.get("/api/step-types").json() if item["responsible"] == "script")
        script = client.post(
            "/api/scripts",
            json={
                "name": f"Print repo {suffix}",
                "slug": f"print-repo-{suffix}",
                "language": "python",
                "source_code": "import os, sys\nprint(os.environ['VIBE_REPOSITORY_NAME'])\nprint('|'.join(sys.argv[1:]))\n",
            },
        ).json()
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Run script",
                "description": "Print repo name.",
                "step_type_id": script_type["id"],
                "repository_ids": [repository["id"]],
                "script_id": script["id"],
                "script_args_text": "--branch codex/example",
            },
        ).json()
        started = client.post(f"/api/plans/{plan['id']}/start-steps", json={"step_ids": [step["id"]]})
        running_detail = client.get(f"/api/plans/{plan['id']}/detail").json()
        detail = _wait_for_step_status(client, plan["id"], step["id"], "completed")

    membership = detail["repositories"][0]
    assert approved.status_code == 200
    assert membership["plan_branch"] is None
    assert membership["checkout_path"]
    assert started.status_code == 200
    assert started.json()["executions"][0]["status"] == "running"
    assert running_detail["script_results"][0]["status"] in {"running", "completed"}
    assert detail["script_steps"][0]["args_text"] == "--branch codex/example"
    assert detail["steps"][0]["status"] == "completed"
    assert detail["script_results"][0]["stdout"].splitlines() == ["Local script repo", "--branch|codex/example"]


def test_plan_checkout_uses_remote_tracking_branch_from_mirror(monkeypatch, tmp_path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is not available in the backend test container")
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("VIBE_WORKSPACE_ROOT", str(workspace))
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=origin, check=True)
    (origin / "README.md").write_text("main\n")
    subprocess.run(["git", "add", "README.md"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-b", "codex/cloud-friends-messaging"], cwd=origin, check=True)
    (origin / "README.md").write_text("branch\n")
    subprocess.run(["git", "commit", "-am", "Branch change"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=origin, check=True)

    with TestClient(app) as client:
        repository = client.post(
            "/api/repositories",
            json={"name": "Branch repo", "remote_url": str(origin), "default_branch": "main"},
        ).json()
        client.post(f"/api/repositories/{repository['id']}/sync")
        plan = client.post(
            "/api/plans",
            json={"name": "Branch plan", "description": "Use branch."},
        ).json()
        client.put(
            f"/api/plans/{plan['id']}/repositories",
            json={
                "repositories": [
                    {
                        "repository_id": repository["id"],
                        "start_ref": "codex/cloud-friends-messaging",
                    }
                ]
            },
        )
        approved = client.post(f"/api/plans/{plan['id']}/approve")
        detail = client.get(f"/api/plans/{plan['id']}/detail").json()

    checkout_path = detail["repositories"][0]["checkout_path"]
    assert approved.status_code == 200
    assert detail["repositories"][0]["start_ref"] == "codex/cloud-friends-messaging"
    assert subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=checkout_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "codex/cloud-friends-messaging"
    assert Path(checkout_path, "README.md").read_text() == "branch\n"


def test_command_step_runs_multiline_command_per_repo(monkeypatch, tmp_path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is not available in the backend test container")
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("VIBE_WORKSPACE_ROOT", str(workspace))
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=origin, check=True)
    (origin / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=origin, check=True)

    with TestClient(app) as client:
        repository = client.post(
            "/api/repositories",
            json={"name": "Local command repo", "remote_url": str(origin), "default_branch": "main"},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Command plan", "description": "Run command."},
        ).json()
        client.put(
            f"/api/plans/{plan['id']}/repositories",
            json={"repositories": [{"repository_id": repository["id"], "start_ref": "main"}]},
        )
        client.post(f"/api/plans/{plan['id']}/approve")
        command_type = next(item for item in client.get("/api/step-types").json() if item["responsible"] == "command")
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Run command",
                "description": "Inspect repo.",
                "step_type_id": command_type["id"],
                "repository_ids": [repository["id"]],
                "command_text": "git branch --show-current\ncat README.md",
            },
        ).json()
        started = client.post(f"/api/plans/{plan['id']}/start-steps", json={"step_ids": [step["id"]]})
        running_detail = client.get(f"/api/plans/{plan['id']}/detail").json()
        detail = _wait_for_step_status(client, plan["id"], step["id"], "completed")

    assert started.status_code == 200
    assert started.json()["executions"][0]["status"] == "running"
    assert running_detail["command_results"][0]["status"] in {"running", "completed"}
    assert detail["command_steps"][0]["command_text"] == "git branch --show-current\ncat README.md"
    assert detail["steps"][0]["status"] == "completed"
    assert detail["command_results"][0]["stdout"].splitlines() == ["main", "hello"]


def test_command_step_failure_records_error_log_and_failed_state(monkeypatch, tmp_path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is not available in the backend test container")
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("VIBE_WORKSPACE_ROOT", str(workspace))
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=origin, check=True)
    (origin / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=origin, check=True)

    with TestClient(app) as client:
        repository = client.post(
            "/api/repositories",
            json={"name": "Failing command repo", "remote_url": str(origin), "default_branch": "main"},
        ).json()
        plan = client.post(
            "/api/plans",
            json={"name": "Failing command plan", "description": "Run command."},
        ).json()
        client.put(
            f"/api/plans/{plan['id']}/repositories",
            json={"repositories": [{"repository_id": repository["id"], "start_ref": "main"}]},
        )
        client.post(f"/api/plans/{plan['id']}/approve")
        command_type = next(item for item in client.get("/api/step-types").json() if item["responsible"] == "command")
        step = client.post(
            f"/api/plans/{plan['id']}/steps",
            json={
                "plan_id": plan["id"],
                "name": "Run failure",
                "description": "Fail loudly.",
                "step_type_id": command_type["id"],
                "repository_ids": [repository["id"]],
                "command_text": "echo before\n>&2 echo nope\nexit 42",
            },
        ).json()
        started = client.post(f"/api/plans/{plan['id']}/start-steps", json={"step_ids": [step["id"]]})
        detail = _wait_for_step_status(client, plan["id"], step["id"], "failed")

    assert started.status_code == 200
    assert detail["plan"]["status"] == "failed"
    assert detail["steps"][0]["status"] == "failed"
    assert detail["executions"][0]["status"] == "failed"
    assert detail["executions"][0]["result_md"] == "Command failed."
    assert detail["command_results"][0]["exit_code"] == 42
    assert "before" in detail["command_results"][0]["stdout"]
    assert "nope" in detail["command_results"][0]["stderr"]

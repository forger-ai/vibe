from __future__ import annotations

import json

from sqlalchemy import text
from sqlmodel import Session, select

from app import models as _models  # noqa: F401 - register SQLModel metadata
from app.database import engine, init_db
from app.models import Agent, NotebookEntry, PlanType, StepType, utcnow


def init_app_db() -> None:
    init_db()
    migrate_app_db()
    init_db()
    seed_defaults()


def migrate_app_db() -> None:
    with engine.begin() as connection:
        step_columns = _table_columns(connection, "step")
        if step_columns and "plan_id" not in step_columns:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            for table_name in (
                "stepassignmentagentthread",
                "taskagentthread",
                "tasknotebookentry",
                "tasktypenotebookentry",
                "stepdependency",
                "stepassignment",
                "step",
                "task",
                "tasktype",
            ):
                connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            connection.execute(text("PRAGMA foreign_keys=ON"))

    init_db()

    with engine.begin() as connection:
        agent_columns = _table_columns(connection, "agent")
        if "reasoning_effort" not in agent_columns:
            connection.execute(
                text("ALTER TABLE agent ADD COLUMN reasoning_effort VARCHAR(80) NOT NULL DEFAULT 'medium'")
            )
            rows = connection.execute(text("SELECT id, model_params_json FROM agent")).mappings().all()
            for row in rows:
                effort = _effort_from_model_params(row["model_params_json"])
                connection.execute(
                    text("UPDATE agent SET reasoning_effort = :effort WHERE id = :id"),
                    {"effort": effort, "id": row["id"]},
                )
        for column in ("feature_intake_task_md", "plan_task_md", "free_chat_task_md"):
            if column not in agent_columns:
                connection.execute(
                    text(f"ALTER TABLE agent ADD COLUMN {column} VARCHAR NOT NULL DEFAULT ''")
                )

        chat_agent_columns = _table_columns(connection, "chatagentthread")
        if chat_agent_columns and ("role" in chat_agent_columns or "agent_thread_id" in chat_agent_columns):
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(text("DROP TABLE IF EXISTS chatagentthread"))
            connection.execute(text("PRAGMA foreign_keys=ON"))

        plan_columns = _table_columns(connection, "plan")
        if plan_columns:
            if "execution_mode" not in plan_columns:
                connection.execute(
                    text("ALTER TABLE plan ADD COLUMN execution_mode VARCHAR(80) NOT NULL DEFAULT 'sequential'")
                )

        agent_thread_columns = _table_columns(connection, "agentthread")
        if agent_thread_columns and bool(agent_thread_columns.get("agent_id", {}).get("notnull")):
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(text("DROP TABLE IF EXISTS agentrun"))
            connection.execute(text("DROP TABLE IF EXISTS chatprogressevent"))
            connection.execute(text("DROP TABLE IF EXISTS stepexecutionagentthread"))
            connection.execute(text("DROP TABLE IF EXISTS stepassignmentagentthread"))
            connection.execute(text("DROP TABLE IF EXISTS planagentthread"))
            connection.execute(text("DROP TABLE IF EXISTS agentthread"))
            connection.execute(text("PRAGMA foreign_keys=ON"))
            agent_thread_columns = {}
        if agent_thread_columns:
            for column, ddl in {
                "chat_thread_id": "ALTER TABLE agentthread ADD COLUMN chat_thread_id VARCHAR",
                "discussion_id": "ALTER TABLE agentthread ADD COLUMN discussion_id VARCHAR",
                "owner_type": "ALTER TABLE agentthread ADD COLUMN owner_type VARCHAR(80) NOT NULL DEFAULT 'agent'",
                "invocation_mode": "ALTER TABLE agentthread ADD COLUMN invocation_mode VARCHAR(80) NOT NULL DEFAULT 'single_task'",
            }.items():
                if column not in agent_thread_columns:
                    connection.execute(text(ddl))
                    connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_agentthread_{column} ON agentthread ({column})"))

        step_columns = _table_columns(connection, "step")
        if step_columns:
            if "kind" not in step_columns:
                connection.execute(
                    text("ALTER TABLE step ADD COLUMN kind VARCHAR(80) NOT NULL DEFAULT 'programming'")
                )
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_step_kind ON step (kind)"))
            if "position" not in step_columns:
                connection.execute(text("ALTER TABLE step ADD COLUMN position INTEGER NOT NULL DEFAULT 0"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_step_position ON step (position)"))

        step_execution_columns = _table_columns(connection, "stepexecution")
        if step_execution_columns and "orchestrator_agent_thread_id" not in step_execution_columns:
            connection.execute(text("ALTER TABLE stepexecution ADD COLUMN orchestrator_agent_thread_id VARCHAR"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_stepexecution_orchestrator_agent_thread_id ON stepexecution (orchestrator_agent_thread_id)"))

        step_type_columns = _table_columns(connection, "steptype")
        if step_type_columns:
            if "main_task_md" not in step_type_columns:
                connection.execute(text("ALTER TABLE steptype ADD COLUMN main_task_md VARCHAR NOT NULL DEFAULT ''"))
            if "responsible" not in step_type_columns:
                connection.execute(
                    text("ALTER TABLE steptype ADD COLUMN responsible VARCHAR(80) NOT NULL DEFAULT 'agent'")
                )
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_steptype_responsible ON steptype (responsible)"))

        script_step_columns = _table_columns(connection, "scriptstep")
        if script_step_columns and "args_text" not in script_step_columns:
            connection.execute(text("ALTER TABLE scriptstep ADD COLUMN args_text VARCHAR NOT NULL DEFAULT ''"))


def _table_columns(connection, table_name: str) -> dict[str, dict[str, object]]:  # type: ignore[no-untyped-def]
    rows = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return {str(row["name"]): dict(row) for row in rows}


def _effort_from_model_params(raw: object) -> str:
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {}
    effort = parsed.get("reasoningEffort") if isinstance(parsed, dict) else None
    return str(effort) if effort in {"low", "medium", "high", "xhigh", "max", "default"} else "medium"


def seed_defaults() -> None:
    with Session(engine) as session:
        _seed_default_agents(session)
        _seed_task_creation_guide(session)

        if not session.exec(select(PlanType)).first():
            session.add_all(
                [
                    PlanType(
                        name="Feature",
                        description="Plan and implement a user-visible feature end to end.",
                        context_md="Clarify intent, plan work, implement, verify, and summarize impact.",
                    ),
                    PlanType(
                        name="Bug fix",
                        description="Investigate and fix a concrete broken behavior.",
                        context_md="Reproduce or reason from evidence, patch narrowly, and verify.",
                    ),
                ]
            )

        existing_step_types = {item.name: item for item in session.exec(select(StepType)).all()}
        for step_type in _default_step_types():
            existing = existing_step_types.get(step_type.name)
            if existing:
                if not existing.main_task_md:
                    existing.main_task_md = step_type.main_task_md
                existing.responsible = step_type.responsible
                session.add(existing)
            else:
                session.add(step_type)

        now = utcnow()
        for item in session.exec(select(Agent)).all():
            item.updated_at = now
            session.add(item)
        session.commit()


def _seed_task_creation_guide(session: Session) -> None:
    now = utcnow()
    entry = session.exec(
        select(NotebookEntry).where(NotebookEntry.title == "Task creation guide")
    ).first()
    if not entry:
        entry = NotebookEntry(title="Task creation guide")
    entry.short_description = (
        "Read when creating or editing a Vibe task plan or plan step."
    )
    entry.long_description_md = (
        "When creating a task plan, use MCP reads first. Inspect repositories, agents, "
        "scripts, existing plan context, and `list_step_types` before choosing steps.\n\n"
        "Create atomic, reviewable steps. Each step should have one clear outcome, a "
        "current StepType, concrete dependencies, affected repositories, and checks that "
        "prove the step is complete. Add intermediate progress, review, human, command, "
        "or script steps where they make execution safer or easier to inspect.\n\n"
        "Assign relevant agents deliberately. Use the available agent roster to choose "
        "the best owner for each agent or multi-agent step, and write self-contained "
        "assignment instructions that include ownership, constraints, expected result, "
        "verification, and handoff format."
    )
    entry.entry_type = "task_creation"
    entry.load_policy = "always"
    entry.read_when = "creating or editing a Vibe task plan, plan step, or step assignment"
    entry.updated_at = now
    session.add(entry)


def _seed_default_agents(session: Session) -> None:
    existing_by_name = {agent.name: agent for agent in session.exec(select(Agent)).all()}
    if "Product" not in existing_by_name and "Product + UI" in existing_by_name:
        legacy = existing_by_name.pop("Product + UI")
        legacy.name = "Product"
        existing_by_name["Product"] = legacy

    now = utcnow()
    for agent in _default_agents():
        existing = existing_by_name.get(agent.name)
        if existing:
            for field in (
                "description",
                "identity_md",
                "tone_md",
                "feature_intake_task_md",
                "plan_task_md",
                "free_chat_task_md",
                "guardrails_md",
                "provider",
                "model",
                "reasoning_effort",
                "model_params_json",
                "enabled",
            ):
                setattr(existing, field, getattr(agent, field))
            existing.updated_at = now
            session.add(existing)
        else:
            session.add(agent)


def _default_agents() -> list[Agent]:
    return [
        Agent(
            name="Tech Lead",
            description="Converts product and UX decisions into executable Vibe plans across repositories.",
            identity_md=(
                "You are the Tech Lead agent inside Vibe. You understand Vibe's planning model: plans include "
                "repositories, selected plan checkouts, typed steps, dependencies, agent assignments, script steps, "
                "command steps, executions, commits, and results."
            ),
            feature_intake_task_md=(
                "Convert clarified product and UX intent into an executable development plan. Identify the repositories "
                "to work on, the technical surfaces involved, the implementation sequence, dependencies, assigned agents, "
                "and verification. Use MCP reads to inspect current repositories, agents, scripts, and step types before "
                "answering about app state or creating plan work. Use command steps for direct Git console work such as "
                "checkout, branch creation, status, "
                "add, commit, and pull-request preparation. Use script steps for reusable deterministic automation. Do not "
                "create definition-only steps; put definitions, schemas, routes, payloads, UI states, checks, risks, and "
                "acceptance criteria in plan context or step detail. Choose current StepTypes intentionally and do not "
                "use legacy kind."
            ),
            plan_task_md=(
                "Review and refine the plan into concrete executable steps that follow Vibe's schema. Ensure repositories "
                "are identified, steps are typed correctly, Git work follows the recommended gitflow through command steps, "
                "agents are assigned where needed, and every step includes enough technical detail and checks to execute. "
                "Use MCP reads before claiming plan state, available tools, or step types."
            ),
            free_chat_task_md="Answer technical planning questions and explain how to structure Vibe plans.",
            tone_md="Direct, technical, and sequencing-focused.",
            guardrails_md=(
                "Do not assume cross-repository behavior without checking the relevant repository. Do not create vague "
                "steps that only restate intent. Do not answer from memory when a Vibe MCP read tool can provide the "
                "current fact."
            ),
            provider="auto",
            model="auto",
            reasoning_effort="default",
            model_params_json={"reasoningEffort": "high"},
        ),
        Agent(
            name="Product",
            description="Shapes product intent, scope, behavior, acceptance criteria, and tradeoffs.",
            identity_md=(
                "You are the Product agent inside Vibe. Turn rough requests into clear user-visible behavior, "
                "scope boundaries, success criteria, and tradeoffs."
            ),
            feature_intake_task_md=(
                "Clarify feature intent, user-visible behavior, definitions, scope, acceptance criteria, edge cases, "
                "and unresolved questions. Keep definition work in chat and in the plan description/context, not as "
                "standalone implementation steps."
            ),
            plan_task_md=(
                "Evaluate the plan from a product perspective. Tighten scope, acceptance criteria, naming, and user "
                "impact so each step is execution-ready."
            ),
            free_chat_task_md="Help the user think through product behavior, scope, and acceptance criteria.",
            tone_md="Pragmatic, concise, and product-minded.",
            guardrails_md="Ask for product intent when behavior would otherwise be guessed.",
            provider="auto",
            model="auto",
            reasoning_effort="default",
            model_params_json={"reasoningEffort": "medium"},
        ),
        Agent(
            name="UX",
            description="Designs user flows, interface states, interaction details, and copy.",
            identity_md=(
                "You are the UX agent inside Vibe. Shape flows, screens, empty/loading/error states, controls, "
                "interaction details, and user-facing copy."
            ),
            feature_intake_task_md=(
                "Clarify the workflow, screen states, copy, affordances, confirmation points, preview/apply/undo needs, "
                "and accessibility concerns. Put settled UX decisions in plan context and implementation step detail."
            ),
            plan_task_md=(
                "Review the plan for missing UI states, unclear interaction contracts, weak copy, layout risks, and "
                "acceptance criteria that do not describe the actual user experience."
            ),
            free_chat_task_md="Help the user think through UX flows, copy, and interface behavior.",
            tone_md="Clear, concrete, and interaction-focused.",
            guardrails_md="Do not invent UI behavior when the user goal or existing pattern is unclear.",
            provider="auto",
            model="auto",
            reasoning_effort="default",
            model_params_json={"reasoningEffort": "medium"},
        ),
        Agent(
            name="Programmer",
            description="Implements scoped coding assignments in controlled plan workspaces.",
            identity_md=(
                "You are the Programmer agent inside Vibe. Implement assigned coding steps inside the provided workspace "
                "and keep changes scoped."
            ),
            feature_intake_task_md=(
                "Advise on feasibility, implementation shape, dependencies, and technical risks. Help turn settled "
                "definitions into executable implementation steps, not spec-writing steps. Name known tables, columns, "
                "indexes, routes, payloads, modules, tests, and compatibility constraints in the plan."
            ),
            plan_task_md=(
                "Turn plan changes into concrete implementation steps, dependencies, and agent assignments with enough "
                "schema, API, file/module, validation, and test detail for a worker to execute from the plan."
            ),
            free_chat_task_md="Answer technical questions and help inspect repositories or implementation options.",
            tone_md="Direct, technical, and careful.",
            guardrails_md=(
                "Do not read outside assigned workspaces unless the user explicitly shares files. Do not rewrite unrelated code."
            ),
            provider="auto",
            model="auto",
            reasoning_effort="default",
            model_params_json={"reasoningEffort": "high"},
        ),
        Agent(
            name="Reviewer",
            description="Reviews code, plans, and step results for risks and missing checks.",
            identity_md=(
                "You are the Reviewer agent inside Vibe. Prioritize bugs, regressions, missing tests, and unclear "
                "acceptance criteria."
            ),
            feature_intake_task_md=(
                "Identify unclear requirements, risky assumptions, missing checks, and acceptance gaps in chat before the "
                "plan is created. Keep final plan steps focused on execution and verification, and flag plan descriptions "
                "that omit important contracts such as columns, payloads, states, or tests."
            ),
            plan_task_md=(
                "Review the plan for sequencing, coverage, regressions, missing implementation detail, test gaps, and residual risk."
            ),
            free_chat_task_md="Review ideas, plans, and implementation options for concrete risks and missing verification.",
            tone_md="Precise and evidence-led.",
            guardrails_md="Do not approve work without concrete checks or explicit residual risk.",
            provider="auto",
            model="auto",
            reasoning_effort="default",
            model_params_json={"reasoningEffort": "medium"},
        ),
    ]


def _default_step_types() -> list[StepType]:
    return [
        StepType(
            name="Checkout branch",
            description="Create or switch to a working branch inside selected plan repositories.",
            context_md="Use when the plan needs a branch before code changes.",
            main_task_md="Create or switch to the branch requested by the plan for each selected repository.",
            responsible="command",
            git_work=True,
        ),
        StepType(
            name="Programming",
            description="Make scoped code changes for a step assignment.",
            context_md="Work in the assigned plan checkout and report changed behavior.",
            main_task_md="Implement the requested code change in the selected repositories and report the result.",
            responsible="agent",
            git_work=True,
        ),
        StepType(
            name="Commit",
            description="Commit completed changes in selected repositories.",
            context_md="Use after implementation work is complete and verified.",
            main_task_md="Create commits for completed work in each selected repository.",
            responsible="command",
            git_work=True,
        ),
        StepType(
            name="Review",
            description="Review changes, risks, and test coverage.",
            context_md="Lead with findings and verify acceptance criteria.",
            main_task_md="Review the selected repositories or step results and report concrete findings.",
            responsible="agent",
            git_work=False,
        ),
        StepType(
            name="Create PR",
            description="Create a pull request for selected repositories.",
            context_md="Use after commits are ready to be proposed upstream.",
            main_task_md="Create pull requests from the current work branches to their target base branches.",
            responsible="command",
            git_work=True,
        ),
        StepType(
            name="Publish PR",
            description="Publish or mark pull requests ready for review.",
            context_md="Use when draft PRs are ready for external review.",
            main_task_md="Publish selected pull requests or move them from draft to ready state.",
            responsible="command",
            git_work=True,
        ),
        StepType(
            name="Human review",
            description="Record a human review or approval step.",
            context_md="Use when work must pause for a person before continuing.",
            main_task_md="Wait for and record the human review result for the selected repositories.",
            responsible="human",
            git_work=False,
        ),
        StepType(
            name="Command",
            description="Run a multiline shell command directly in selected plan repositories.",
            context_md="Use for direct console operations that do not need a reusable script.",
            main_task_md="Run the configured shell command in each repository attached to the step.",
            responsible="command",
            git_work=True,
        ),
        StepType(
            name="Script",
            description="Run an editable Vibe script against selected repositories.",
            context_md="Use for deterministic workspace automation.",
            main_task_md="Run the selected script once for each repository attached to the step.",
            responsible="script",
            git_work=True,
        ),
    ]

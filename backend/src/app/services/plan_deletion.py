from __future__ import annotations

from sqlmodel import Session, select

from app.models import (
    AgentRun,
    AgentThread,
    ChatAgentThread,
    ChatMessage,
    ChatProgressEvent,
    ChatThread,
    ChatThreadMessage,
    CommandExecutionResult,
    CommandStep,
    Discussion,
    DiscussionMessage,
    DiscussionParticipant,
    Plan,
    PlanAgentThread,
    PlanChatThread,
    PlanNotebookEntry,
    PlanRepository,
    ScriptExecutionResult,
    ScriptStep,
    Step,
    StepAssignment,
    StepAssignmentAgentThread,
    StepCommit,
    StepDependency,
    StepExecution,
    StepExecutionAgentThread,
    StepRepository,
)


def delete_plan_cascade(session: Session, plan: Plan) -> None:
    steps = session.exec(select(Step).where(Step.plan_id == plan.id)).all()
    step_ids = [step.id for step in steps]
    assignments = session.exec(
        select(StepAssignment).where(StepAssignment.step_id.in_(step_ids))
    ).all() if step_ids else []
    assignment_ids = [assignment.id for assignment in assignments]
    executions = session.exec(
        select(StepExecution).where(StepExecution.step_id.in_(step_ids))
    ).all() if step_ids else []
    execution_ids = [execution.id for execution in executions]

    if execution_ids:
        for link in session.exec(
            select(StepExecutionAgentThread).where(StepExecutionAgentThread.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(link)
        for commit in session.exec(select(StepCommit).where(StepCommit.step_execution_id.in_(execution_ids))).all():
            session.delete(commit)
        for result in session.exec(
            select(ScriptExecutionResult).where(ScriptExecutionResult.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(result)
        for result in session.exec(
            select(CommandExecutionResult).where(CommandExecutionResult.step_execution_id.in_(execution_ids))
        ).all():
            session.delete(result)
    for execution in executions:
        session.delete(execution)
    if assignment_ids:
        for link in session.exec(
            select(StepAssignmentAgentThread).where(StepAssignmentAgentThread.step_assignment_id.in_(assignment_ids))
        ).all():
            session.delete(link)
    if step_ids:
        for dependency in session.exec(
            select(StepDependency).where(
                (StepDependency.step_id.in_(step_ids)) | (StepDependency.depends_on_step_id.in_(step_ids))
            )
        ).all():
            session.delete(dependency)
    for assignment in assignments:
        session.delete(assignment)
    if step_ids:
        for link in session.exec(select(StepRepository).where(StepRepository.step_id.in_(step_ids))).all():
            session.delete(link)
        for link in session.exec(select(ScriptStep).where(ScriptStep.step_id.in_(step_ids))).all():
            session.delete(link)
        for link in session.exec(select(CommandStep).where(CommandStep.step_id.in_(step_ids))).all():
            session.delete(link)
    session.flush()
    for step in steps:
        session.delete(step)
    session.flush()

    plan_agent_links = session.exec(select(PlanAgentThread).where(PlanAgentThread.plan_id == plan.id)).all()
    plan_agent_thread_ids = [link.agent_thread_id for link in plan_agent_links]
    for link in plan_agent_links:
        session.delete(link)
    if plan_agent_thread_ids:
        for run in session.exec(select(AgentRun).where(AgentRun.agent_thread_id.in_(plan_agent_thread_ids))).all():
            session.delete(run)
        for progress in session.exec(
            select(ChatProgressEvent).where(ChatProgressEvent.agent_thread_id.in_(plan_agent_thread_ids))
        ).all():
            session.delete(progress)
        for thread in session.exec(select(AgentThread).where(AgentThread.id.in_(plan_agent_thread_ids))).all():
            session.delete(thread)

    chat_links = session.exec(select(PlanChatThread).where(PlanChatThread.plan_id == plan.id)).all()
    chat_ids = [link.chat_thread_id for link in chat_links]
    for link in chat_links:
        session.delete(link)
    if chat_ids:
        discussions = session.exec(select(Discussion).where(Discussion.chat_thread_id.in_(chat_ids))).all()
        discussion_ids = [discussion.id for discussion in discussions]
        if discussion_ids:
            for message in session.exec(select(DiscussionMessage).where(DiscussionMessage.discussion_id.in_(discussion_ids))).all():
                session.delete(message)
            for participant in session.exec(select(DiscussionParticipant).where(DiscussionParticipant.discussion_id.in_(discussion_ids))).all():
                session.delete(participant)
            for discussion in discussions:
                session.delete(discussion)
            session.flush()
        chat_agent_links = session.exec(select(ChatAgentThread).where(ChatAgentThread.chat_thread_id.in_(chat_ids))).all()
        chat_agent_thread_ids = [
            thread.id for thread in session.exec(select(AgentThread).where(AgentThread.chat_thread_id.in_(chat_ids))).all()
        ]
        for link in chat_agent_links:
            session.delete(link)
        session.flush()
        if chat_agent_thread_ids:
            for run in session.exec(select(AgentRun).where(AgentRun.agent_thread_id.in_(chat_agent_thread_ids))).all():
                session.delete(run)
            for progress in session.exec(
                select(ChatProgressEvent).where(ChatProgressEvent.agent_thread_id.in_(chat_agent_thread_ids))
            ).all():
                session.delete(progress)
            for thread in session.exec(select(AgentThread).where(AgentThread.id.in_(chat_agent_thread_ids))).all():
                session.delete(thread)
            session.flush()
        for progress in session.exec(select(ChatProgressEvent).where(ChatProgressEvent.chat_thread_id.in_(chat_ids))).all():
            session.delete(progress)
        session.flush()
        message_links = session.exec(select(ChatThreadMessage).where(ChatThreadMessage.chat_thread_id.in_(chat_ids))).all()
        message_ids = [link.chat_message_id for link in message_links]
        for link in message_links:
            session.delete(link)
        session.flush()
        if message_ids:
            for message in session.exec(select(ChatMessage).where(ChatMessage.id.in_(message_ids))).all():
                session.delete(message)
            session.flush()
        for chat in session.exec(select(ChatThread).where(ChatThread.id.in_(chat_ids))).all():
            session.delete(chat)

    for repository in session.exec(select(PlanRepository).where(PlanRepository.plan_id == plan.id)).all():
        session.delete(repository)
    for link in session.exec(select(PlanNotebookEntry).where(PlanNotebookEntry.plan_id == plan.id)).all():
        session.delete(link)

    session.delete(plan)

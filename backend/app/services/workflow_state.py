"""Upsert helpers for dynamic_workflow_states (resumable workflow checkpoints)."""

from sqlalchemy import select

from app.db.models import DynamicWorkflowState
from app.db.session import AsyncSessionLocal


async def upsert_workflow_state(
    run_id: str,
    trace_id: str,
    current_node: str,
    round_index: int,
    max_rounds: int,
    status: str,
    plan: list[dict],
    snapshot: dict,
    verdict_summary: dict | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(DynamicWorkflowState).where(DynamicWorkflowState.run_id == run_id)
        )
        if existing:
            existing.current_node = current_node
            existing.round_index = round_index
            existing.max_rounds = max_rounds
            existing.status = status
            existing.plan = plan
            existing.state_snapshot = snapshot
            if verdict_summary is not None:
                existing.verdict_summary = verdict_summary
        else:
            session.add(DynamicWorkflowState(
                run_id=run_id,
                trace_id=trace_id,
                current_node=current_node,
                round_index=round_index,
                max_rounds=max_rounds,
                status=status,
                plan=plan,
                state_snapshot=snapshot,
                verdict_summary=verdict_summary or {},
            ))
        await session.commit()

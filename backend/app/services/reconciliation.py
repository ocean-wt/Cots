"""Crash reconciliation for in-flight workflow states.

Runs that never reached 'completed' before the process exited were interrupted;
they are marked on startup so operators can inspect and retry them via
GET /api/v1/runs.
"""

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.db.models import DynamicWorkflowState
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

_OPEN_STATUSES = ("planning", "planned", "dispatched")


async def reconcile_interrupted_runs() -> int:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(DynamicWorkflowState)
                .where(DynamicWorkflowState.status.in_(_OPEN_STATUSES))
            )
        ).all()
        if not rows:
            return 0
        for row in rows:
            row.status = "interrupted"
        await session.commit()
        logger.warning("marked %d interrupted run(s) from a previous process",
                       len(rows))
        return len(rows)

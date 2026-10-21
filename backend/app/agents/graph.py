"""LangGraph supervisor topology.

START → supervisor(plan) → dispatch(concurrent) → review → synthesize → END.

A durable checkpointer is injected when available (MySQL): every superstep is
persisted under thread_id == run_id, which makes a crashed run resumable from
the last completed node instead of recomputing the whole workflow.
"""

from typing import Any

from langgraph.graph import START, StateGraph

from app.agents.state import CotsState
from app.agents.supervisor import (
    dispatch_node,
    review_node,
    route_after_review,
    supervisor_node,
    synthesize_node,
)


def build_graph(checkpointer: Any | None = None):
    workflow = StateGraph(CotsState)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("dispatch", dispatch_node)
    workflow.add_node("review", review_node)
    workflow.add_node("synthesize", synthesize_node)

    workflow.add_edge(START, "supervisor")
    workflow.add_edge("supervisor", "dispatch")
    workflow.add_edge("dispatch", "review")
    # review dispatches a bounded escalation or proceeds to synthesis
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {"dispatch": "dispatch", "synthesize": "synthesize"},
    )
    workflow.add_edge("synthesize", "__end__")

    if checkpointer is not None:
        return workflow.compile(checkpointer=checkpointer)
    return workflow.compile()


# Stateless default (tests / SQLite local mode).
cots_graph = build_graph()

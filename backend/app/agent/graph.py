from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from . import nodes

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    evidence: List[str]

def build_graph():
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("api_diagnose", nodes.api_diagnose_node)
    workflow.add_node("doc_qa", nodes.doc_qa_node)
    workflow.add_node("summarize", nodes.summarize_node)
    
    # 设置条件路由
    workflow.set_conditional_entry_point(
        nodes.route_intent,
        {
            "diagnose_429": "api_diagnose",
            "doc_qa": "doc_qa"
        }
    )
    
    # 设置边
    workflow.add_edge("api_diagnose", "summarize")
    workflow.add_edge("doc_qa", "summarize")
    workflow.add_edge("summarize", END)
    
    return workflow.compile()

cots_agent = build_graph()
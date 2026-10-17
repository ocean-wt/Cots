from langchain_core.messages import AIMessage
from app.services.rag import search_knowledge_base, search_api_logs

def route_intent(state):
    """意图路由节点：判断用户的问题属于哪种类型"""
    query = state["messages"][-1].content
    if "429" in query or "报错" in query:
        return "diagnose_429"
    return "doc_qa"

def api_diagnose_node(state):
    """API诊断分支"""
    # 这里可以模拟多次工具调用读取日志
    log_evidence = search_api_logs(trace_id="trace_12345")
    return {"evidence": state.get("evidence", []) + [log_evidence], "next_action": "summarize"}

def doc_qa_node(state):
    """文档问答分支"""
    query = state["messages"][-1].content
    doc_evidence = search_knowledge_base(query)
    return {"evidence": state.get("evidence", []) + [doc_evidence], "next_action": "summarize"}

def summarize_node(state):
    """汇总节点：生成包含证据链的最终回复"""
    evidence_text = "\n".join(state.get("evidence", []))
    answer = f"根据分析，结论如下：\n\n【证据链】\n{evidence_text}\n\n【建议步骤】\n1. 检查配额；2. 降低并发。"
    return {"messages": [AIMessage(content=answer)]}
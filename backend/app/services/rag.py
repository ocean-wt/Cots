# 这里做简化模拟，实际项目中这里会连接  Milvus
def search_knowledge_base(query: str) -> str:
    """模拟从知识库中检索代码文档和排查手册"""
    # 这里可以加入大量复杂的检索逻辑，增加工具调用次数
    if "429" in query:
        return "【知识库命中】错误码 429 表示 Too Many Requests。常见原因为：1. QPS超限；2. 账号欠费。"
    return "【知识库命中】未找到直接相关的标准文档。"

def search_api_logs(trace_id: str) -> str:
    """模拟查询日志系统"""
    return f"【日志追踪】TraceID: {trace_id} -> 发生 429 报错，调用量突增 300%。"
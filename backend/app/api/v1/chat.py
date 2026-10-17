from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from app.agent.graph import cots_agent
import asyncio

router = APIRouter()

class ChatRequest(BaseModel):
    query: str

async def stream_agent_response(query: str):
    """执行 Agent 并流式输出结果"""
    inputs = {"messages": [HumanMessage(content=query)]}
    
    # 执行 LangGraph 状态机
    result = cots_agent.invoke(inputs)
    final_answer = result["messages"][-1].content
    
    # 模拟 SSE 分段流式输出（架构图要求：答案生成后，分块发送）
    chunk_size = 10
    for i in range(0, len(final_answer), chunk_size):
        chunk = final_answer[i:i+chunk_size]
        yield f"data: {chunk}\n\n"
        await asyncio.sleep(0.1) # 模拟网络延迟

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(
        stream_agent_response(request.query),
        media_type="text/event-stream"
    )
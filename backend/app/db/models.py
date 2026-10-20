"""Database models.

Eight core business tables (tenants / users / applications / api_keys /
conversations / messages / tickets / api_logs), two extension tables that
make the agent runtime observable and resumable (``agent_execution_traces``,
``dynamic_workflow_states`` — JSON-first so future task types need no
migration), and ``knowledge_chunks`` as the authoritative corpus that feeds
both the BM25 and the Milvus retrieval channels.

The same SQLAlchemy 2.0 typed models run on MySQL 8.0 (docker topology) and
on SQLite (local development); dialect-specific DDL lives in
``scripts/init.sql``.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


# --------------------------------------------------------------------------- #
# 1. tenants
# --------------------------------------------------------------------------- #
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    plan: Mapped[str] = mapped_column(String(32), default="pro")  # free|pro|enterprise
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|suspended
    daily_quota: Mapped[int] = mapped_column(Integer, default=100_000)
    qps_limit: Mapped[int] = mapped_column(Integer, default=50)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")


# --------------------------------------------------------------------------- #
# 2. users
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255), default="!")
    role: Mapped[str] = mapped_column(String(32), default="admin")
    status: Mapped[str] = mapped_column(String(32), default="active")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="users")


# --------------------------------------------------------------------------- #
# 3. applications
# --------------------------------------------------------------------------- #
class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    app_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(32), default="production")
    status: Mapped[str] = mapped_column(String(32), default="active")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# 4. api_keys
# --------------------------------------------------------------------------- #
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("applications.id"), nullable=True
    )
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(128), default="default")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# 5. conversations
# --------------------------------------------------------------------------- #
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.id"
    )


# --------------------------------------------------------------------------- #
# 6. messages
# --------------------------------------------------------------------------- #
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))  # user|assistant|system
    content: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    structured: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# --------------------------------------------------------------------------- #
# 7. tickets (auto-escalation fallback)
# --------------------------------------------------------------------------- #
class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    ticket_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), default="technical")
    priority: Mapped[str] = mapped_column(String(16), default="P2")
    status: Mapped[str] = mapped_column(String(32), default="open")
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="agent_auto")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------- #
# 8. api_logs (source of truth for diagnostics)
# --------------------------------------------------------------------------- #
class ApiLog(Base):
    __tablename__ = "api_logs"
    __table_args__ = (
        Index("ix_api_logs_trace_status", "trace_id", "status_code"),
        Index("ix_api_logs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("applications.id"), nullable=True
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("api_keys.id"), nullable=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(8))
    endpoint: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    request_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upstream: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


# --------------------------------------------------------------------------- #
# 9. agent_execution_traces — full trail: reasoning / tool calls / evidence / tokens
# --------------------------------------------------------------------------- #
class AgentExecutionTrace(Base):
    __tablename__ = "agent_execution_traces"
    __table_args__ = (
        Index("ix_traces_run_agent", "run_id", "agent_name"),
        Index("ix_traces_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    round_index: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(64))
    node: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(32))  # start|tool_call|tool_result|end
    action: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# 10. dynamic_workflow_states — resumable workflow checkpoints / dynamic state
# --------------------------------------------------------------------------- #
class DynamicWorkflowState(Base):
    __tablename__ = "dynamic_workflow_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    current_node: Mapped[str] = mapped_column(String(64), default="supervisor")
    round_index: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(32), default="planning")
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verdict_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------- #
# 11. knowledge_chunks — authoritative corpus for BM25 / dense retrieval
# --------------------------------------------------------------------------- #
class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    # NOTE: tags is a JSON column (no plain index on MySQL 8; lexical search
    # runs through the in-memory BM25 index, relational lookups use doc_id).
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_doc_chunk"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    doc_title: Mapped[str] = mapped_column(String(255))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_status: Mapped[str] = mapped_column(String(16), default="pending")
    rerank_bias: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

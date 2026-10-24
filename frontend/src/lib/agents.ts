import type { AgentName } from '../types'

export const AGENT_META: Record<
  AgentName,
  { name: string; role: string; accent: string; glyph: string }
> = {
  supervisor: {
    name: 'Supervisor',
    role: '主管智能体 · 任务拆解与汇总',
    accent: 'from-violet-500 to-fuchsia-500',
    glyph: '◈',
  },
  diagnostic: {
    name: 'DiagnosticAgent',
    role: '排障专家 · 日志 / TraceID',
    accent: 'from-sky-500 to-cyan-400',
    glyph: '⛨',
  },
  billing: {
    name: 'BillingAgent',
    role: '账单专家 · 配额 / QPS / 欠费',
    accent: 'from-amber-500 to-orange-400',
    glyph: '¥',
  },
  knowledge: {
    name: 'KnowledgeAgent',
    role: '知识专家 · Milvus + BM25 混合 RAG',
    accent: 'from-emerald-500 to-teal-400',
    glyph: '✦',
  },
  support: {
    name: 'SupportAgent',
    role: '建单专家 · 人工兜底',
    glyph: '☑',
    accent: 'from-rose-500 to-pink-400',
  },
}

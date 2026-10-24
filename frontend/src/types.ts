export type AgentName =
  | 'supervisor'
  | 'diagnostic'
  | 'billing'
  | 'knowledge'
  | 'support'

export type AgentStatus =
  | 'planning'
  | 'dispatching'
  | 'synthesizing'
  | 'running'
  | 'waiting'
  | 'done'
  | 'error'
  | 'timeout'

export interface AgentAction {
  trace_id: string
  run_id: string
  agent: AgentName
  status: AgentStatus
  action: string
  detail?: string
  task_id?: string | null
  round?: number
  tools?: string[]
}

export interface Evidence {
  id: string
  kind: 'log' | 'billing' | 'knowledge' | 'ticket' | 'system'
  title: string
  summary: string
  source: string
  agent: AgentName
  status: string
  payload: Record<string, unknown>
}

export interface ScoreSet {
  dense: number
  bm25: number
  rrf: number
  rerank: number
}

export interface KnowledgeChunk {
  chunk_uid: string
  doc_id: string
  doc_title: string
  section: string
  tags: string[]
  snippet: string
  scores: ScoreSet
  channels: string[]
}

export interface FinalReport {
  trace_id: string
  run_id: string
  intent: string
  conclusion_markdown: string
  root_causes: string[]
  steps: string[]
  evidences: Evidence[]
  tickets: Array<{ ticket_no: string; title?: string; priority?: string }>
  confidence: number
  rounds: number
  token_usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  token_usage_estimated?: boolean
}

export interface RoundPlan {
  round: number
  max_rounds: number
  intent: string
  plan: Array<{
    id: string
    agent: AgentName
    goal: string
    tool_hint: string
    reason: string
  }>
}

export type SSEEvent =
  | { seq: number; event: 'agent_action'; data: AgentAction }
  | { seq: number; event: 'evidence'; data: Evidence }
  | { seq: number; event: 'round'; data: RoundPlan }
  | { seq: number; event: 'token'; data: { text: string } }
  | { seq: number; event: 'final'; data: { report: FinalReport } }
  | { seq: number; event: 'error'; data: { message: string } }
  | { seq: number; event: 'done'; data: Record<string, never> }
  | { seq: number; event: 'ping'; data: unknown }

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  runId?: string
  traceId?: string
  actions?: AgentAction[]
  evidences?: Evidence[]
  rounds?: RoundPlan[]
  report?: FinalReport
  error?: boolean
}

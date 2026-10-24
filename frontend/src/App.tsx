import { useCallback, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Header } from './components/Header'
import { Composer } from './components/Composer'
import { AssistantMessage } from './components/AssistantMessage'
import { ChatStreamError, streamChat } from './lib/sse'
import type {
  AgentAction,
  ChatMessage,
  Evidence,
  FinalReport,
  RoundPlan,
  SSEEvent,
} from './types'

let messageSeq = 0
const nextId = () => `msg-${++messageSeq}-${Date.now()}`

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const seenSeq = useRef<Map<string, Set<number>>>(new Map())

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
    })
  }, [])

  const applyEvent = (id: string) => (event: SSEEvent) => {
    // Resume may replay events already rendered — dedupe on SSE sequence.
    let seen = seenSeq.current.get(id)
    if (!seen) {
      seen = new Set<number>()
      seenSeq.current.set(id, seen)
    }
    if (event.seq > 0 && seen.has(event.seq)) return
    if (event.seq > 0) seen.add(event.seq)

    setMessages((prev) =>
      prev.map((msg) => {
        if (msg.id !== id) return msg
        switch (event.event) {
          case 'agent_action': {
            const action = event.data as unknown as AgentAction
            return {
              ...msg,
              traceId: msg.traceId ?? action.trace_id,
              actions: [...(msg.actions ?? []), action],
            }
          }
          case 'evidence': {
            const evidence = event.data as unknown as Evidence
            if (msg.evidences?.some((e) => e.id === evidence.id)) return msg
            return { ...msg, evidences: [...(msg.evidences ?? []), evidence] }
          }
          case 'round': {
            const round = event.data as unknown as RoundPlan
            if (msg.rounds?.some((r) => r.round === round.round)) return msg
            return { ...msg, rounds: [...(msg.rounds ?? []), round] }
          }
          case 'token': {
            return { ...msg, content: msg.content + event.data.text }
          }
          case 'final': {
            const report = event.data.report as unknown as FinalReport
            return {
              ...msg,
              report,
              traceId: report.trace_id,
              content: report.conclusion_markdown,
            }
          }
          case 'error': {
            const { code, message } = event.data as { code?: string; message?: string }
            return {
              ...msg,
              error: true,
              content: code ? `[${code}] ${message ?? ''}` : (message ?? '执行失败'),
            }
          }
          default:
            return msg
        }
      })
    )
    scrollToBottom()
  }

  const send = useCallback(
    (text: string) => {
      const assistantId = nextId()
      const userMsg: ChatMessage = { id: nextId(), role: 'user', content: text }
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        streaming: true,
        actions: [],
        evidences: [],
        rounds: [],
      }
      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setBusy(true)
      setReconnecting(false)
      setNotice(null)
      scrollToBottom()

      const controller = new AbortController()
      abortRef.current = controller

      streamChat({
        message: text,
        signal: controller.signal,
        onEvent: applyEvent(assistantId),
        onError: (err: ChatStreamError, canResume: boolean) => {
          if (err.status === 429) {
            const wait = err.retryAfter ? `，请 ${err.retryAfter}s 后重试` : '，请稍后重试'
            setNotice(`请求过于频繁（429）${wait}`)
          } else if (!canResume) {
            setNotice(`${err.code}: ${err.message}`)
          }
          setReconnecting(canResume)
        },
        onClose: () => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, streaming: false } : m
            )
          )
          setBusy(false)
          setReconnecting(false)
          abortRef.current = null
          scrollToBottom()
        },
      })
    },
    [scrollToBottom]
  )

  const stop = () => abortRef.current?.abort()

  return (
    <div className="mx-auto flex h-screen max-w-6xl flex-col px-4 pb-5 sm:px-6">
      <Header />

      <div ref={scrollRef} className="flex-1 space-y-6 overflow-y-auto py-6 pr-1">
        {messages.length === 0 ? <Hero onPick={send} /> : null}
        <AnimatePresence initial={false}>
          {messages.map((message) =>
            message.role === 'user' ? (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex justify-end"
              >
                <div className="glass max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-[14px] leading-6 text-white">
                  {message.content}
                </div>
              </motion.div>
            ) : (
              <AssistantMessage key={message.id} message={message} />
            )
          )}
        </AnimatePresence>
      </div>

      {(reconnecting || notice) && (
        <div
          className={`mb-2 flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[12px] ${
            reconnecting
              ? 'border-amber-400/30 bg-amber-400/10 text-amber-200'
              : 'border-rose-400/30 bg-rose-400/10 text-rose-200'
          }`}
        >
          <span className="h-1.5 w-1.5 animate-pulseSoft rounded-full bg-current" />
          {reconnecting
            ? '连接中断，正在通过 Last-Event-ID 续传事件…'
            : notice}
          {!reconnecting && (
            <button
              type="button"
              className="ml-auto text-[11px] underline underline-offset-2"
              onClick={() => setNotice(null)}
            >
              关闭
            </button>
          )}
        </div>
      )}

      <Composer busy={busy} onSend={send} onStop={stop} />
    </div>
  )
}

function Hero({ onPick }: { onPick: (text: string) => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="glass mx-auto mt-10 max-w-3xl rounded-3xl p-8 text-center sm:p-12"
    >
      <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 via-violet-500 to-cyan-400 text-2xl text-white shadow-glow">
        ◈
      </div>
      <h1 className="bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-2xl font-semibold text-transparent sm:text-3xl">
        Cots · 自主执行任务的超级智能
      </h1>
      <p className="mx-auto mt-3 max-w-xl text-[13.5px] leading-6 text-slate-400">
        Supervisor 主管智能体理解你的模糊目标，并发调度排障、账单、知识专家，
        跨日志系统、计费库与 Milvus 混合检索收集证据，输出带证据链的最终结论。
      </p>
      <div className="mt-6 grid grid-cols-1 gap-3 text-left sm:grid-cols-3">
        {[
          { t: '多智能体协作', d: 'LangGraph Supervisor + 4 专家并发' },
          { t: '混合 RAG', d: 'Milvus + BM25，手写 RRF 融合' },
          { t: '证据链推流', d: 'SSE 实时可视化思考过程' },
        ].map((card) => (
          <div key={card.t} className="glass-soft rounded-xl p-4">
            <div className="text-[13px] font-semibold text-white">{card.t}</div>
            <div className="mt-1 text-[11.5px] text-slate-500">{card.d}</div>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => onPick('系统报 429 错误了，traceID trc-9f3a2c7b1e4d，帮我紧急排查')}
        className="mt-7 rounded-xl bg-gradient-to-r from-brand-500 to-cyan-500 px-5 py-2.5 text-[13.5px] font-medium text-white shadow-glow transition hover:brightness-110"
      >
        体验 429 事故自动排查 →
      </button>
    </motion.div>
  )
}

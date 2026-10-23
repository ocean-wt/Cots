import { AnimatePresence, motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../types'
import { AgentPipeline } from './AgentPipeline'
import { EvidenceCard } from './EvidenceCard'
import { TraceChip } from './TraceChip'

function Typewriter({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulseSoft bg-brand-400 align-middle" />
    </div>
  )
}

export function AssistantMessage({ message }: { message: ChatMessage }) {
  const live = message.streaming && !message.report
  const actions = message.actions ?? []
  const evidences = message.evidences ?? []

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-4"
    >
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-cyan-400 text-sm font-bold text-white shadow-glow">
          ◈
        </div>
        <div>
          <div className="text-[13px] font-semibold text-white">Cots 超级智能</div>
          <div className="font-mono text-[10.5px] text-slate-500">
            {message.traceId && <TraceChip text={message.traceId} />}
          </div>
        </div>
      </div>

      {actions.length > 0 && (
        <div className="glass rounded-2xl p-4">
          <AgentPipeline
            actions={actions}
            rounds={message.rounds ?? []}
            live={!!message.streaming}
          />
        </div>
      )}

      <AnimatePresence>
        {evidences.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="grid grid-cols-1 gap-3 lg:grid-cols-2"
          >
            {evidences.map((ev) => (
              <EvidenceCard
                key={ev.id}
                evidence={ev}
                defaultOpen={ev.kind === 'log' || ev.kind === 'ticket'}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {live && !message.content && (
        <div className="glass space-y-3 rounded-2xl p-5">
          <div className="skeleton h-4 w-2/3" />
          <div className="skeleton h-4 w-full" />
          <div className="skeleton h-4 w-5/6" />
          <div className="skeleton h-20 w-full" />
        </div>
      )}

      {message.content && (
        <div className="glass rounded-2xl p-5">
          {message.streaming ? (
            <Typewriter text={message.content} />
          ) : (
            <div className="markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          {message.report && (
            <ReportFooter message={message} />
          )}
        </div>
      )}

      {message.error && (
        <div className="rounded-xl border border-rose-400/30 bg-rose-400/10 px-4 py-2.5 text-[13px] text-rose-200">
          执行失败：{message.content || '未知错误'}
        </div>
      )}
    </motion.div>
  )
}

function ReportFooter({ message }: { message: ChatMessage }) {
  const report = message.report!
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/5 pt-3 text-[11px] text-slate-500">
      <span className="flex items-center gap-1.5">
        置信度
        <span className="font-mono text-emerald-300">
          {Math.round(report.confidence * 100)}%
        </span>
      </span>
      <span>轮次 {report.rounds}</span>
      <span className="font-mono" title={report.token_usage_estimated ? '本地估算' : '供应商回执'}>
        tokens {report.token_usage.total_tokens.toLocaleString()}
        {report.token_usage_estimated ? ' · 估算' : ' · 精确'}
      </span>
      {report.tickets.length > 0 && (
        <span className="rounded bg-rose-400/15 px-2 py-0.5 text-rose-300">
          已建工单 {report.tickets[0].ticket_no}
        </span>
      )}
    </div>
  )
}

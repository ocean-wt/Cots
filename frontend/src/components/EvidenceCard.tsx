import { AnimatePresence, motion } from 'framer-motion'
import { useState } from 'react'
import type { Evidence, KnowledgeChunk } from '../types'
import { AGENT_META } from '../lib/agents'
import { TraceChip } from './TraceChip'

const KIND_META: Record<
  Evidence['kind'],
  { label: string; icon: string; ring: string; title: string }
> = {
  log: {
    label: '日志证据',
    icon: '⛨',
    ring: 'border-sky-400/25',
    title: 'text-sky-300',
  },
  billing: {
    label: '账单证据',
    icon: '¥',
    ring: 'border-amber-400/25',
    title: 'text-amber-300',
  },
  knowledge: {
    label: '知识证据',
    icon: '✦',
    ring: 'border-emerald-400/25',
    title: 'text-emerald-300',
  },
  ticket: {
    label: '工单证据',
    icon: '☑',
    ring: 'border-rose-400/25',
    title: 'text-rose-300',
  },
  system: {
    label: '系统证据',
    icon: 'ⓘ',
    ring: 'border-slate-400/25',
    title: 'text-slate-300',
  },
}

function ScoreBar({ label, value, max = 1 }: { label: string; value: number; max?: number }) {
  const pct = Math.max(4, Math.min(100, (value / max) * 100))
  return (
    <div className="flex items-center gap-2 text-[10.5px] text-slate-400">
      <span className="w-12 shrink-0 font-mono">{label}</span>
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-cyan-400"
        />
      </div>
      <span className="w-10 text-right font-mono">{value.toFixed(3)}</span>
    </div>
  )
}

function LogDetail({ analysis }: { analysis: Record<string, unknown> }) {
  const breakdown = analysis.status_breakdown as Record<string, number> | undefined
  const samples = (analysis.sample_logs as Array<Record<string, unknown>>) ?? []
  const errors = (analysis.top_error_messages as Array<[string, number]>) ?? []
  return (
    <div className="mt-3 space-y-2.5">
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { k: '请求总数', v: analysis.total as number },
          { k: '峰值 QPS', v: analysis.peak_qps as number },
          { k: '错误率', v: `${Math.round((analysis.error_rate as number) * 100)}%` },
        ].map((s) => (
          <div key={s.k} className="rounded-lg bg-black/25 px-2 py-1.5">
            <div className="font-mono text-sm font-semibold text-white">{s.v}</div>
            <div className="text-[10px] text-slate-500">{s.k}</div>
          </div>
        ))}
      </div>
      {breakdown && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(breakdown).map(([code, count]) => (
            <span
              key={code}
              className={`rounded-md px-2 py-0.5 font-mono text-[11px] ${
                code.startsWith('2')
                  ? 'bg-emerald-400/10 text-emerald-300'
                  : 'bg-rose-400/10 text-rose-300'
              }`}
            >
              {code} × {count}
            </span>
          ))}
        </div>
      )}
      {errors.length > 0 && (
        <ul className="space-y-1">
          {errors.slice(0, 3).map(([msg, count]) => (
            <li key={msg} className="flex gap-2 font-mono text-[11px] text-slate-400">
              <span className="text-rose-400">×{count}</span>
              <TraceChip text={msg} />
            </li>
          ))}
        </ul>
      )}
      {samples.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-white/10">
          {samples.slice(0, 3).map((row, i) => (
            <div
              key={i}
              className="flex items-center gap-2 border-b border-white/5 px-2.5 py-1.5 font-mono text-[10.5px] last:border-0"
            >
              <span
                className={`rounded px-1.5 py-0.5 ${
                  (row.status_code as number) >= 400
                    ? 'bg-rose-400/15 text-rose-300'
                    : 'bg-emerald-400/15 text-emerald-300'
                }`}
              >
                {String(row.status_code)}
              </span>
              <span className="text-slate-400">{String(row.method)}</span>
              <span className="truncate text-slate-300">{String(row.endpoint)}</span>
              <span className="ml-auto shrink-0 text-slate-500">
                {String(row.latency_ms)}ms
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function BillingDetail({ billing }: { billing: Record<string, unknown> }) {
  const ratio = (billing.quota_usage_ratio as number) ?? 0
  return (
    <div className="mt-3 space-y-2.5">
      <div>
        <div className="mb-1 flex justify-between text-[11px] text-slate-400">
          <span>
            日配额 {Number(billing.used_today).toLocaleString()} /{' '}
            {Number(billing.daily_quota).toLocaleString()}
          </span>
          <span className="font-mono">{Math.round(ratio * 100)}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, ratio * 100)}%` }}
            transition={{ duration: 0.7 }}
            className="h-full rounded-full bg-gradient-to-r from-amber-400 to-rose-500"
          />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { k: 'QPS 上限', v: String(billing.qps_limit) },
          { k: '余额(元)', v: String(billing.balance_yuan) },
          { k: '套餐', v: String(billing.plan) },
        ].map((s) => (
          <div key={s.k} className="rounded-lg bg-black/25 px-2 py-1.5">
            <div className="font-mono text-sm font-semibold text-white">{String(s.v)}</div>
            <div className="text-[10px] text-slate-500">{s.k}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Boolean(billing.quota_exhausted) && (
          <span className="rounded-md bg-rose-400/15 px-2 py-0.5 text-[11px] text-rose-300">
            配额已耗尽
          </span>
        )}
        {Boolean(billing.overdue) && (
          <span className="rounded-md bg-rose-400/15 px-2 py-0.5 text-[11px] text-rose-300">
            欠费 {String(billing.overdue_days)} 天
          </span>
        )}
        {!billing.quota_exhausted && !billing.overdue && (
          <span className="rounded-md bg-emerald-400/15 px-2 py-0.5 text-[11px] text-emerald-300">
            账单状态正常
          </span>
        )}
      </div>
    </div>
  )
}

function KnowledgeDetail({ result }: { result: Record<string, unknown> }) {
  const chunks = (result.chunks as KnowledgeChunk[]) ?? []
  return (
    <div className="mt-3 space-y-2">
      <p className="text-[11px] text-slate-500">
        双路 Top20 召回 · RRF 融合 · gte 精排（候选 {String(result.total_candidates)}）
      </p>
      {chunks.slice(0, 4).map((chunk, i) => (
        <div key={chunk.chunk_uid} className="rounded-lg bg-black/25 p-2.5">
          <div className="mb-1.5 flex items-center gap-2">
            <span className="flex h-4 w-4 items-center justify-center rounded bg-emerald-400/20 text-[10px] text-emerald-300">
              {i + 1}
            </span>
            <span className="truncate text-[12px] font-medium text-white">
              {chunk.doc_title}
            </span>
            <span className="ml-auto flex gap-1">
              {chunk.channels.map((c) => (
                <span
                  key={c}
                  className="rounded bg-white/10 px-1 py-0.5 font-mono text-[9.5px] text-slate-300"
                >
                  {c === 'dense' ? '向量' : 'BM25'}
                </span>
              ))}
            </span>
          </div>
          <p className="mb-1.5 line-clamp-2 text-[11px] leading-5 text-slate-400">
            {chunk.snippet}
          </p>
          <div className="space-y-0.5">
            <ScoreBar label="rerank" value={chunk.scores.rerank} />
            <ScoreBar label="dense" value={chunk.scores.dense} />
            <ScoreBar label="rrf" value={chunk.scores.rrf * 60} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function EvidenceCard({ evidence, defaultOpen }: {
  evidence: Evidence
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(!!defaultOpen)
  const meta = KIND_META[evidence.kind]
  const payload = evidence.payload as Record<string, unknown>

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 240, damping: 26 }}
      className={`glass-soft rounded-xl border ${meta.ring} p-3.5`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 text-left"
      >
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.06] text-base ${meta.title}`}
        >
          {meta.icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className={`text-[13px] font-semibold ${meta.title}`}>
              {evidence.title}
            </span>
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-slate-400">
              {meta.label}
            </span>
          </span>
          <span className="mt-0.5 line-clamp-2 block text-[11.5px] leading-5 text-slate-400">
            <TraceChip text={evidence.summary} />
          </span>
        </span>
        <span className="shrink-0 text-slate-500 transition-transform" style={{
          transform: open ? 'rotate(180deg)' : 'none',
        }}>
          ⌄
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24 }}
            className="overflow-hidden"
          >
            {evidence.kind === 'log' && Boolean(payload.analysis) && (
              <LogDetail analysis={payload.analysis as Record<string, unknown>} />
            )}
            {evidence.kind === 'billing' && Boolean(payload.billing) && (
              <BillingDetail billing={payload.billing as Record<string, unknown>} />
            )}
            {evidence.kind === 'knowledge' && Boolean(payload.retrieval ?? payload) && (
              <KnowledgeDetail
                result={(payload.retrieval ?? payload) as Record<string, unknown>}
              />
            )}
            {evidence.kind === 'ticket' && (
              <div className="mt-3 flex items-center gap-3 rounded-lg bg-rose-400/10 px-3 py-2 text-[12px] text-rose-200">
                <span className="font-mono font-semibold">
                  {String(payload.ticket_no ?? '')}
                </span>
                <span>优先级 {String(payload.priority ?? '')}</span>
                <span className="ml-auto">{String(payload.status ?? '')}</span>
              </div>
            )}
            <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-2 text-[10px] text-slate-500">
              <span className="font-mono">
                {evidence.source} · {AGENT_META[evidence.agent]?.name ?? evidence.agent}
              </span>
              {evidence.status !== 'ok' && (
                <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-amber-300">
                  {evidence.status}
                </span>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

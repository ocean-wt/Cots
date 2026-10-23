import { AnimatePresence, motion } from 'framer-motion'
import { useMemo } from 'react'
import type { AgentAction, AgentStatus, RoundPlan } from '../types'
import { AGENT_META } from '../lib/agents'

const STATUS_LABEL: Record<AgentStatus, string> = {
  planning: '规划中',
  dispatching: '派发中',
  synthesizing: '汇总中',
  running: '执行中',
  waiting: '等待',
  done: '完成',
  error: '异常',
  timeout: '超时',
}

function statusTone(status: AgentStatus): string {
  switch (status) {
    case 'done':
      return 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30'
    case 'error':
      return 'text-rose-300 bg-rose-400/10 border-rose-400/30'
    case 'timeout':
      return 'text-amber-300 bg-amber-400/10 border-amber-400/30'
    default:
      return 'text-brand-200 bg-brand-400/10 border-brand-400/30'
  }
}

function Spinner() {
  return (
    <span className="relative flex h-2.5 w-2.5">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-70" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-400" />
    </span>
  )
}

function NodeCard({
  agent,
  action,
  isSupervisor,
}: {
  agent: keyof typeof AGENT_META
  action?: AgentAction
  isSupervisor?: boolean
}) {
  const meta = AGENT_META[agent]
  const status: AgentStatus = action?.status ?? 'waiting'
  const active = ['planning', 'dispatching', 'synthesizing', 'running'].includes(status)
  const failed = status === 'error' || status === 'timeout'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 18, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 260, damping: 24 }}
      className={`glass-soft relative w-full min-w-[190px] rounded-2xl p-3.5 ${
        isSupervisor ? 'border-violet-400/25' : ''
      } ${active ? 'shadow-glow' : ''}`}
    >
      <div className="flex items-start gap-3">
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-lg font-semibold text-white ${meta.accent} ${
            active ? 'animate-pulseSoft' : ''
          } ${failed ? 'grayscale-[0.3]' : ''}`}
        >
          {meta.glyph}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-[13.5px] font-semibold text-white">
              {meta.name}
            </span>
            <span
              className={`shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${statusTone(
                status
              )}`}
            >
              {STATUS_LABEL[status]}
            </span>
          </div>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">{meta.role}</p>
        </div>
      </div>

      <AnimatePresence mode="wait">
        {action?.action && (
          <motion.div
            key={action.action + (action.detail ?? '')}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22 }}
            className="overflow-hidden"
          >
            <div className="mt-2.5 flex items-start gap-2 rounded-lg bg-black/20 px-2.5 py-2">
              {active && <Spinner />}
              <p className="text-[11.5px] leading-5 text-slate-300">
                <span className="text-slate-100">{action.action}</span>
                {action.detail ? (
                  <span className="block truncate text-slate-500">{action.detail}</span>
                ) : null}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {action?.tools && action.tools.length > 0 && active && (
        <div className="mt-2 flex flex-wrap gap-1">
          {action.tools.map((tool) => (
            <span
              key={tool}
              className="rounded border border-white/10 bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-300"
            >
              {tool}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  )
}

export function AgentPipeline({
  actions,
  rounds,
  live,
}: {
  actions: AgentAction[]
  rounds: RoundPlan[]
  live: boolean
}) {
  const latestByAgent = useMemo(() => {
    const map = new Map<string, AgentAction>()
    for (const action of actions) map.set(action.agent, action)
    return map
  }, [actions])

  const supervisor = latestByAgent.get('supervisor')
  const latestRound = rounds[rounds.length - 1]
  const expertAgents = useMemo(() => {
    const agents = new Set<string>()
    for (const round of rounds) round.plan.forEach((p) => agents.add(p.agent))
    for (const action of actions)
      if (action.agent !== 'supervisor') agents.add(action.agent)
    return Array.from(agents)
  }, [actions, rounds])

  return (
    <div className="rounded-2xl">
      <div className="mb-3 flex items-center gap-2 text-xs text-slate-400">
        <span className="font-medium uppercase tracking-[0.18em]">Agent Pipeline</span>
        {live && (
          <span className="flex items-center gap-1.5 rounded-full border border-brand-400/30 bg-brand-400/10 px-2 py-0.5 text-brand-200">
            <Spinner />
            多智能体协作中
          </span>
        )}
        {latestRound && (
          <span className="ml-auto font-mono text-[10.5px] text-slate-500">
            round {latestRound.round + 1}/{latestRound.max_rounds}
          </span>
        )}
      </div>

      <NodeCard agent="supervisor" action={supervisor} isSupervisor />

      <div className="relative my-2 flex justify-center">
        <svg width="2" height="22" className={live ? 'connector-active' : ''}>
          <line x1="1" y1="0" x2="1" y2="22" stroke="url(#pipeGrad)" strokeWidth="2" />
          <defs>
            <linearGradient id="pipeGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" />
              <stop offset="100%" stopColor="#22d3ee" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {expertAgents.map((agent, i) => (
          <motion.div
            key={agent}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
          >
            <NodeCard
              agent={agent as keyof typeof AGENT_META}
              action={latestByAgent.get(agent)}
            />
          </motion.div>
        ))}
      </div>
    </div>
  )
}

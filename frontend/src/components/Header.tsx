import { useEffect, useState } from 'react'

function useTheme() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('cots-theme')
    return saved ? saved === 'dark' : true
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.classList.toggle('light', !dark)
    localStorage.setItem('cots-theme', dark ? 'dark' : 'light')
  }, [dark])
  return { dark, toggle: () => setDark((v) => !v) }
}

export function Header() {
  const { dark, toggle } = useTheme()
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/5">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 via-violet-500 to-cyan-400 text-lg text-white shadow-glow">
          ◈
        </div>
        <div>
          <div className="flex items-center gap-2 text-[15px] font-semibold tracking-tight text-white">
            Cots
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9.5px] font-medium uppercase tracking-wider text-slate-400">
              Autonomous Agent
            </span>
          </div>
          <div className="text-[10.5px] text-slate-500">
            LangGraph Supervisor · Multi-Agent Ops Copilot
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="hidden items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-1 text-[10.5px] text-emerald-300 sm:flex">
          <span className="h-1.5 w-1.5 animate-pulseSoft rounded-full bg-emerald-400" />
          实时 SSE 已连接
        </span>
        <button
          type="button"
          onClick={toggle}
          className="glass-soft flex h-9 w-9 items-center justify-center rounded-xl text-base transition hover:border-brand-400/40"
          title="切换明暗模式"
        >
          {dark ? '☾' : '☀'}
        </button>
      </div>
    </header>
  )
}

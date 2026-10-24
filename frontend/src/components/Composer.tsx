import { useState } from 'react'

const SUGGESTIONS = [
  {
    label: '429 限流排查',
    text: '系统报 429 错误了，traceID trc-9f3a2c7b1e4d，帮我紧急排查',
  },
  {
    label: '欠费与配额核查',
    text: '我们租户 QPS 被限制了，是不是欠费或者配额用完了？',
  },
  {
    label: '知识库问答',
    text: '如何通过指数退避避免 429 重试风暴？',
  },
]

export function Composer({
  busy,
  onSend,
  onStop,
}: {
  busy: boolean
  onSend: (text: string) => void
  onStop: () => void
}) {
  const [text, setText] = useState('')

  const submit = () => {
    const value = text.trim()
    if (!value || busy) return
    onSend(value)
    setText('')
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            type="button"
            disabled={busy}
            onClick={() => onSend(s.text)}
            className="glass-soft rounded-full px-3 py-1.5 text-[11.5px] text-slate-300 transition hover:border-brand-400/40 hover:text-white disabled:opacity-40"
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="glass flex items-end gap-3 rounded-2xl p-3 transition focus-within:border-brand-400/40">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          rows={1}
          placeholder="告诉 Cots 你的目标，例如：系统报 429 错误了……"
          className="max-h-40 min-h-[28px] flex-1 resize-none bg-transparent text-[14px] leading-7 text-white outline-none placeholder:text-slate-500"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="shrink-0 rounded-xl border border-rose-400/40 bg-rose-400/15 px-4 py-2 text-[13px] font-medium text-rose-200 transition hover:bg-rose-400/25"
          >
            停止
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!text.trim()}
            className="shrink-0 rounded-xl bg-gradient-to-r from-brand-500 to-cyan-500 px-4 py-2 text-[13px] font-medium text-white shadow-glow transition hover:brightness-110 disabled:opacity-30"
          >
            派发任务 ↑
          </button>
        )}
      </div>
    </div>
  )
}

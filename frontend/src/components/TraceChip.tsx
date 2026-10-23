import { useState } from 'react'

const TRACE_RE = /\b(?:trc-[a-z0-9]{8,}|trace[_-]?id)\b/gi

/**
 * Highlights TraceIDs inline and copies on click/Enter.
 * Renders a span (not a button) because this component also appears inside
 * the clickable evidence-card header — nested <button> elements are invalid
 * HTML and trigger React validateDOMNesting warnings.
 */
export function TraceChip({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  if (!TRACE_RE.test(text)) return <span>{text}</span>
  TRACE_RE.lastIndex = 0
  const parts = text.split(TRACE_RE)
  const matches = text.match(TRACE_RE) ?? []

  const copy = (id: string) => (event: React.SyntheticEvent) => {
    event.stopPropagation()
    navigator.clipboard?.writeText(id).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }

  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {matches[i] && (
            <span
              role="button"
              tabIndex={0}
              title="复制 TraceID"
              onClick={copy(matches[i])}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') copy(matches[i])(e)
              }}
              className="trace-chip"
            >
              {copied ? '已复制' : matches[i]}
            </span>
          )}
        </span>
      ))}
    </>
  )
}

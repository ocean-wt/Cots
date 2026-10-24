import type { SSEEvent } from '../types'

export class ChatStreamError extends Error {
  status: number
  code: string
  retryAfter: number | null

  constructor(message: string, status = 0, code = 'NETWORK', retryAfter: number | null = null) {
    super(message)
    this.name = 'ChatStreamError'
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

interface StreamOptions {
  message: string
  onEvent: (event: SSEEvent) => void
  onError: (error: ChatStreamError, reconnecting: boolean) => void
  onClose: () => void
  signal?: AbortSignal
}

interface ParsedEvent {
  id?: string
  event?: string
  data: string
}

function parseBlock(rawBlock: string): ParsedEvent | null {
  // sse-starlette frames events with CRLF; accept both CRLF and LF.
  const block = rawBlock.replace(/\r\n/g, '\n').replace(/\r/g, '')
  const lines = block.split('\n')
  let id: string | undefined
  let event: string | undefined
  const dataLines: string[] = []
  for (const line of lines) {
    if (line.startsWith('id:')) id = line.slice(3).trim()
    else if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!event || dataLines.length === 0) return null
  return { id, event, data: dataLines.join('\n') }
}

async function readStream(
  response: Response,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new ChatStreamError('响应没有响应体')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    if (signal?.aborted) {
      await reader.cancel()
      return
    }
    const { value, done } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    const blocks = buffer.split(/\n\n/)
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const parsed = parseBlock(block)
      if (!parsed) continue
      try {
        const payload = JSON.parse(parsed.data)
        onEvent({
          seq: parsed.id ? Number(parsed.id) : 0,
          event: parsed.event as SSEEvent['event'],
          data: payload,
        } as SSEEvent)
      } catch {
        // ignore keep-alive / malformed ping lines
      }
    }
  }
}

/**
 * POST SSE with reconnect. Network failures replay missed events from the
 * gateway's Redis-backed resume endpoint. 4xx responses (auth, 413, 429) are
 * client errors and are surfaced immediately without a pointless reconnect.
 */
export async function streamChat(options: StreamOptions): Promise<void> {
  const { message, onEvent, onError, onClose, signal } = options
  let runId: string | null = null
  let lastSeq = 0
  let attempt = 0

  const handle = (event: SSEEvent) => {
    lastSeq = Math.max(lastSeq, event.seq)
    const anyData = event.data as { run_id?: string }
    if (anyData.run_id) runId = anyData.run_id
    onEvent(event)
  }

  while (true) {
    try {
      let response: Response
      if (attempt === 0) {
        response = await fetch('/api/v1/chat/stream', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Last-Event-ID': String(lastSeq),
          },
          body: JSON.stringify({ message }),
          signal,
        })
      } else {
        const url = `/api/v1/chat/stream/${runId ?? ''}/resume?last_event_id=${lastSeq}`
        response = await fetch(url, { headers: { Accept: 'text/event-stream' }, signal })
      }
      if (!response.ok) {
        const retryAfter = response.headers.get('Retry-After')
        let detail = `上游响应 ${response.status}`
        try {
          const body = await response.json()
          detail = body.detail ?? body.error ?? detail
          if (typeof detail === 'object') detail = JSON.stringify(detail)
        } catch {
          /* non-JSON error body */
        }
        throw new ChatStreamError(
          String(detail),
          response.status,
          response.status === 429 ? 'RATE_LIMITED' : `HTTP_${response.status}`,
          retryAfter ? Number(retryAfter) : null,
        )
      }
      attempt = 0
      await readStream(response, handle, signal)
      onClose()
      return
    } catch (err) {
      if (signal?.aborted) {
        onClose()
        return
      }
      const streamErr =
        err instanceof ChatStreamError
          ? err
          : new ChatStreamError((err as Error).message ?? '网络中断')
      // 4xx are deterministic client errors: never retry, surface once.
      if (streamErr.status >= 400 && streamErr.status < 500) {
        onError(streamErr, false)
        onClose()
        return
      }
      const canResume = attempt < 5 && runId !== null
      onError(streamErr, canResume)
      if (!canResume) {
        onClose()
        return
      }
      attempt += 1
      await new Promise((r) => setTimeout(r, Math.min(800 * 2 ** attempt, 5000)))
    }
  }
}

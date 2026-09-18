import {
  API_BASE,
  ChatJob,
  JobEvent,
  JobSnapshot,
  WebUIChatCompletionRequest,
  parseApiError,
  webuiHeaders
} from './api'

export function isActiveJob(job?: ChatJob | null): boolean {
  return !!job && ['queued', 'running', 'cancelling'].includes(job.state)
}

async function requestJob(
  path: string,
  token: string,
  init: RequestInit = {}
): Promise<Response> {
  const response = await fetch(`${API_BASE}/v1/jobs${path}`, {
    ...init,
    headers: { ...webuiHeaders(token), ...init.headers }
  })
  if (!response.ok)
    throw await parseApiError(
      response,
      `Task request failed: ${response.status}`
    )
  return response
}

export async function submitJob(
  request: WebUIChatCompletionRequest,
  token: string,
  key: string
): Promise<ChatJob> {
  const response = await requestJob('', token, {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    body: JSON.stringify(request)
  })
  return response.json()
}

export async function getJob(
  id: string,
  token: string,
  signal?: AbortSignal
): Promise<ChatJob> {
  return (
    await requestJob(`/${encodeURIComponent(id)}?include_output=true`, token, {
      signal
    })
  ).json()
}

export async function listJobs(
  token: string,
  signal?: AbortSignal
): Promise<ChatJob[]> {
  const response = await requestJob('?limit=200', token, { signal })
  return (await response.json()).data
}

export async function waitJobResult(
  id: string,
  token: string,
  signal?: AbortSignal
): Promise<ChatJob> {
  const response = await fetch(
    `${API_BASE}/v1/jobs/${encodeURIComponent(id)}/result?wait_seconds=20`,
    {
      headers: webuiHeaders(token),
      signal
    }
  )
  if (!response.ok) return getJob(id, token, signal)
  const data: ChatJob & { result?: JobSnapshot } = await response.json()
  return { ...data, snapshot: data.result || data.snapshot }
}

export async function cancelJob(id: string, token: string): Promise<ChatJob> {
  return (
    await requestJob(`/${encodeURIComponent(id)}/cancel`, token, {
      method: 'POST'
    })
  ).json()
}

export async function uploadAttachment(
  file: File,
  token: string,
  signal?: AbortSignal
): Promise<string> {
  if (file.size > 20 * 1024 * 1024)
    throw new Error('Each file must be at most 20 MiB')
  const form = new FormData()
  form.append('file', file)
  form.append('purpose', 'assistants')
  const response = await fetch(`${API_BASE}/v1/files`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
    signal
  })
  if (!response.ok) throw await parseApiError(response, 'File upload failed')
  return (await response.json()).id
}

export async function* jobEvents(
  id: string,
  token: string,
  signal: AbortSignal
): AsyncGenerator<JobEvent> {
  const response = await requestJob(
    `/${encodeURIComponent(id)}/events`,
    token,
    { signal }
  )
  const reader = response.body?.getReader()
  if (!reader) throw new Error('No task event stream')
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = false
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      if (buffer.length > 4 * 1024 * 1024)
        throw new Error('Task event exceeded the size limit')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (data) {
          const event = JSON.parse(data) as JobEvent
          if (event.type === 'terminal') terminal = true
          yield event
          if (terminal) return
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
    if (!terminal)
      throw new Error('Task observation disconnected; reconnecting')
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

export function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const abort = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, ms)
    signal.addEventListener('abort', abort, { once: true })
  })
}

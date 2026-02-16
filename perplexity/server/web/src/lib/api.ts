const API_BASE = window.location.origin

export interface PoolStatus {
  total: number
  available: number
  mode: string
  clients: ClientInfo[]
}

export interface ClientInfo {
  id: string
  enabled: boolean
  available: boolean
  state: string
  weight: number
  request_count: number
  fail_count: number
  pro_fail_count: number
  last_heartbeat_at: string | null
}

export interface HeartbeatConfig {
  enable: boolean
  question: string
  interval: number
  tg_bot_token: string | null
  tg_chat_id: string | null
}

export interface FallbackConfig {
  fallback_to_auto: boolean
}

export interface IncognitoConfig {
  enabled: boolean
}

export interface ApiResponse<T = unknown> {
  status: 'ok' | 'error'
  message?: string
  error?: string
  data?: T
  config?: T
}

export async function fetchPoolStatus(): Promise<PoolStatus> {
  const resp = await fetch(`${API_BASE}/pool/status`)
  return resp.json()
}

export async function verifyAdminToken(token: string): Promise<boolean> {
  const resp = await fetch(`${API_BASE}/logs/tail?lines=1`, {
    headers: {
      'X-Admin-Token': token,
    },
  })
  return resp.ok
}

export async function fetchHeartbeatConfig(adminToken: string): Promise<ApiResponse<HeartbeatConfig>> {
  const resp = await fetch(`${API_BASE}/heartbeat/config`, {
    headers: {
      'X-Admin-Token': adminToken,
    },
  })
  return resp.json()
}

export async function fetchFallbackConfig(): Promise<ApiResponse<FallbackConfig>> {
  const resp = await fetch(`${API_BASE}/fallback/config`)
  return resp.json()
}

export async function updateFallbackConfig(
  config: Partial<FallbackConfig>,
  adminToken: string
): Promise<ApiResponse<FallbackConfig>> {
  const resp = await fetch(`${API_BASE}/fallback/config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Token': adminToken,
    },
    body: JSON.stringify(config),
  })
  return resp.json()
}

export async function fetchIncognitoConfig(): Promise<ApiResponse<IncognitoConfig>> {
  const resp = await fetch(`${API_BASE}/incognito/config`)
  return resp.json()
}

export async function updateIncognitoConfig(
  config: Partial<IncognitoConfig>,
  adminToken: string
): Promise<ApiResponse<IncognitoConfig>> {
  const resp = await fetch(`${API_BASE}/incognito/config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Token': adminToken,
    },
    body: JSON.stringify(config),
  })
  return resp.json()
}

export async function apiCall(
  action: string,
  params: Record<string, unknown> = {},
  adminToken?: string
): Promise<ApiResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (adminToken) {
    headers['X-Admin-Token'] = adminToken
  }

  const url = action.startsWith('heartbeat')
    ? `${API_BASE}/${action}`
    : `${API_BASE}/pool/${action}`

  const resp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(params),
  })
  return resp.json()
}

export async function updateHeartbeatConfig(
  config: Partial<HeartbeatConfig>,
  adminToken: string
): Promise<ApiResponse<HeartbeatConfig>> {
  const resp = await fetch(`${API_BASE}/heartbeat/config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Token': adminToken,
    },
    body: JSON.stringify(config),
  })
  return resp.json()
}

// ============ Logs API ============

export interface LogsResponse {
  status: 'ok' | 'error'
  message?: string
  lines?: string[]
  total_lines?: number
  file_size?: number
}

export async function fetchLogs(
  adminToken: string,
  lines: number = 100
): Promise<LogsResponse> {
  const resp = await fetch(`${API_BASE}/logs/tail?lines=${lines}`, {
    headers: {
      'X-Admin-Token': adminToken,
    },
  })
  return resp.json()
}

// ============ Token Config Export/Import API ============

export interface TokenConfig {
  id: string
  csrf_token: string
  session_token: string
}

export async function downloadSingleTokenConfig(
  clientId: string,
  adminToken: string
): Promise<TokenConfig[]> {
  const resp = await fetch(`${API_BASE}/pool/export/${encodeURIComponent(clientId)}`, {
    headers: {
      'X-Admin-Token': adminToken,
    },
  })
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ message: resp.statusText }))
    throw new Error(error.message || `Export failed: ${resp.status}`)
  }
  return resp.json()
}

export async function importTokenConfig(
  tokens: TokenConfig[],
  adminToken: string
): Promise<ApiResponse> {
  const resp = await fetch(`${API_BASE}/pool/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Token': adminToken,
    },
    body: JSON.stringify(tokens),
  })
  return resp.json()
}

// ============ OAI Compatible API ============

export interface Source {
  url: string
  title?: string
}

export interface OAIModel {
  id: string
  object: string
  created: number
  owned_by: string
}

export interface OAIModelsResponse {
  object: string
  data: OAIModel[]
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
  sources?: Source[]
}

export interface ChatCompletionRequest {
  model: string
  messages: ChatMessage[]
  stream?: boolean
  temperature?: number
  max_tokens?: number
}

export interface ChatCompletionChoice {
  index: number
  message: ChatMessage
  finish_reason: string | null
}

export interface ChatCompletionResponse {
  id: string
  object: string
  created: number
  model: string
  choices: ChatCompletionChoice[]
  sources?: Source[]
}

export interface ChatCompletionChunkDelta {
  role?: string
  content?: string
}

export interface ChatCompletionChunk {
  id: string
  object: string
  created: number
  model: string
  choices: {
    index: number
    delta: ChatCompletionChunkDelta
    finish_reason: string | null
  }[]
  sources?: Source[]
}

export async function fetchOAIModels(apiToken: string): Promise<OAIModelsResponse> {
  const resp = await fetch(`${API_BASE}/v1/models`, {
    headers: {
      Authorization: `Bearer ${apiToken}`,
    },
  })
  if (!resp.ok) {
    throw new Error(`Failed to fetch models: ${resp.status}`)
  }
  return resp.json()
}

// Helper to strip sources from messages before sending to API
function cleanMessagesForRequest(
  messages: ChatMessage[]
): Array<{ role: string; content: string }> {
  return messages.map(({ role, content }) => ({ role, content }))
}

export async function chatCompletion(
  request: ChatCompletionRequest,
  apiToken: string
): Promise<ChatCompletionResponse> {
  const cleanedRequest = {
    ...request,
    messages: cleanMessagesForRequest(request.messages),
    stream: false,
  }
  const resp = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiToken}`,
    },
    body: JSON.stringify(cleanedRequest),
  })
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ error: { message: resp.statusText } }))
    throw new Error(error.error?.message || `API error: ${resp.status}`)
  }
  return resp.json()
}

export async function* chatCompletionStream(
  request: ChatCompletionRequest,
  apiToken: string
): AsyncGenerator<ChatCompletionChunk, void, unknown> {
  const cleanedRequest = {
    ...request,
    messages: cleanMessagesForRequest(request.messages),
    stream: true,
  }
  const resp = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiToken}`,
    },
    body: JSON.stringify(cleanedRequest),
  })

  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ error: { message: resp.statusText } }))
    throw new Error(error.error?.message || `API error: ${resp.status}`)
  }

  const reader = resp.body?.getReader()
  if (!reader) {
    throw new Error('No response body')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed || !trimmed.startsWith('data: ')) continue
      const data = trimmed.slice(6)
      if (data === '[DONE]') return
      try {
        yield JSON.parse(data) as ChatCompletionChunk
      } catch {
        // Skip invalid JSON
      }
    }
  }
}

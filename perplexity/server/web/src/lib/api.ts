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

export interface ApiResponse<T = unknown> {
  status: 'ok' | 'error'
  message?: string
  data?: T
  config?: T
}

export async function fetchPoolStatus(): Promise<PoolStatus> {
  const resp = await fetch(`${API_BASE}/pool/status`)
  return resp.json()
}

export async function fetchHeartbeatConfig(): Promise<ApiResponse<HeartbeatConfig>> {
  const resp = await fetch(`${API_BASE}/heartbeat/config`)
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

import type { TokenConfig } from './api'

export type TokenAuth = Pick<
  TokenConfig,
  'csrf_token' | 'session_token' | 'cookies'
>

const LEGACY_CSRF = 'next-auth.csrf-token'
const LEGACY_SESSION = '__Secure-next-auth.session-token'
const SESSION_PREFIX = '__Secure-pplx.session.'
const LAST_ACTIVE = '__Host-pplx-last-active-account'

// Mirrors build_account_cookies: a legacy pair or a non-empty cookie map.
export function hasAccountAuth(token: TokenAuth): boolean {
  return Boolean(
    (token.csrf_token && token.session_token) ||
      (token.cookies && Object.values(token.cookies).some(Boolean))
  )
}

function parseCookieInput(input: string): Record<string, string> {
  const text = input.trim().replace(/^cookie:\s*/i, '')
  if (text.startsWith('{')) {
    try {
      const parsed: unknown = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return Object.fromEntries(
          Object.entries(parsed).filter(
            (e): e is [string, string] => typeof e[1] === 'string'
          )
        )
      }
    } catch {
      // Fall through: not JSON after all.
    }
    return {}
  }
  const cookies: Record<string, string> = {}
  for (const part of text.split(/;|\n/)) {
    const eq = part.indexOf('=')
    if (eq > 0) cookies[part.slice(0, eq).trim()] = part.slice(eq + 1).trim()
  }
  return cookies
}

/**
 * Extract Perplexity auth from a pasted Cookie header ("a=b; c=d") or JSON object.
 * Transient cookies such as __cf_bm are dropped. Returns null without a session cookie.
 */
export function parseAuthCookies(input: string): TokenAuth | null {
  const auth: TokenAuth = {}
  const cookies: Record<string, string> = {}
  for (const [name, value] of Object.entries(parseCookieInput(input))) {
    if (!value) continue
    if (name === LEGACY_CSRF) auth.csrf_token = value
    else if (name === LEGACY_SESSION) auth.session_token = value
    else if (name.startsWith(SESSION_PREFIX) || name === LAST_ACTIVE)
      cookies[name] = value
  }
  if (Object.keys(cookies).length) auth.cookies = cookies
  const hasSession = Object.keys(cookies).some((name) =>
    name.startsWith(SESSION_PREFIX)
  )
  return hasSession || (auth.csrf_token && auth.session_token) ? auth : null
}

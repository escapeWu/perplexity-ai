import { describe, expect, it } from 'vitest'
import { hasAccountAuth, parseAuthCookies } from './tokenCookies'

describe('parseAuthCookies', () => {
  it('keeps session cookies from a Cookie header and drops transient ones', () => {
    const header =
      'Cookie: __cf_bm=x; __Secure-pplx.session.abc=tok=en; __Host-pplx-last-active-account=abc'
    expect(parseAuthCookies(header)).toEqual({
      cookies: {
        '__Secure-pplx.session.abc': 'tok=en',
        '__Host-pplx-last-active-account': 'abc'
      }
    })
  })

  it('accepts a JSON object', () => {
    expect(
      parseAuthCookies('{"__Secure-pplx.session.abc": "tok", "other": "x"}')
    ).toEqual({
      cookies: { '__Secure-pplx.session.abc': 'tok' }
    })
  })

  it('maps legacy next-auth cookies to the token pair', () => {
    expect(
      parseAuthCookies(
        'next-auth.csrf-token=c; __Secure-next-auth.session-token=s'
      )
    ).toEqual({ csrf_token: 'c', session_token: 's' })
  })

  it('rejects input without a session cookie', () => {
    expect(
      parseAuthCookies('__Host-pplx-last-active-account=abc; __cf_bm=x')
    ).toBeNull()
    expect(parseAuthCookies('{not json')).toBeNull()
  })
})

describe('hasAccountAuth', () => {
  it('requires the legacy pair or non-empty cookies', () => {
    expect(hasAccountAuth({ csrf_token: 'c', session_token: 's' })).toBe(true)
    expect(hasAccountAuth({ cookies: { a: 'b' } })).toBe(true)
    expect(hasAccountAuth({ csrf_token: 'c' })).toBe(false)
    expect(hasAccountAuth({ cookies: { a: '' } })).toBe(false)
  })
})

import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useVersionCheck } from './useVersionCheck'

const LEGACY_CACHE_KEY = 'perplexity_version_check'
const CACHE_KEY = 'perplexity_version_check:v2'

function releaseResponse(tagName: string, ok = true) {
  return {
    ok,
    status: ok ? 200 : 503,
    json: vi.fn().mockResolvedValue({
      tag_name: tagName,
      html_url: `https://github.com/escapeWu/perplexity-ai/releases/tag/${tagName}`
    })
  } as unknown as Response
}

describe('useVersionCheck', () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not show the current release as an available update', async () => {
    localStorage.setItem(
      LEGACY_CACHE_KEY,
      JSON.stringify({
        timestamp: Date.now(),
        data: {
          hasUpdate: true,
          latestVersion: `v${__APP_VERSION__}`,
          releaseUrl: 'https://example.test/stale',
          loading: false,
          error: false
        }
      })
    )
    const fetchMock = vi
      .fn()
      .mockResolvedValue(releaseResponse(`v${__APP_VERSION__}`))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useVersionCheck())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.hasUpdate).toBe(false)
    expect(result.current.latestVersion).toBe(`v${__APP_VERSION__}`)
    expect(localStorage.getItem(LEGACY_CACHE_KEY)).toBeNull()
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('caches release facts instead of a stale hasUpdate decision', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(releaseResponse(`v${__APP_VERSION__}`))
    vi.stubGlobal('fetch', fetchMock)

    const firstHook = renderHook(() => useVersionCheck())
    await waitFor(() => expect(firstHook.result.current.loading).toBe(false))
    firstHook.unmount()

    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || '{}')
    expect(cached.release.tag_name).toBe(`v${__APP_VERSION__}`)
    expect(cached).not.toHaveProperty('hasUpdate')
    expect(cached.release).not.toHaveProperty('hasUpdate')

    const secondHook = renderHook(() => useVersionCheck())
    await waitFor(() => expect(secondHook.result.current.loading).toBe(false))
    expect(secondHook.result.current.hasUpdate).toBe(false)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('shows a newer valid release and uses its release URL', async () => {
    const tagName = 'v999.0.0'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(releaseResponse(tagName)))

    const { result } = renderHook(() => useVersionCheck())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.hasUpdate).toBe(true)
    expect(result.current.latestVersion).toBe(tagName)
    expect(result.current.releaseUrl).toContain(`/releases/tag/${tagName}`)
    expect(result.current.error).toBe(false)
  })

  it('ignores malformed cache data and refreshes from GitHub', async () => {
    localStorage.setItem(CACHE_KEY, '{"schema":2,"repository":"wrong"}')
    const fetchMock = vi
      .fn()
      .mockResolvedValue(releaseResponse(`v${__APP_VERSION__}`))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useVersionCheck())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.hasUpdate).toBe(false)
    expect(result.current.error).toBe(false)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('fails closed when GitHub cannot provide a release', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(releaseResponse('', false))
    )

    const { result } = renderHook(() => useVersionCheck())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.hasUpdate).toBe(false)
    expect(result.current.error).toBe(true)
  })

  it('aborts an in-flight request when the component unmounts', async () => {
    let requestSignal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        requestSignal = init?.signal || undefined
        return new Promise((_resolve, reject) => {
          requestSignal?.addEventListener(
            'abort',
            () =>
              reject(
                new DOMException('The operation was aborted', 'AbortError')
              ),
            { once: true }
          )
        })
      })
    )

    const { unmount } = renderHook(() => useVersionCheck())
    await waitFor(() => expect(requestSignal).toBeDefined())
    unmount()

    expect(requestSignal?.aborted).toBe(true)
  })
})

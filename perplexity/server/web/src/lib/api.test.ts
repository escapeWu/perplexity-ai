import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatCompletionStream } from './api'

describe('chatCompletionStream', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('surfaces an SSE error and releases the response reader', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    const read = vi.fn().mockResolvedValueOnce({
      done: false,
      value: new TextEncoder().encode(
        'data: {"error":{"message":"upstream interrupted","type":"api_error"}}\n\n'
      )
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: {
          getReader: () => ({ read, cancel, releaseLock })
        }
      })
    )

    const stream = chatCompletionStream(
      {
        model: 'perplexity-search',
        messages: [{ role: 'user', content: 'hello' }]
      },
      'test-token'
    )

    await expect(stream.next()).rejects.toThrow('upstream interrupted')
    expect(cancel).toHaveBeenCalledOnce()
    expect(releaseLock).toHaveBeenCalledOnce()
  })
})

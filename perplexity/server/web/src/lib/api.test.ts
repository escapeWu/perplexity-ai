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

  it('requests progress by default and yields progress chunks', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    const read = vi.fn().mockResolvedValueOnce({
      done: false,
      value: new TextEncoder().encode(
        [
          'data: {"id":"chatcmpl-test","object":"chat.completion.chunk","created":1,"model":"perplexity-search","choices":[{"index":0,"delta":{},"finish_reason":null}],"perplexity_progress":{"id":"progress-1","stage":"search_web","status":"running","label":"Searching the web"}}',
          '',
          'data: [DONE]',
          '',
        ].join('\n')
      ),
    })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({ read, cancel, releaseLock }),
      },
    })
    vi.stubGlobal('fetch', fetchMock)

    const stream = chatCompletionStream(
      {
        model: 'perplexity-search',
        messages: [{ role: 'user', content: 'hello' }],
      },
      'test-token'
    )

    const first = await stream.next()
    const done = await stream.next()

    expect(first.value?.perplexity_progress).toEqual({
      id: 'progress-1',
      stage: 'search_web',
      status: 'running',
      label: 'Searching the web',
    })
    expect(done.done).toBe(true)
    const requestBody = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(requestBody.perplexity).toEqual({ include_progress: true })
    expect(cancel).toHaveBeenCalledOnce()
    expect(releaseLock).toHaveBeenCalledOnce()
  })
})

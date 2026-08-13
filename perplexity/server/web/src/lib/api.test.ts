import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createWebUISession,
  deleteWebUISession,
  renameWebUISession,
  webuiChatCompletion,
  webuiChatCompletionStream,
  chatCompletionStream
} from './api'

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
          ''
        ].join('\n')
      )
    })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({ read, cancel, releaseLock })
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    const stream = chatCompletionStream(
      {
        model: 'perplexity-search',
        messages: [{ role: 'user', content: 'hello' }]
      },
      'test-token'
    )

    const first = await stream.next()
    const done = await stream.next()

    expect(first.value?.perplexity_progress).toEqual({
      id: 'progress-1',
      stage: 'search_web',
      status: 'running',
      label: 'Searching the web'
    })
    expect(done.done).toBe(true)
    const requestBody = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(requestBody.perplexity).toEqual({ include_progress: true })
    expect(cancel).toHaveBeenCalledOnce()
    expect(releaseLock).toHaveBeenCalledOnce()
  })

  it('yields an SSE chunk before the response reader completes', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    let finishRead!: (value: { done: boolean; value?: Uint8Array }) => void
    const pendingRead = new Promise<{ done: boolean; value?: Uint8Array }>(
      (resolve) => {
        finishRead = resolve
      }
    )
    const read = vi
      .fn()
      .mockResolvedValueOnce({
        done: false,
        value: new TextEncoder().encode(
          'data: {"id":"chatcmpl-test","object":"chat.completion.chunk","created":1,"model":"perplexity-search","choices":[{"index":0,"delta":{"content":"Hel"},"finish_reason":null}]}\n\n'
        )
      })
      .mockImplementationOnce(() => pendingRead)
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

    const first = await stream.next()
    expect(first.value?.choices[0].delta.content).toBe('Hel')
    expect(read).toHaveBeenCalledOnce()

    const donePromise = stream.next()
    finishRead({
      done: false,
      value: new TextEncoder().encode('data: [DONE]\n\n')
    })
    await expect(donePromise).resolves.toEqual({ value: undefined, done: true })
    expect(cancel).toHaveBeenCalledOnce()
    expect(releaseLock).toHaveBeenCalledOnce()
  })
})

describe('WebUI session API', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends only the current turn to the dedicated session endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'chatcmpl-test',
        object: 'chat.completion',
        created: 1,
        model: 'perplexity-search',
        choices: []
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    await webuiChatCompletion(
      {
        session_id: 'sess_00000000000000000000000000000001',
        model: 'perplexity-search',
        messages: [{ role: 'user', content: 'current turn' }]
      },
      'test-token'
    )

    expect(fetchMock.mock.calls[0][0]).toContain('/v1/webui/chat/completions')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toMatchObject({
      session_id: 'sess_00000000000000000000000000000001',
      stream: false,
      messages: [{ role: 'user', content: 'current turn' }]
    })
  })

  it('preserves the session id and progress option for streaming', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined)
    const releaseLock = vi.fn()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn().mockResolvedValueOnce({
            done: false,
            value: new TextEncoder().encode('data: [DONE]\n\n')
          }),
          cancel,
          releaseLock
        })
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    const stream = webuiChatCompletionStream(
      {
        session_id: 'sess_00000000000000000000000000000001',
        model: 'perplexity-search',
        messages: [{ role: 'user', content: 'current turn' }]
      },
      'test-token'
    )
    await stream.next()

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.session_id).toBe('sess_00000000000000000000000000000001')
    expect(body.stream).toBe(true)
    expect(body.perplexity).toEqual({ include_progress: true })
  })

  it('uses authenticated create, rename, and delete routes', async () => {
    const response = {
      id: 'sess_00000000000000000000000000000001',
      title: 'New chat',
      bound_client_id: null,
      model: null,
      created_at: 1,
      updated_at: 1
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => response
    })
    vi.stubGlobal('fetch', fetchMock)

    await createWebUISession('test-token')
    await renameWebUISession(response.id, 'Renamed', 'test-token')
    await deleteWebUISession(response.id, 'test-token')

    expect(fetchMock.mock.calls.map((call) => call[1].method)).toEqual([
      'POST',
      'PATCH',
      'DELETE'
    ])
    expect(fetchMock.mock.calls[1][1].body).toBe(
      JSON.stringify({ title: 'Renamed' })
    )
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe(
      'Bearer test-token'
    )
  })
})

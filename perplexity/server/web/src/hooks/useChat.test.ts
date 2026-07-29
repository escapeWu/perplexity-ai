import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatCompletion, chatCompletionStream } from 'lib/api'
import type { ChatCompletionChunk, PerplexityProgress } from 'lib/api'
import { useChat } from './useChat'

vi.mock('lib/api', () => ({
  fetchOAIModels: vi.fn(),
  chatCompletion: vi.fn(),
  chatCompletionStream: vi.fn(),
}))

function streamChunk(
  content?: string,
  progress?: PerplexityProgress
): ChatCompletionChunk {
  return {
    id: 'chatcmpl-test',
    object: 'chat.completion.chunk',
    created: 1,
    model: 'perplexity-search',
    choices: [
      {
        index: 0,
        delta: content ? { content } : {},
        finish_reason: null,
      },
    ],
    ...(progress ? { perplexity_progress: progress } : {}),
  }
}

describe('useChat cancellation', () => {
  afterEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('passes an abort signal to the stream and stops without showing an error', async () => {
    let requestSignal: AbortSignal | undefined
    vi.mocked(chatCompletionStream).mockImplementation((_request, _apiToken, signal) => {
      requestSignal = signal
      return (async function* () {
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'running',
          label: 'Searching the web',
        })
        await new Promise<void>((_resolve, reject) => {
          signal?.addEventListener(
            'abort',
            () => reject(new DOMException('The operation was aborted', 'AbortError')),
            { once: true }
          )
        })
      })()
    })

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))

    let sendPromise!: Promise<void>
    act(() => {
      sendPromise = result.current.sendMessage('hello')
    })

    await waitFor(() => expect(chatCompletionStream).toHaveBeenCalledOnce())
    await waitFor(() =>
      expect(result.current.messages.at(-1)?.progress?.[0].status).toBe('running')
    )
    act(() => result.current.stopStreaming())
    await act(async () => {
      await sendPromise
    })

    expect(requestSignal?.aborted).toBe(true)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.messages.at(-1)?.progress?.[0].status).toBe('cancelled')
    expect(
      result.current.messages.some(
        (message) =>
          message.role === 'assistant' &&
          typeof message.content === 'string' &&
          message.content.startsWith('Error:')
      )
    ).toBe(false)
  })

  it('stores progress updates alongside streamed answer content', async () => {
    vi.mocked(chatCompletionStream).mockImplementation(() =>
      (async function* () {
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'running',
          label: 'Searching the web',
          detail: { queries: ['glass frog transparency'], query_count: 1 },
        })
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'completed',
          label: 'Searching the web',
          detail: { queries: ['glass frog transparency'], query_count: 1 },
        })
        yield streamChunk(undefined, {
          id: 'progress-2',
          stage: 'final',
          status: 'running',
          label: 'Writing answer',
        })
        yield streamChunk('complete answer')
        yield streamChunk(undefined, {
          id: 'progress-2',
          stage: 'final',
          status: 'completed',
          label: 'Writing answer',
        })
      })()
    )

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    const assistant = result.current.messages.at(-1)
    expect(assistant?.content).toBe('complete answer')
    expect(assistant?.progress).toEqual([
      {
        id: 'progress-1',
        stage: 'search_web',
        status: 'completed',
        label: 'Searching the web',
        detail: { queries: ['glass frog transparency'], query_count: 1 },
      },
      {
        id: 'progress-2',
        stage: 'final',
        status: 'completed',
        label: 'Writing answer',
      },
    ])
  })

  it('keeps partial content and marks active progress failed on stream errors', async () => {
    vi.mocked(chatCompletionStream).mockImplementation(() =>
      (async function* () {
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'running',
          label: 'Searching the web',
        })
        yield streamChunk('partial answer')
        throw new Error('upstream interrupted')
      })()
    )

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    const assistant = result.current.messages.at(-1)
    expect(assistant?.content).toBe('partial answer')
    expect(assistant?.error).toBe('upstream interrupted')
    expect(assistant?.progress?.[0].status).toBe('failed')
    expect(result.current.error).toBe('upstream interrupted')
  })

  it('uses the complete response API when streaming is disabled', async () => {
    vi.mocked(chatCompletion).mockResolvedValue({
      id: 'chatcmpl-test',
      object: 'chat.completion',
      created: 1,
      model: 'perplexity-search',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: 'complete answer' },
          finish_reason: 'stop',
        },
      ],
    })

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    act(() => result.current.setStreamEnabled(false))
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    expect(chatCompletion).toHaveBeenCalledOnce()
    expect(chatCompletionStream).not.toHaveBeenCalled()
    expect(result.current.messages.at(-1)?.content).toBe('complete answer')
  })
})

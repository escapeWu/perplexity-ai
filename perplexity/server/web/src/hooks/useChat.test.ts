import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createWebUISession,
  fetchOAIModels,
  getWebUISession,
  listWebUISessions,
  webuiChatCompletion,
  webuiChatCompletionStream
} from 'lib/api'
import type {
  ChatCompletionChunk,
  ChatSession,
  OAIModel,
  PerplexityProgress
} from 'lib/api'
import { useChat } from './useChat'

vi.mock('lib/api', () => ({
  fetchOAIModels: vi.fn(),
  createWebUISession: vi.fn(),
  listWebUISessions: vi.fn(),
  getWebUISession: vi.fn(),
  renameWebUISession: vi.fn(),
  deleteWebUISession: vi.fn(),
  webuiChatCompletion: vi.fn(),
  webuiChatCompletionStream: vi.fn()
}))

const session: ChatSession = {
  id: 'sess_00000000000000000000000000000001',
  title: 'New chat',
  bound_client_id: null,
  model: null,
  created_at: 1,
  updated_at: 1
}

const modelCatalog: OAIModel[] = [
  {
    id: 'gpt-5-6-terra',
    object: 'model',
    created: 1700000000,
    owned_by: 'perplexity',
    label: 'GPT-5.6 Terra',
    description: 'Versatile model',
    subscription_tier: 'pro',
    mode: 'pro',
    base_model_id: 'gpt-5-6-terra',
    thinking_model_id: 'gpt-5-6-terra-thinking',
    supports_thinking: true,
    thinking: false,
    thinking_only: false
  },
  {
    id: 'gpt-5-6-terra-thinking',
    object: 'model',
    created: 1700000000,
    owned_by: 'perplexity',
    label: 'GPT-5.6 Terra Thinking',
    description: 'Versatile model',
    subscription_tier: 'pro',
    mode: 'reasoning',
    base_model_id: 'gpt-5-6-terra',
    thinking_model_id: 'gpt-5-6-terra-thinking',
    supports_thinking: true,
    thinking: true,
    thinking_only: false
  }
]

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
        finish_reason: null
      }
    ],
    ...(progress ? { perplexity_progress: progress } : {})
  }
}

describe('useChat cancellation', () => {
  beforeEach(() => {
    vi.mocked(fetchOAIModels).mockResolvedValue({
      object: 'list',
      data: modelCatalog
    })
    vi.mocked(createWebUISession).mockResolvedValue(session)
    vi.mocked(listWebUISessions).mockResolvedValue({
      object: 'list',
      data: [session]
    })
    vi.mocked(getWebUISession).mockResolvedValue({ ...session, messages: [] })
  })

  afterEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('passes an abort signal to the stream and stops without showing an error', async () => {
    let requestSignal: AbortSignal | undefined
    vi.mocked(webuiChatCompletionStream).mockImplementation(
      (_request, _apiToken, signal) => {
        requestSignal = signal
        return (async function* () {
          yield streamChunk(undefined, {
            id: 'progress-1',
            stage: 'search_web',
            status: 'running',
            label: 'Searching the web'
          })
          await new Promise<void>((_resolve, reject) => {
            signal?.addEventListener(
              'abort',
              () =>
                reject(
                  new DOMException('The operation was aborted', 'AbortError')
                ),
              { once: true }
            )
          })
        })()
      }
    )

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))

    let sendPromise!: Promise<void>
    act(() => {
      sendPromise = result.current.sendMessage('hello')
    })

    await waitFor(() =>
      expect(webuiChatCompletionStream).toHaveBeenCalledOnce()
    )
    await waitFor(() =>
      expect(result.current.messages.at(-1)?.progress?.[0].status).toBe(
        'running'
      )
    )
    act(() => result.current.stopStreaming())
    await act(async () => {
      await sendPromise
    })

    expect(requestSignal?.aborted).toBe(true)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.messages.at(-1)?.progress?.[0].status).toBe(
      'cancelled'
    )
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
    vi.mocked(webuiChatCompletionStream).mockImplementation(() =>
      (async function* () {
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'running',
          label: 'Searching the web',
          detail: { queries: ['glass frog transparency'], query_count: 1 }
        })
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'completed',
          label: 'Searching the web',
          detail: { queries: ['glass frog transparency'], query_count: 1 }
        })
        yield streamChunk(undefined, {
          id: 'progress-2',
          stage: 'final',
          status: 'running',
          label: 'Writing answer'
        })
        yield streamChunk('complete answer')
        yield streamChunk(undefined, {
          id: 'progress-2',
          stage: 'final',
          status: 'completed',
          label: 'Writing answer'
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
        detail: { queries: ['glass frog transparency'], query_count: 1 }
      },
      {
        id: 'progress-2',
        stage: 'final',
        status: 'completed',
        label: 'Writing answer'
      }
    ])
  })

  it('keeps partial content and marks active progress failed on stream errors', async () => {
    vi.mocked(webuiChatCompletionStream).mockImplementation(() =>
      (async function* () {
        yield streamChunk(undefined, {
          id: 'progress-1',
          stage: 'search_web',
          status: 'running',
          label: 'Searching the web'
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
    vi.mocked(webuiChatCompletion).mockResolvedValue({
      id: 'chatcmpl-test',
      object: 'chat.completion',
      created: 1,
      model: 'perplexity-search',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: 'complete answer' },
          finish_reason: 'stop'
        }
      ]
    })

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    act(() => result.current.setStreamEnabled(false))
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    expect(webuiChatCompletion).toHaveBeenCalledOnce()
    expect(webuiChatCompletionStream).not.toHaveBeenCalled()
    expect(result.current.messages.at(-1)?.content).toBe('complete answer')
  })

  it('sends only the current turn with the active session id', async () => {
    vi.mocked(webuiChatCompletion).mockResolvedValue({
      id: 'chatcmpl-test',
      object: 'chat.completion',
      created: 1,
      model: 'perplexity-search',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: 'answer' },
          finish_reason: 'stop'
        }
      ]
    })

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    act(() => result.current.setStreamEnabled(false))
    await act(async () => result.current.sendMessage('first'))
    await act(async () => result.current.sendMessage('second'))

    const secondRequest = vi.mocked(webuiChatCompletion).mock.calls[1][0]
    expect(secondRequest.session_id).toBe(session.id)
    expect(secondRequest.messages).toEqual([
      { role: 'user', content: 'second' }
    ])
  })

  it('restores an effective thinking model as base id plus thinking flag', async () => {
    vi.mocked(getWebUISession).mockResolvedValue({
      ...session,
      model: 'gpt-5-6-terra-thinking',
      messages: []
    })
    vi.mocked(webuiChatCompletion).mockResolvedValue({
      id: 'chatcmpl-test',
      object: 'chat.completion',
      created: 1,
      model: 'gpt-5-6-terra-thinking',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: 'reasoned answer' },
          finish_reason: 'stop'
        }
      ]
    })

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    await act(async () => result.current.loadModels())
    await waitFor(() => expect(result.current.activeSessionId).toBe(session.id))

    expect(result.current.selectedModel).toBe('gpt-5-6-terra')
    expect(result.current.thinking).toBe(true)
    expect(localStorage.getItem('oai_selected_model')).toBe('gpt-5-6-terra')
    expect(localStorage.getItem('oai_thinking')).toBe('true')

    act(() => result.current.setStreamEnabled(false))
    await act(async () => result.current.sendMessage('follow up'))

    expect(vi.mocked(webuiChatCompletion).mock.calls[0][0]).toMatchObject({
      model: 'gpt-5-6-terra',
      thinking: true
    })
  })

  it('restores the remembered session and keeps histories isolated when switching', async () => {
    const other: ChatSession = {
      ...session,
      id: 'sess_00000000000000000000000000000002',
      title: 'Other chat',
      updated_at: 2
    }
    localStorage.setItem('webui_active_session_id', other.id)
    vi.mocked(listWebUISessions).mockResolvedValue({
      object: 'list',
      data: [other, session]
    })
    vi.mocked(getWebUISession).mockImplementation(async (sessionId) => ({
      ...(sessionId === other.id ? other : session),
      messages: [
        {
          role: 'assistant',
          content: sessionId === other.id ? 'other history' : 'first history'
        }
      ]
    }))

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    localStorage.setItem('webui_active_session_id', other.id)
    await act(async () => result.current.loadSessions())

    expect(result.current.activeSessionId).toBe(other.id)
    expect(result.current.messages[0].content).toBe('other history')

    await act(async () => result.current.selectSession(session.id))
    expect(result.current.activeSessionId).toBe(session.id)
    expect(result.current.messages[0].content).toBe('first history')
  })

  it('updates the sidebar with the account returned by a committed stream', async () => {
    const committed = {
      ...session,
      title: 'hello',
      bound_client_id: 'account-a',
      updated_at: 3
    }
    vi.mocked(webuiChatCompletionStream).mockImplementation(() =>
      (async function* () {
        yield { ...streamChunk('answer'), webui_session: committed }
      })()
    )

    const { result } = renderHook(() => useChat())
    act(() => result.current.saveApiToken('test-token'))
    await act(async () => result.current.sendMessage('hello'))

    expect(result.current.activeSession?.bound_client_id).toBe('account-a')
    expect(result.current.activeSession?.title).toBe('hello')
  })
})

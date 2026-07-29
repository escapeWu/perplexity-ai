import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatCompletionStream } from 'lib/api'
import { useChat } from './useChat'

vi.mock('lib/api', () => ({
  fetchOAIModels: vi.fn(),
  chatCompletion: vi.fn(),
  chatCompletionStream: vi.fn(),
}))

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
    act(() => result.current.stopStreaming())
    await act(async () => {
      await sendPromise
    })

    expect(requestSignal?.aborted).toBe(true)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.error).toBeNull()
    expect(
      result.current.messages.some(
        (message) =>
          message.role === 'assistant' &&
          typeof message.content === 'string' &&
          message.content.startsWith('Error:')
      )
    ).toBe(false)
  })
})

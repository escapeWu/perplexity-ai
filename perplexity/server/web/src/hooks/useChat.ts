import { useState, useCallback, useEffect, useRef } from 'react'
import {
  ChatMessage,
  InputFilePart,
  OAIModel,
  PerplexityProgress,
  ProgressStatus,
  Source,
  fetchOAIModels,
  chatCompletion,
  chatCompletionStream,
} from 'lib/api'

export interface ChatState {
  messages: ChatMessage[]
  isLoading: boolean
  isStreaming: boolean
  error: string | null
  models: OAIModel[]
  selectedModel: string
  apiToken: string
  streamEnabled: boolean
  pendingFiles: File[]
}

function updateLastAssistant(
  messages: ChatMessage[],
  updater: (message: ChatMessage) => ChatMessage
): ChatMessage[] {
  const lastIdx = messages.length - 1
  if (lastIdx < 0 || messages[lastIdx].role !== 'assistant') return messages

  const updated = [...messages]
  updated[lastIdx] = updater(updated[lastIdx])
  return updated
}

function upsertProgress(
  progress: PerplexityProgress[] | undefined,
  incoming: PerplexityProgress
): PerplexityProgress[] {
  const updated = [...(progress || [])]
  const index = updated.findIndex((item) => item.id === incoming.id)
  if (index === -1) {
    updated.push(incoming)
  } else {
    updated[index] = {
      ...updated[index],
      ...incoming,
      detail: incoming.detail || updated[index].detail,
    }
  }
  return updated
}

function settleRunningProgress(
  progress: PerplexityProgress[] | undefined,
  status: Exclude<ProgressStatus, 'running'>
): PerplexityProgress[] | undefined {
  if (!progress) return progress
  return progress.map((item) => (item.status === 'running' ? { ...item, status } : item))
}

/** Read a File as a base64 data-URL and return only the base64 payload. */
function readFileAsBase64(file: File, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('The operation was aborted', 'AbortError'))
      return
    }

    const reader = new FileReader()
    const cleanup = () => signal.removeEventListener('abort', handleAbort)
    const handleAbort = () => reader.abort()

    reader.onload = () => {
      cleanup()
      const result = reader.result as string
      // Strip the "data:<mime>;base64," prefix
      const base64 = result.includes(',') ? result.split(',')[1] : result
      resolve(base64)
    }
    reader.onerror = () => {
      cleanup()
      reject(new Error(`Failed to read file: ${file.name}`))
    }
    reader.onabort = () => {
      cleanup()
      reject(new DOMException('The operation was aborted', 'AbortError'))
    }
    signal.addEventListener('abort', handleAbort, { once: true })
    reader.readAsDataURL(file)
  })
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<OAIModel[]>([])
  const [selectedModel, setSelectedModel] = useState(() => localStorage.getItem('oai_selected_model') || 'perplexity-search')
  const [apiToken, setApiToken] = useState(() => localStorage.getItem('oai_api_token') || '')
  const [streamEnabled, setStreamEnabled] = useState(true)
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)

  useEffect(
    () => () => {
      abortControllerRef.current?.abort()
    },
    []
  )

  const handleSetSelectedModel = useCallback((model: string) => {
    setSelectedModel(model)
    localStorage.setItem('oai_selected_model', model)
  }, [])

  const saveApiToken = useCallback((token: string) => {
    setApiToken(token)
    localStorage.setItem('oai_api_token', token)
    setError(null)
    setModels([])
  }, [])

  const addFiles = useCallback((files: File[]) => {
    setPendingFiles((prev) => [...prev, ...files])
  }, [])

  const removeFile = useCallback((index: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const clearFiles = useCallback(() => {
    setPendingFiles([])
  }, [])

  const loadModels = useCallback(async () => {
    if (!apiToken) {
      setError('API token is required')
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetchOAIModels(apiToken)
      setModels(response.data)

      const currentModelExists = response.data.some((m) => m.id === selectedModel)

      if (!currentModelExists && response.data.length > 0) {
        const defaultModel = response.data.find((m) => m.id === 'perplexity-search')
        if (defaultModel) {
          handleSetSelectedModel(defaultModel.id)
        } else {
          handleSetSelectedModel(response.data[0].id)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load models')
    } finally {
      setIsLoading(false)
    }
  }, [apiToken])

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() && pendingFiles.length === 0) return
      if (!apiToken) return

      abortControllerRef.current?.abort()
      const abortController = new AbortController()
      abortControllerRef.current = abortController
      setIsLoading(true)
      setError(null)

      try {
        // Build content: array when files are attached, plain string otherwise
        let messageContent: ChatMessage['content']
        if (pendingFiles.length > 0) {
          const fileParts: InputFilePart[] = await Promise.all(
            pendingFiles.map(async (file) => ({
              type: 'input_file' as const,
              filename: file.name,
              file_data: await readFileAsBase64(file, abortController.signal),
            }))
          )
          const parts: ChatMessage['content'] = []
          if (content.trim()) {
            ;(parts as Array<unknown>).push({ type: 'text', text: content.trim() })
          }
          ;(parts as Array<unknown>).push(...fileParts)
          messageContent = parts as ChatMessage['content']
        } else {
          messageContent = content.trim()
        }

        const userMessage: ChatMessage = { role: 'user', content: messageContent }
        setMessages((prev) => [...prev, userMessage])
        setPendingFiles([])
        const allMessages = [...messages, userMessage]

        if (streamEnabled) {
          setIsStreaming(true)
          const assistantMessage: ChatMessage = { role: 'assistant', content: '', sources: [] }
          setMessages((prev) => [...prev, assistantMessage])

          const stream = chatCompletionStream(
            { model: selectedModel, messages: allMessages },
            apiToken,
            abortController.signal
          )

          let streamSources: Source[] = []
          for await (const chunk of stream) {
            if (chunk.perplexity_progress) {
              setMessages((prev) =>
                updateLastAssistant(prev, (lastMsg) => ({
                  ...lastMsg,
                  progress: upsertProgress(lastMsg.progress, chunk.perplexity_progress!),
                }))
              )
            }

            const delta = chunk.choices[0]?.delta?.content
            if (delta) {
              setMessages((prev) =>
                updateLastAssistant(prev, (lastMsg) => ({
                  ...lastMsg,
                  content: (lastMsg.content as string) + delta,
                }))
              )
            }
            if (chunk.sources && chunk.sources.length > 0) {
              streamSources = chunk.sources
            }
          }
          setMessages((prev) =>
            updateLastAssistant(prev, (lastMsg) => ({
              ...lastMsg,
              ...(streamSources.length > 0 ? { sources: streamSources } : {}),
              progress: settleRunningProgress(lastMsg.progress, 'completed'),
            }))
          )
        } else {
          const response = await chatCompletion(
            { model: selectedModel, messages: allMessages },
            apiToken,
            abortController.signal
          )
          const assistantContent = response.choices[0]?.message?.content || ''
          const sources = response.sources || []
          setMessages((prev) => [...prev, { role: 'assistant', content: assistantContent, sources }])
        }
      } catch (err) {
        if (
          abortController.signal.aborted ||
          (err instanceof DOMException && err.name === 'AbortError')
        ) {
          setMessages((prev) => {
            const updated = updateLastAssistant(prev, (lastMsg) => ({
              ...lastMsg,
              progress: settleRunningProgress(lastMsg.progress, 'cancelled'),
            }))
            const lastMessage = updated.at(-1)
            if (
              lastMessage?.role === 'assistant' &&
              lastMessage.content === '' &&
              (!lastMessage.progress || lastMessage.progress.length === 0)
            ) {
              return updated.slice(0, -1)
            }
            return updated
          })
          return
        }
        const errorMessage = err instanceof Error ? err.message : 'Failed to send message'
        setError(errorMessage)
        setMessages((prev) => {
          const lastMessage = prev.at(-1)
          if (lastMessage?.role !== 'assistant') {
            return [...prev, { role: 'assistant', content: `Error: ${errorMessage}` }]
          }
          if (
            lastMessage.content === '' &&
            (!lastMessage.progress || lastMessage.progress.length === 0)
          ) {
            return [
              ...prev.slice(0, -1),
              { role: 'assistant', content: `Error: ${errorMessage}` },
            ]
          }
          return updateLastAssistant(prev, (message) => ({
            ...message,
            error: errorMessage,
            progress: settleRunningProgress(message.progress, 'failed'),
          }))
        })
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null
          setIsLoading(false)
          setIsStreaming(false)
        }
      }
    },
    [apiToken, messages, selectedModel, streamEnabled, pendingFiles]
  )

  const clearChat = useCallback(() => {
    setMessages([])
    setError(null)
  }, [])

  const stopStreaming = useCallback(() => {
    const abortController = abortControllerRef.current
    if (abortController) {
      abortController.abort()
      abortControllerRef.current = null
    }
    setIsStreaming(false)
    setIsLoading(false)
  }, [])

  return {
    messages,
    isLoading,
    isStreaming,
    error,
    models,
    selectedModel,
    apiToken,
    streamEnabled,
    pendingFiles,
    setSelectedModel: handleSetSelectedModel,
    saveApiToken,
    setStreamEnabled,
    addFiles,
    removeFile,
    clearFiles,
    loadModels,
    sendMessage,
    clearChat,
    stopStreaming,
  }
}

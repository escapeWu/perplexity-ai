import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChatMessage,
  ChatSession,
  InputFilePart,
  OAIModel,
  PerplexityProgress,
  ProgressStatus,
  Source,
  createWebUISession,
  deleteWebUISession,
  fetchOAIModels,
  getWebUISession,
  listWebUISessions,
  renameWebUISession,
  webuiChatCompletion,
  webuiChatCompletionStream
} from 'lib/api'

const ACTIVE_SESSION_KEY = 'webui_active_session_id'

export interface ChatState {
  messages: ChatMessage[]
  sessions: ChatSession[]
  activeSessionId: string | null
  isLoading: boolean
  isSessionLoading: boolean
  isStreaming: boolean
  error: string | null
  models: OAIModel[]
  selectedModel: string
  apiToken: string
  streamEnabled: boolean
  pendingFiles: File[]
}

function sortSessions(sessions: ChatSession[]): ChatSession[] {
  return [...sessions].sort((left, right) => right.updated_at - left.updated_at)
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
      detail: incoming.detail || updated[index].detail
    }
  }
  return updated
}

function settleRunningProgress(
  progress: PerplexityProgress[] | undefined,
  status: Exclude<ProgressStatus, 'running'>
): PerplexityProgress[] | undefined {
  if (!progress) return progress
  return progress.map((item) =>
    item.status === 'running' ? { ...item, status } : item
  )
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
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isSessionLoading, setIsSessionLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<OAIModel[]>([])
  const [selectedModel, setSelectedModel] = useState(
    () => localStorage.getItem('oai_selected_model') || 'perplexity-search'
  )
  const [apiToken, setApiToken] = useState(
    () => localStorage.getItem('oai_api_token') || ''
  )
  const [streamEnabled, setStreamEnabled] = useState(true)
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const activeSessionIdRef = useRef<string | null>(null)
  const sessionLoadSequenceRef = useRef(0)
  const initializedTokenRef = useRef<string | null>(null)

  useEffect(
    () => () => {
      abortControllerRef.current?.abort()
    },
    []
  )

  const setActiveSession = useCallback((sessionId: string | null) => {
    activeSessionIdRef.current = sessionId
    setActiveSessionId(sessionId)
    if (sessionId) {
      localStorage.setItem(ACTIVE_SESSION_KEY, sessionId)
    } else {
      localStorage.removeItem(ACTIVE_SESSION_KEY)
    }
  }, [])

  const upsertSession = useCallback((session: ChatSession) => {
    setSessions((current) =>
      sortSessions([
        session,
        ...current.filter((item) => item.id !== session.id)
      ])
    )
  }, [])

  const handleSetSelectedModel = useCallback((model: string) => {
    setSelectedModel(model)
    localStorage.setItem('oai_selected_model', model)
  }, [])

  const saveApiToken = useCallback(
    (token: string) => {
      abortControllerRef.current?.abort()
      setApiToken(token)
      localStorage.setItem('oai_api_token', token)
      setError(null)
      setModels([])
      setMessages([])
      setSessions([])
      setActiveSession(null)
      initializedTokenRef.current = null
    },
    [setActiveSession]
  )

  const addFiles = useCallback((files: File[]) => {
    setPendingFiles((prev) => [...prev, ...files])
  }, [])

  const removeFile = useCallback((index: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const clearFiles = useCallback(() => {
    setPendingFiles([])
  }, [])

  const loadSessionDetail = useCallback(
    async (sessionId: string, token = apiToken) => {
      const sequence = ++sessionLoadSequenceRef.current
      setIsSessionLoading(true)
      setError(null)
      try {
        const detail = await getWebUISession(sessionId, token)
        if (sequence !== sessionLoadSequenceRef.current) return
        setActiveSession(detail.id)
        setMessages(detail.messages)
        setPendingFiles([])
        upsertSession(detail)
        if (detail.model) {
          handleSetSelectedModel(detail.model)
        }
      } catch (err) {
        if (sequence !== sessionLoadSequenceRef.current) return
        setError(
          err instanceof Error ? err.message : 'Failed to load conversation'
        )
        throw err
      } finally {
        if (sequence === sessionLoadSequenceRef.current) {
          setIsSessionLoading(false)
        }
      }
    },
    [apiToken, handleSetSelectedModel, setActiveSession, upsertSession]
  )

  const createSession = useCallback(
    async (abortCurrentRequest = true) => {
      if (!apiToken) {
        setError('API token is required')
        return null
      }
      if (abortCurrentRequest) abortControllerRef.current?.abort()
      setIsSessionLoading(true)
      setError(null)
      try {
        const session = await createWebUISession(apiToken)
        sessionLoadSequenceRef.current += 1
        upsertSession(session)
        setActiveSession(session.id)
        setMessages([])
        setPendingFiles([])
        return session
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to create conversation'
        )
        return null
      } finally {
        setIsSessionLoading(false)
      }
    },
    [apiToken, setActiveSession, upsertSession]
  )

  const loadSessions = useCallback(async () => {
    if (!apiToken) return
    setIsSessionLoading(true)
    setError(null)
    try {
      const response = await listWebUISessions(apiToken)
      let availableSessions = sortSessions(response.data)
      if (availableSessions.length === 0) {
        availableSessions = [await createWebUISession(apiToken)]
      }
      setSessions(availableSessions)

      const rememberedId = localStorage.getItem(ACTIVE_SESSION_KEY)
      const target =
        availableSessions.find((session) => session.id === rememberedId) ||
        availableSessions[0]
      await loadSessionDetail(target.id, apiToken)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load conversations'
      )
    } finally {
      setIsSessionLoading(false)
    }
  }, [apiToken, loadSessionDetail])

  useEffect(() => {
    if (
      !apiToken ||
      models.length === 0 ||
      initializedTokenRef.current === apiToken
    )
      return
    initializedTokenRef.current = apiToken
    void loadSessions()
  }, [apiToken, loadSessions, models.length])

  const selectSession = useCallback(
    async (sessionId: string) => {
      if (!apiToken || sessionId === activeSessionIdRef.current) return
      abortControllerRef.current?.abort()
      await loadSessionDetail(sessionId)
    },
    [apiToken, loadSessionDetail]
  )

  const renameSession = useCallback(
    async (sessionId: string, title: string) => {
      if (!apiToken) return false
      try {
        const updated = await renameWebUISession(sessionId, title, apiToken)
        upsertSession(updated)
        return true
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to rename conversation'
        )
        return false
      }
    },
    [apiToken, upsertSession]
  )

  const deleteSession = useCallback(
    async (sessionId: string) => {
      if (!apiToken) return
      abortControllerRef.current?.abort()
      try {
        await deleteWebUISession(sessionId, apiToken)
        const remaining = sessions.filter((session) => session.id !== sessionId)
        setSessions(remaining)
        if (activeSessionIdRef.current !== sessionId) return
        if (remaining.length > 0) {
          await loadSessionDetail(remaining[0].id)
        } else {
          await createSession()
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to delete conversation'
        )
      }
    },
    [apiToken, createSession, loadSessionDetail, sessions]
  )

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

      const currentModelExists = response.data.some(
        (model) => model.id === selectedModel
      )
      if (!currentModelExists && response.data.length > 0) {
        const defaultModel = response.data.find(
          (model) => model.id === 'perplexity-search'
        )
        handleSetSelectedModel(defaultModel?.id || response.data[0].id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load models')
    } finally {
      setIsLoading(false)
    }
  }, [apiToken, handleSetSelectedModel, selectedModel])

  const ensureActiveSession = useCallback(async () => {
    if (activeSessionIdRef.current) return activeSessionIdRef.current
    const session = await createSession(false)
    if (!session) throw new Error('Unable to create a conversation')
    return session.id
  }, [createSession])

  const refreshSessionMetadata = useCallback(
    async (sessionId: string) => {
      if (!apiToken) return
      try {
        const detail = await getWebUISession(sessionId, apiToken)
        upsertSession(detail)
      } catch {
        // The original completion error remains the useful message.
      }
    },
    [apiToken, upsertSession]
  )

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() && pendingFiles.length === 0) return
      if (!apiToken) return

      abortControllerRef.current?.abort()
      const abortController = new AbortController()
      abortControllerRef.current = abortController
      setIsLoading(true)
      setError(null)
      let requestSessionId: string | null = null

      try {
        requestSessionId = await ensureActiveSession()
        let messageContent: ChatMessage['content']
        if (pendingFiles.length > 0) {
          const fileParts: InputFilePart[] = await Promise.all(
            pendingFiles.map(async (file) => ({
              type: 'input_file' as const,
              filename: file.name,
              file_data: await readFileAsBase64(file, abortController.signal)
            }))
          )
          const parts: Array<InputFilePart | { type: 'text'; text: string }> =
            []
          if (content.trim()) parts.push({ type: 'text', text: content.trim() })
          parts.push(...fileParts)
          messageContent = parts
        } else {
          messageContent = content.trim()
        }

        const userMessage: ChatMessage = {
          role: 'user',
          content: messageContent
        }
        setMessages((prev) => [...prev, userMessage])
        setPendingFiles([])

        if (streamEnabled) {
          setIsStreaming(true)
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: '', sources: [] }
          ])
          const stream = webuiChatCompletionStream(
            {
              session_id: requestSessionId,
              model: selectedModel,
              messages: [userMessage]
            },
            apiToken,
            abortController.signal
          )

          let streamSources: Source[] = []
          let committedSession: ChatSession | undefined
          for await (const chunk of stream) {
            if (chunk.perplexity_progress) {
              setMessages((prev) =>
                updateLastAssistant(prev, (lastMsg) => ({
                  ...lastMsg,
                  progress: upsertProgress(
                    lastMsg.progress,
                    chunk.perplexity_progress!
                  )
                }))
              )
            }

            const delta = chunk.choices[0]?.delta?.content
            if (delta) {
              setMessages((prev) =>
                updateLastAssistant(prev, (lastMsg) => ({
                  ...lastMsg,
                  content: (lastMsg.content as string) + delta
                }))
              )
            }
            if (chunk.sources?.length) streamSources = chunk.sources
            if (chunk.webui_session) committedSession = chunk.webui_session
          }
          setMessages((prev) =>
            updateLastAssistant(prev, (lastMsg) => ({
              ...lastMsg,
              ...(streamSources.length > 0 ? { sources: streamSources } : {}),
              progress: settleRunningProgress(lastMsg.progress, 'completed')
            }))
          )
          if (committedSession) upsertSession(committedSession)
        } else {
          const response = await webuiChatCompletion(
            {
              session_id: requestSessionId,
              model: selectedModel,
              messages: [userMessage]
            },
            apiToken,
            abortController.signal
          )
          const assistantContent = response.choices[0]?.message?.content || ''
          const sources = response.sources || []
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: assistantContent, sources }
          ])
          if (response.webui_session) upsertSession(response.webui_session)
        }
      } catch (err) {
        if (
          abortController.signal.aborted ||
          (err instanceof DOMException && err.name === 'AbortError')
        ) {
          setMessages((prev) => {
            const updated = updateLastAssistant(prev, (lastMsg) => ({
              ...lastMsg,
              progress: settleRunningProgress(lastMsg.progress, 'cancelled')
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
        const errorMessage =
          err instanceof Error ? err.message : 'Failed to send message'
        setError(errorMessage)
        setMessages((prev) => {
          const lastMessage = prev.at(-1)
          if (lastMessage?.role !== 'assistant') {
            return [
              ...prev,
              { role: 'assistant', content: `Error: ${errorMessage}` }
            ]
          }
          if (
            lastMessage.content === '' &&
            (!lastMessage.progress || lastMessage.progress.length === 0)
          ) {
            return [
              ...prev.slice(0, -1),
              { role: 'assistant', content: `Error: ${errorMessage}` }
            ]
          }
          return updateLastAssistant(prev, (message) => ({
            ...message,
            error: errorMessage,
            progress: settleRunningProgress(message.progress, 'failed')
          }))
        })
        if (requestSessionId) await refreshSessionMetadata(requestSessionId)
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null
          setIsLoading(false)
          setIsStreaming(false)
        }
      }
    },
    [
      apiToken,
      ensureActiveSession,
      pendingFiles,
      refreshSessionMetadata,
      selectedModel,
      streamEnabled,
      upsertSession
    ]
  )

  const clearChat = useCallback(() => {
    void createSession()
  }, [createSession])

  const stopStreaming = useCallback(() => {
    const abortController = abortControllerRef.current
    if (abortController) {
      abortController.abort()
      abortControllerRef.current = null
    }
    setIsStreaming(false)
    setIsLoading(false)
  }, [])

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) || null,
    [activeSessionId, sessions]
  )

  return {
    messages,
    sessions,
    activeSession,
    activeSessionId,
    isLoading,
    isSessionLoading,
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
    loadSessions,
    createSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
    clearChat,
    stopStreaming
  }
}

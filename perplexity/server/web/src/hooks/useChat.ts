import { useState, useCallback, useRef } from 'react'
import {
  ChatMessage,
  OAIModel,
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
  const abortControllerRef = useRef<AbortController | null>(null)

  const handleSetSelectedModel = useCallback((model: string) => {
    setSelectedModel(model)
    localStorage.setItem('oai_selected_model', model)
  }, [])

  const saveApiToken = useCallback((token: string) => {
    setApiToken(token)
    localStorage.setItem('oai_api_token', token)
    // Clear error when token changes so auto-load can retry
    setError(null)
    // Clear models to allow re-loading with new token
    setModels([])
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

      // Check if current selected model exists in list
      const currentModelExists = response.data.some((m) => m.id === selectedModel)

      if (!currentModelExists && response.data.length > 0) {
        // Fallback to default or first available
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
      if (!content.trim() || !apiToken) return

      const userMessage: ChatMessage = { role: 'user', content: content.trim() }
      setMessages((prev) => [...prev, userMessage])
      setIsLoading(true)
      setError(null)

      const allMessages = [...messages, userMessage]

      try {
        if (streamEnabled) {
          // Streaming mode
          setIsStreaming(true)
          const assistantMessage: ChatMessage = { role: 'assistant', content: '', sources: [] }
          setMessages((prev) => [...prev, assistantMessage])

          const stream = chatCompletionStream(
            { model: selectedModel, messages: allMessages },
            apiToken
          )

          let streamSources: Source[] = []
          for await (const chunk of stream) {
            const delta = chunk.choices[0]?.delta?.content
            if (delta) {
              setMessages((prev) => {
                const updated = [...prev]
                const lastIdx = updated.length - 1
                const lastMsg = updated[lastIdx]
                if (lastMsg.role === 'assistant') {
                  // Create a new object to trigger React re-render
                  updated[lastIdx] = {
                    ...lastMsg,
                    content: lastMsg.content + delta,
                  }
                }
                return updated
              })
            }
            // Capture sources from final chunk
            if (chunk.sources && chunk.sources.length > 0) {
              streamSources = chunk.sources
            }
          }
          // Update sources after stream completes
          if (streamSources.length > 0) {
            setMessages((prev) => {
              const updated = [...prev]
              const lastIdx = updated.length - 1
              const lastMsg = updated[lastIdx]
              if (lastMsg.role === 'assistant') {
                updated[lastIdx] = {
                  ...lastMsg,
                  sources: streamSources,
                }
              }
              return updated
            })
          }
        } else {
          // Non-streaming mode
          const response = await chatCompletion(
            { model: selectedModel, messages: allMessages },
            apiToken
          )
          const assistantContent = response.choices[0]?.message?.content || ''
          const sources = response.sources || []
          setMessages((prev) => [...prev, { role: 'assistant', content: assistantContent, sources }])
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to send message'
        setError(errorMessage)
        // Add error as assistant message
        setMessages((prev) => [
          ...prev.filter((m) => m.role !== 'assistant' || m.content !== ''),
          { role: 'assistant', content: `Error: ${errorMessage}` },
        ])
      } finally {
        setIsLoading(false)
        setIsStreaming(false)
      }
    },
    [apiToken, messages, selectedModel, streamEnabled]
  )

  const clearChat = useCallback(() => {
    setMessages([])
    setError(null)
  }, [])

  const stopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
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
    setSelectedModel: handleSetSelectedModel,
    saveApiToken,
    setStreamEnabled,
    loadModels,
    sendMessage,
    clearChat,
    stopStreaming,
  }
}

import { useState, useCallback, useRef } from 'react'
import {
  ChatMessage,
  InputFilePart,
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
  pendingFiles: File[]
}

/** Read a File as a base64 data-URL and return only the base64 payload. */
function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // Strip the "data:<mime>;base64," prefix
      const base64 = result.includes(',') ? result.split(',')[1] : result
      resolve(base64)
    }
    reader.onerror = () => reject(new Error(`Failed to read file: ${file.name}`))
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

      // Build content: array when files are attached, plain string otherwise
      let messageContent: ChatMessage['content']
      if (pendingFiles.length > 0) {
        const fileParts: InputFilePart[] = await Promise.all(
          pendingFiles.map(async (file) => ({
            type: 'input_file' as const,
            filename: file.name,
            file_data: await readFileAsBase64(file),
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
      setIsLoading(true)
      setError(null)

      const allMessages = [...messages, userMessage]

      try {
        if (streamEnabled) {
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
                  updated[lastIdx] = {
                    ...lastMsg,
                    content: (lastMsg.content as string) + delta,
                  }
                }
                return updated
              })
            }
            if (chunk.sources && chunk.sources.length > 0) {
              streamSources = chunk.sources
            }
          }
          if (streamSources.length > 0) {
            setMessages((prev) => {
              const updated = [...prev]
              const lastIdx = updated.length - 1
              const lastMsg = updated[lastIdx]
              if (lastMsg.role === 'assistant') {
                updated[lastIdx] = { ...lastMsg, sources: streamSources }
              }
              return updated
            })
          }
        } else {
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
        setMessages((prev) => [
          ...prev.filter((m) => m.role !== 'assistant' || m.content !== ''),
          { role: 'assistant', content: `Error: ${errorMessage}` },
        ])
      } finally {
        setIsLoading(false)
        setIsStreaming(false)
      }
    },
    [apiToken, messages, selectedModel, streamEnabled, pendingFiles]
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

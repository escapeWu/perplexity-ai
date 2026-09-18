import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChatMessage,
  ChatSession,
  InputFilePart,
  OAIModel,
  WebUIChatCompletionRequest,
  createWebUISession,
  deleteWebUISession,
  fetchOAIModels,
  getWebUISession,
  listWebUISessions,
  renameWebUISession
} from 'lib/api'
import { cancelJob, isActiveJob, submitJob, uploadAttachment } from 'lib/jobs'
import {
  modelBaseId,
  modelIsThinking,
  modelIsThinkingOnly,
  modelSupportsThinking
} from 'lib/modelCatalog'
import { useChatJobs } from './useChatJobs'

const ACTIVE_SESSION_KEY = 'webui_active_session_id'
const SELECTED_MODEL_KEY = 'oai_selected_model'
const THINKING_KEY = 'oai_thinking'

export interface ModelSelection {
  model: string
  thinking: boolean
}
export function resolveModelSelection(
  models: OAIModel[],
  modelId: string,
  preferredThinking = false
): ModelSelection | null {
  const requested = models.find((model) => model.id === modelId)
  if (!requested) return null
  const base =
    models.find((model) => model.id === modelBaseId(requested, models)) ||
    requested
  return {
    model: base.id,
    thinking:
      modelIsThinkingOnly(requested, models) ||
      modelIsThinking(requested) ||
      (preferredThinking && modelSupportsThinking(base, models))
  }
}

interface SessionView {
  messages: ChatMessage[]
  pendingFiles: File[]
  draft: string
  selectedModel: string
  thinking: boolean
  streamEnabled: boolean
  loading: boolean
  submitting: boolean
  error: string | null
  nextCursor: number | null
}

function requestKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
    value.toString(16).padStart(2, '0')
  ).join('')
}

function defaultView(): SessionView {
  return {
    messages: [],
    pendingFiles: [],
    draft: '',
    selectedModel:
      localStorage.getItem(SELECTED_MODEL_KEY) || 'perplexity-search',
    thinking: localStorage.getItem(THINKING_KEY) === 'true',
    streamEnabled: true,
    loading: false,
    submitting: false,
    error: null,
    nextCursor: null
  }
}

export function useChat() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const activeRef = useRef<string | null>(null)
  const [views, setViews] = useState<Record<string, SessionView>>({})
  const viewsRef = useRef<Record<string, SessionView>>({})
  const [models, setModels] = useState<OAIModel[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [globalError, setGlobalError] = useState<string | null>(null)
  const [apiToken, setApiToken] = useState(
    () => localStorage.getItem('oai_api_token') || ''
  )
  const tokenRef = useRef(apiToken)
  tokenRef.current = apiToken
  const [sessionCursor, setSessionCursor] = useState<string | null>(null)
  const initialized = useRef<string | null>(null)
  const navSequence = useRef(0)
  const loadSequence = useRef<Record<string, number>>({})
  const preparations = useRef(new Map<string, AbortController>())
  const explicitStops = useRef(new WeakSet<AbortController>())
  const mounted = useRef(true)
  const fileKeys = useRef(new WeakMap<File, string>())
  const pendingKeys = useRef<
    Record<
      string,
      { fingerprint: string; key: string; request?: WebUIChatCompletionRequest }
    >
  >({})
  const refreshed = useRef(new Set<string>())
  const view = activeSessionId
    ? views[activeSessionId] || defaultView()
    : defaultView()
  const { jobs, jobsRef, remember, observationError } = useChatJobs(
    apiToken,
    activeSessionId,
    view.streamEnabled
  )
  const job = activeSessionId ? jobs[activeSessionId] : undefined

  const updateView = useCallback((id: string, patch: Partial<SessionView>) => {
    const next = {
      ...viewsRef.current,
      [id]: { ...(viewsRef.current[id] || defaultView()), ...patch }
    }
    viewsRef.current = next
    setViews(next)
  }, [])

  const setActive = useCallback((id: string | null) => {
    activeRef.current = id
    setActiveSessionId(id)
    if (id) localStorage.setItem(ACTIVE_SESSION_KEY, id)
    else localStorage.removeItem(ACTIVE_SESSION_KEY)
  }, [])

  const upsertSession = useCallback((session: ChatSession) => {
    const incoming = session
    setSessions((current) => {
      const existing = current.find((item) => item.id === incoming.id)
      if (existing && existing.updated_at > incoming.updated_at) return current
      return [
        incoming,
        ...current.filter((item) => item.id !== incoming.id)
      ].sort((a, b) => b.updated_at - a.updated_at)
    })
  }, [])

  const loadSessionDetail = useCallback(
    async (id: string, before?: number | null) => {
      const token = apiToken
      const sequence = (loadSequence.current[id] || 0) + 1
      loadSequence.current[id] = sequence
      updateView(id, { loading: true, error: null })
      try {
        const detail = await getWebUISession(id, token, before)
        if (token !== tokenRef.current || loadSequence.current[id] !== sequence)
          return
        const current = viewsRef.current[id] || defaultView()
        const selection = resolveModelSelection(
          models,
          detail.model || current.selectedModel,
          current.thinking
        )
        updateView(id, {
          messages: before
            ? [...detail.messages, ...current.messages]
            : detail.messages,
          nextCursor: detail.next_cursor || null,
          loading: false,
          ...(selection && !viewsRef.current[id]?.messages.length
            ? { selectedModel: selection.model, thinking: selection.thinking }
            : {})
        })
        upsertSession(detail)
        if (detail.latest_job) remember(detail.latest_job)
      } catch (error) {
        if (token !== tokenRef.current || loadSequence.current[id] !== sequence)
          return
        updateView(id, {
          loading: false,
          error:
            error instanceof Error
              ? error.message
              : 'Failed to load conversation'
        })
      }
    },
    [apiToken, models, remember, updateView, upsertSession]
  )

  const createSession = useCallback(async () => {
    if (!apiToken) {
      setGlobalError('API token is required')
      return null
    }
    const sequence = ++navSequence.current
    const token = apiToken
    setCreating(true)
    try {
      const session = await createWebUISession(token)
      if (token !== tokenRef.current) return null
      upsertSession(session)
      updateView(session.id, defaultView())
      if (sequence === navSequence.current) setActive(session.id)
      return session
    } catch (error) {
      setGlobalError(
        error instanceof Error ? error.message : 'Failed to create conversation'
      )
      return null
    } finally {
      if (token === tokenRef.current) setCreating(false)
    }
  }, [apiToken, setActive, updateView, upsertSession])

  const loadSessions = useCallback(async () => {
    if (!apiToken) return
    const token = apiToken
    try {
      const response = await listWebUISessions(token)
      if (token !== tokenRef.current) return
      setSessions(response.data)
      setSessionCursor(response.next_cursor || null)
      response.data.forEach((session) => {
        if (session.active_job) remember(session.active_job)
      })
      if (!response.data.length) {
        await createSession()
        return
      }
      const remembered = localStorage.getItem(ACTIVE_SESSION_KEY)
      const target =
        response.data.find((item) => item.id === remembered) || response.data[0]
      setActive(target.id)
      await loadSessionDetail(target.id)
    } catch (error) {
      setGlobalError(
        error instanceof Error ? error.message : 'Failed to load conversations'
      )
    }
  }, [apiToken, createSession, loadSessionDetail, remember, setActive])

  useEffect(() => {
    if (!apiToken || !models.length || initialized.current === apiToken) return
    initialized.current = apiToken
    void loadSessions()
  }, [apiToken, models.length, loadSessions])

  useEffect(() => {
    if (!job || isActiveJob(job) || refreshed.current.has(job.id)) return
    refreshed.current.add(job.id)
    if (job.snapshot?.session) upsertSession(job.snapshot.session)
    if (job.state === 'completed') void loadSessionDetail(job.session_id)
  }, [
    job?.id,
    job?.state,
    job?.snapshot?.session,
    loadSessionDetail,
    upsertSession
  ])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      preparations.current.forEach((controller) => controller.abort())
    }
  }, [])

  const loadModels = useCallback(async () => {
    if (!apiToken) {
      setGlobalError('API token is required')
      return
    }
    const token = apiToken
    setModelsLoading(true)
    setGlobalError(null)
    try {
      const response = await fetchOAIModels(token)
      if (token !== tokenRef.current) return
      setModels(response.data)
      const selection =
        resolveModelSelection(
          response.data,
          localStorage.getItem(SELECTED_MODEL_KEY) || 'perplexity-search',
          localStorage.getItem(THINKING_KEY) === 'true'
        ) ||
        resolveModelSelection(
          response.data,
          response.data.find((item) => item.id === 'perplexity-search')?.id ||
            response.data[0]?.id
        )
      if (selection) {
        localStorage.setItem(SELECTED_MODEL_KEY, selection.model)
        localStorage.setItem(THINKING_KEY, String(selection.thinking))
        if (activeRef.current)
          updateView(activeRef.current, {
            selectedModel: selection.model,
            thinking: selection.thinking
          })
      }
    } catch (error) {
      if (token === tokenRef.current)
        setGlobalError(
          error instanceof Error ? error.message : 'Failed to load models'
        )
    } finally {
      if (token === tokenRef.current) setModelsLoading(false)
    }
  }, [apiToken, updateView])

  const saveApiToken = useCallback(
    (token: string) => {
      preparations.current.forEach((controller) => controller.abort())
      preparations.current.clear()
      tokenRef.current = token
      setApiToken(token)
      localStorage.setItem('oai_api_token', token)
      viewsRef.current = {}
      setViews({})
      setSessions([])
      setModels([])
      setActive(null)
      setGlobalError(null)
      initialized.current = null
      refreshed.current.clear()
      pendingKeys.current = {}
    },
    [setActive]
  )

  const selectSession = useCallback(
    async (id: string) => {
      ++navSequence.current
      setActive(id)
      setGlobalError(null)
      await loadSessionDetail(id)
    },
    [loadSessionDetail, setActive]
  )

  const renameSession = useCallback(
    async (id: string, title: string) => {
      try {
        upsertSession(await renameWebUISession(id, title, apiToken))
        return true
      } catch (error) {
        updateView(id, {
          error: error instanceof Error ? error.message : 'Rename failed'
        })
        return false
      }
    },
    [apiToken, updateView, upsertSession]
  )

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await deleteWebUISession(id, apiToken)
        const remaining = sessions.filter((item) => item.id !== id)
        setSessions(remaining)
        const next = { ...viewsRef.current }
        delete next[id]
        viewsRef.current = next
        setViews(next)
        if (activeRef.current === id) {
          if (remaining.length) await selectSession(remaining[0].id)
          else await createSession()
        }
      } catch (error) {
        updateView(id, {
          error: error instanceof Error ? error.message : 'Delete failed'
        })
      }
    },
    [apiToken, sessions, selectSession, createSession, updateView]
  )

  const sendMessage = useCallback(
    async (content: string) => {
      let id = activeRef.current
      if (!id) id = (await createSession())?.id || null
      if (
        !id ||
        !apiToken ||
        preparations.current.has(id) ||
        isActiveJob(jobsRef.current[id])
      )
        return
      const current = viewsRef.current[id] || defaultView()
      if (!content.trim() && !current.pendingFiles.length) return
      const controller = new AbortController()
      preparations.current.set(id, controller)
      updateView(id, { submitting: true, error: null })
      const token = apiToken
      let submittedRequest = false
      try {
        const fingerprint = JSON.stringify({
          session: id,
          content: content.trim(),
          model: current.selectedModel,
          thinking: current.thinking,
          files: current.pendingFiles.map((file) => {
            if (!fileKeys.current.has(file))
              fileKeys.current.set(file, requestKey())
            return fileKeys.current.get(file)
          })
        })
        const previous = pendingKeys.current[id]
        const pending =
          previous?.fingerprint === fingerprint
            ? previous
            : { fingerprint, key: requestKey(), request: undefined }
        pendingKeys.current[id] = pending
        if (!pending.request) {
          const parts: (InputFilePart | { type: 'text'; text: string })[] = []
          if (content.trim()) parts.push({ type: 'text', text: content.trim() })
          for (const file of current.pendingFiles) {
            const fileId = await uploadAttachment(
              file,
              token,
              controller.signal
            )
            parts.push({
              type: 'input_file',
              filename: file.name,
              file_id: fileId
            })
          }
          if (controller.signal.aborted) return
          pending.request = {
            session_id: id,
            model: current.selectedModel,
            thinking: current.thinking,
            messages: [
              {
                role: 'user',
                content: current.pendingFiles.length ? parts : content.trim()
              }
            ]
          }
        }
        submittedRequest = true
        // Keep the receipt across navigation. Only an explicit Stop owns cancellation.
        let submitted = await submitJob(pending.request, token, pending.key)
        if (explicitStops.current.has(controller))
          submitted = await cancelJob(submitted.id, token)
        if (token !== tokenRef.current || !mounted.current) return
        remember(submitted)
        delete pendingKeys.current[id]
        updateView(id, { pendingFiles: [], draft: '' })
      } catch (error) {
        if (
          token === tokenRef.current &&
          mounted.current &&
          (!controller.signal.aborted || submittedRequest)
        ) {
          const message =
            explicitStops.current.has(controller) && submittedRequest
              ? 'Stopping is not yet confirmed. Check the task status and retry Stop.'
              : error instanceof Error
                ? error.message
                : 'Task submission failed'
          updateView(id, { error: message, draft: content })
        }
      } finally {
        if (preparations.current.get(id) === controller)
          preparations.current.delete(id)
        if (token === tokenRef.current && mounted.current)
          updateView(id, { submitting: false })
      }
    },
    [apiToken, createSession, jobsRef, remember, updateView]
  )

  const stopStreaming = useCallback(async () => {
    const id = activeRef.current
    if (!id) return
    const preparing = preparations.current.get(id)
    if (preparing) {
      explicitStops.current.add(preparing)
      preparing.abort()
    }
    const current = jobsRef.current[id]
    if (current && isActiveJob(current)) {
      try {
        remember(await cancelJob(current.id, apiToken))
      } catch (error) {
        updateView(id, {
          error: error instanceof Error ? error.message : 'Unable to stop task'
        })
      }
    }
  }, [apiToken, jobsRef, remember, updateView])

  const setSelectedModel = useCallback(
    (model: string) => {
      const current = activeRef.current
        ? viewsRef.current[activeRef.current]
        : null
      const selection = resolveModelSelection(
        models,
        model,
        current?.thinking
      ) || { model, thinking: false }
      localStorage.setItem(SELECTED_MODEL_KEY, selection.model)
      localStorage.setItem(THINKING_KEY, String(selection.thinking))
      if (activeRef.current)
        updateView(activeRef.current, {
          selectedModel: selection.model,
          thinking: selection.thinking
        })
    },
    [models, updateView]
  )

  const setThinking = useCallback(
    (enabled: boolean) => {
      const id = activeRef.current
      if (!id) return
      const current = viewsRef.current[id] || defaultView()
      const selected = models.find((item) => item.id === current.selectedModel)
      const thinking =
        !!selected &&
        (modelIsThinkingOnly(selected, models) ||
          (enabled && modelSupportsThinking(selected, models)))
      localStorage.setItem(THINKING_KEY, String(thinking))
      updateView(id, { thinking })
    },
    [models, updateView]
  )

  const addFiles = useCallback(
    (files: File[]) => {
      const id = activeRef.current
      if (!id) return
      const all = [...(viewsRef.current[id]?.pendingFiles || []), ...files]
      if (
        all.length > 10 ||
        all.some((file) => file.size > 20 * 1024 * 1024) ||
        all.reduce((sum, file) => sum + file.size, 0) > 100 * 1024 * 1024
      ) {
        updateView(id, {
          error: 'Use at most 10 files, 20 MiB each and 100 MiB total'
        })
        return
      }
      updateView(id, { pendingFiles: all })
    },
    [updateView]
  )
  const removeFile = useCallback(
    (index: number) => {
      const id = activeRef.current
      if (id)
        updateView(id, {
          pendingFiles: (viewsRef.current[id]?.pendingFiles || []).filter(
            (_, i) => i !== index
          )
        })
    },
    [updateView]
  )
  const clearFiles = useCallback(() => {
    if (activeRef.current) updateView(activeRef.current, { pendingFiles: [] })
  }, [updateView])
  const setDraft = useCallback(
    (draft: string) => {
      if (activeRef.current) updateView(activeRef.current, { draft })
    },
    [updateView]
  )
  const setStreamEnabled = useCallback(
    (streamEnabled: boolean) => {
      if (activeRef.current) updateView(activeRef.current, { streamEnabled })
    },
    [updateView]
  )

  const loadMoreSessions = useCallback(async () => {
    if (!sessionCursor) return
    try {
      const page = await listWebUISessions(apiToken, sessionCursor)
      page.data.forEach(upsertSession)
      setSessionCursor(page.next_cursor || null)
    } catch (error) {
      setGlobalError(
        error instanceof Error ? error.message : 'Unable to load conversations'
      )
    }
  }, [apiToken, sessionCursor, upsertSession])
  const loadOlderMessages = useCallback(async () => {
    const id = activeRef.current
    if (id && viewsRef.current[id]?.nextCursor)
      await loadSessionDetail(id, viewsRef.current[id].nextCursor)
  }, [loadSessionDetail])

  const messages = useMemo(() => {
    if (!job || view.messages.some((message) => message.job_id === job.id))
      return view.messages
    const failed = !isActiveJob(job) && job.state !== 'completed'
    const showPartial = view.streamEnabled || !isActiveJob(job)
    const progress = (job.snapshot?.progress || []).map((item) => ({
      ...item,
      status:
        !isActiveJob(job) && item.status === 'running'
          ? ((job.state === 'completed'
              ? 'completed'
              : job.state === 'cancelled'
                ? 'cancelled'
                : 'failed') as 'completed' | 'cancelled' | 'failed')
          : item.status
    }))
    const appended: ChatMessage[] = [
      { role: 'user', content: job.user_content || '', job_id: job.id },
      {
        role: 'assistant',
        content: showPartial ? job.snapshot?.answer || '' : '',
        sources: job.snapshot?.sources || [],
        progress,
        job_id: job.id,
        ...(failed ? { error: job.error?.message || `Task ${job.state}` } : {})
      }
    ]
    return [...view.messages, ...appended]
  }, [job, view.messages, view.streamEnabled])

  const displaySessions = useMemo(
    () =>
      sessions.map((session) => ({
        ...session,
        active_job: jobs[session.id] || session.active_job,
        ...(jobs[session.id]?.snapshot?.session &&
        jobs[session.id].snapshot!.session!.updated_at > session.updated_at
          ? jobs[session.id].snapshot!.session
          : {})
      })),
    [sessions, jobs]
  )
  const activeSession =
    displaySessions.find((item) => item.id === activeSessionId) || null
  const isLoading = modelsLoading || view.submitting || isActiveJob(job)
  return {
    messages,
    sessions: displaySessions,
    activeSession,
    activeSessionId,
    isLoading,
    isSessionLoading: view.loading || creating,
    isStreaming: isActiveJob(job) && view.streamEnabled,
    error: view.error || globalError || observationError,
    models,
    selectedModel: view.selectedModel,
    thinking: view.thinking,
    apiToken,
    streamEnabled: view.streamEnabled,
    pendingFiles: view.pendingFiles,
    draft: view.draft,
    setDraft,
    setSelectedModel,
    setThinking,
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
    clearChat: createSession,
    stopStreaming,
    hasMoreSessions: !!sessionCursor,
    loadMoreSessions,
    hasOlderMessages: !!view.nextCursor,
    loadOlderMessages
  }
}

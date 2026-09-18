import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from 'lib/api'
import * as tasks from 'lib/jobs'
import type { ChatJob, ChatMessage, ChatSession, JobEvent } from 'lib/api'
import { useChat } from './useChat'

vi.mock('lib/api', async (original) => ({
  ...(await original<typeof api>()),
  fetchOAIModels: vi.fn(),
  createWebUISession: vi.fn(),
  listWebUISessions: vi.fn(),
  getWebUISession: vi.fn(),
  renameWebUISession: vi.fn(),
  deleteWebUISession: vi.fn()
}))
vi.mock('lib/jobs', async (original) => ({
  ...(await original<typeof tasks>()),
  submitJob: vi.fn(),
  getJob: vi.fn(),
  listJobs: vi.fn(),
  jobEvents: vi.fn(),
  waitJobResult: vi.fn(),
  cancelJob: vi.fn(),
  uploadAttachment: vi.fn()
}))

const session = (id: string): ChatSession => ({
  id,
  title: id,
  bound_client_id: null,
  model: null,
  created_at: 1,
  updated_at: 1
})
const a = session('session-a')
const b = session('session-b')
const models: api.OAIModel[] = [
  {
    id: 'model-a',
    object: 'model',
    created: 1,
    owned_by: 'perplexity',
    base_model_id: 'model-a',
    thinking_model_id: 'model-a-thinking',
    supports_thinking: true
  },
  {
    id: 'model-a-thinking',
    object: 'model',
    created: 1,
    owned_by: 'perplexity',
    mode: 'reasoning',
    base_model_id: 'model-a',
    thinking: true
  },
  {
    id: 'model-b',
    object: 'model',
    created: 1,
    owned_by: 'perplexity',
    base_model_id: 'model-b',
    supports_thinking: false
  }
]
let records: Record<string, ChatJob>
let history: Record<string, ChatMessage[]>
let listeners: Record<string, (event: JobEvent) => void>
let fullListeners: Record<string, (job: ChatJob) => void>
let signals: Record<string, AbortSignal>
let clock: number
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))

function finish(id: string, state: 'completed' | 'failed' = 'completed') {
  const old = records[id]
  const job: ChatJob = {
    ...old,
    seq: old.seq + 1,
    state,
    updated_at: ++clock,
    error:
      state === 'failed'
        ? { code: 'upstream_failed', message: 'Upstream interrupted' }
        : null,
    snapshot: {
      answer:
        state === 'completed'
          ? `${old.session_id} final`
          : `${old.session_id} partial`,
      progress: [
        {
          id: 'p',
          stage: 'final',
          label: 'Writing answer',
          status: state === 'completed' ? 'completed' : 'failed'
        }
      ]
    }
  }
  records[id] = job
  if (state === 'completed')
    history[job.session_id] = [
      ...(history[job.session_id] || []),
      { id: 1, job_id: id, role: 'user', content: job.user_content || '' },
      { id: 2, job_id: id, role: 'assistant', content: job.snapshot!.answer! }
    ]
  listeners[id]?.({ type: 'terminal', seq: job.seq, job: clone(job) })
  fullListeners[id]?.(clone(job))
}

beforeEach(() => {
  localStorage.clear()
  vi.resetAllMocks()
  records = {}
  history = {}
  listeners = {}
  fullListeners = {}
  signals = {}
  clock = 10
  vi.mocked(api.fetchOAIModels).mockResolvedValue({
    object: 'list',
    data: models
  })
  vi.mocked(api.listWebUISessions).mockResolvedValue({
    object: 'list',
    data: [a, b]
  })
  vi.mocked(api.createWebUISession).mockResolvedValue(b)
  vi.mocked(api.getWebUISession).mockImplementation(async (id) => ({
    ...session(id),
    messages: history[id] || [],
    latest_job: clone(
      Object.values(records).find((job) => job.session_id === id) || null
    )
  }))
  vi.mocked(tasks.listJobs).mockImplementation(async () =>
    Object.values(records).map(clone)
  )
  vi.mocked(tasks.getJob).mockImplementation(async (id) => clone(records[id]))
  vi.mocked(tasks.submitJob).mockImplementation(async (request) => {
    const id = 'job-' + request.session_id
    const job: ChatJob = {
      id,
      job_id: id,
      session_id: request.session_id,
      account_id: 'one-account',
      model: request.model,
      state: 'running',
      seq: 1,
      created_at: ++clock,
      updated_at: clock,
      user_content: request.messages[0].content,
      snapshot: { answer: request.session_id + ' partial' }
    }
    records[id] = job
    return clone(job)
  })
  vi.mocked(tasks.jobEvents).mockImplementation(
    async function* (id, token, signal) {
      signals[id] = signal
      yield { type: 'snapshot', seq: records[id].seq, job: clone(records[id]) }
      while (!signal.aborted) {
        const event = await new Promise<JobEvent>((resolve, reject) => {
          const abort = () => reject(new DOMException('Aborted', 'AbortError'))
          signal.addEventListener('abort', abort, { once: true })
          listeners[id] = (event) => {
            signal.removeEventListener('abort', abort)
            resolve(event)
          }
        })
        yield event
        if (event.type === 'terminal') return
      }
    }
  )
  vi.mocked(tasks.waitJobResult).mockImplementation(
    (id, token, signal) =>
      new Promise((resolve, reject) => {
        fullListeners[id] = resolve
        signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true }
        )
      })
  )
  vi.mocked(tasks.cancelJob).mockImplementation(async (id) => {
    const job: ChatJob = {
      ...records[id],
      seq: records[id].seq + 1,
      state: 'cancelled',
      updated_at: ++clock
    }
    records[id] = job
    listeners[id]?.({ type: 'terminal', seq: job.seq, job: clone(job) })
    fullListeners[id]?.(clone(job))
    return clone(job)
  })
  vi.mocked(tasks.uploadAttachment).mockResolvedValue('file-one')
})
afterEach(() => {
  localStorage.clear()
})

async function connect(
  hook: ReturnType<typeof renderHook<ReturnType<typeof useChat>, unknown>>
) {
  act(() => hook.result.current.saveApiToken('unit-token'))
  await act(async () => hook.result.current.loadModels())
  await waitFor(() => {
    expect(hook.result.current.activeSessionId).toBe(a.id)
    expect(hook.result.current.isSessionLoading).toBe(false)
  })
}

describe('server-owned multi-session tasks', () => {
  it('switches from A to B without cancellation and stops B independently', async () => {
    const hook = renderHook(() => useChat())
    await connect(hook)
    await act(async () => hook.result.current.sendMessage('question A'))
    await waitFor(() =>
      expect(hook.result.current.messages.at(-1)?.content).toBe(
        'session-a partial'
      )
    )
    await act(async () => hook.result.current.selectSession(b.id))
    expect(tasks.cancelJob).not.toHaveBeenCalled()
    expect(signals['job-session-a'].aborted).toBe(true)
    expect(hook.result.current.isLoading).toBe(false)
    await act(async () => hook.result.current.sendMessage('question B'))
    await waitFor(() =>
      expect(hook.result.current.messages.at(-1)?.content).toBe(
        'session-b partial'
      )
    )
    await act(async () => hook.result.current.stopStreaming())
    expect(tasks.cancelJob).toHaveBeenCalledWith('job-session-b', 'unit-token')
    expect(records['job-session-a'].state).toBe('running')
    await act(async () => hook.result.current.selectSession(a.id))
    await waitFor(() =>
      expect(hook.result.current.messages.at(-1)?.content).toBe(
        'session-a partial'
      )
    )
    act(() => finish('job-session-a'))
    await waitFor(() =>
      expect(hook.result.current.messages.at(-1)?.content).toBe(
        'session-a final'
      )
    )
    expect(tasks.submitJob).toHaveBeenCalledTimes(2)
    expect(hook.result.current.messages).toHaveLength(2)
    hook.unmount()
  })

  it('recovers a task after remount without a second submission', async () => {
    const first = renderHook(() => useChat())
    await connect(first)
    await act(async () => first.result.current.sendMessage('question'))
    await waitFor(() =>
      expect(first.result.current.messages.at(-1)?.content).toBe(
        'session-a partial'
      )
    )
    first.unmount()
    expect(tasks.cancelJob).not.toHaveBeenCalled()
    const second = renderHook(() => useChat())
    await act(async () => second.result.current.loadModels())
    await waitFor(() =>
      expect(second.result.current.messages.at(-1)?.content).toBe(
        'session-a partial'
      )
    )
    act(() => finish('job-session-a'))
    await waitFor(() =>
      expect(second.result.current.messages.at(-1)?.content).toBe(
        'session-a final'
      )
    )
    expect(tasks.submitJob).toHaveBeenCalledOnce()
    second.unmount()
  })

  it('keeps drafts, model parameters and attachments per session', async () => {
    const hook = renderHook(() => useChat())
    await connect(hook)
    act(() => {
      hook.result.current.setDraft('draft A')
      hook.result.current.addFiles([new File(['x'], 'a.txt')])
      hook.result.current.setThinking(true)
    })
    await act(async () => hook.result.current.selectSession(b.id))
    act(() => {
      hook.result.current.setDraft('draft B')
      hook.result.current.setSelectedModel('model-b')
      hook.result.current.setStreamEnabled(false)
    })
    expect(hook.result.current.pendingFiles).toHaveLength(0)
    await act(async () => hook.result.current.selectSession(a.id))
    expect(hook.result.current.draft).toBe('draft A')
    expect(hook.result.current.selectedModel).toBe('model-a')
    expect(hook.result.current.thinking).toBe(true)
    expect(hook.result.current.streamEnabled).toBe(true)
    expect(hook.result.current.pendingFiles[0].name).toBe('a.txt')
    hook.unmount()
  })

  it('uses the complete result observer without showing intermediate text', async () => {
    const hook = renderHook(() => useChat())
    await connect(hook)
    act(() => hook.result.current.setStreamEnabled(false))
    await act(async () => hook.result.current.sendMessage('full question'))
    await waitFor(() => expect(tasks.waitJobResult).toHaveBeenCalledOnce())
    expect(hook.result.current.messages.at(-1)?.content).toBe('')
    expect(tasks.jobEvents).not.toHaveBeenCalled()
    act(() => finish('job-session-a'))
    await waitFor(() =>
      expect(hook.result.current.messages.at(-1)?.content).toBe(
        'session-a final'
      )
    )
    expect(hook.result.current.isLoading).toBe(false)
    hook.unmount()
  })

  it('shows a failed task with its partial answer and terminal progress', async () => {
    const hook = renderHook(() => useChat())
    await connect(hook)
    await act(async () => hook.result.current.sendMessage('question'))
    await waitFor(() => expect(listeners['job-session-a']).toBeDefined())
    act(() => finish('job-session-a', 'failed'))
    await waitFor(() =>
      expect(hook.result.current.messages.at(-1)?.error).toBe(
        'Upstream interrupted'
      )
    )
    expect(hook.result.current.messages.at(-1)?.content).toBe(
      'session-a partial'
    )
    expect(hook.result.current.messages.at(-1)?.progress?.[0].status).toBe(
      'failed'
    )
    expect(hook.result.current.isLoading).toBe(false)
    hook.unmount()
  })

  it('does not cancel an accepted submission when the page closes before its receipt', async () => {
    const submit = vi.mocked(tasks.submitJob).getMockImplementation()!
    let release!: () => void
    const receipt = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.mocked(tasks.submitJob).mockImplementation(async (...args) => {
      const job = await submit(...args)
      await receipt
      return job
    })
    const hook = renderHook(() => useChat())
    await connect(hook)
    let sending!: Promise<void>
    act(() => {
      sending = hook.result.current.sendMessage('detached')
    })
    await waitFor(() => expect(tasks.submitJob).toHaveBeenCalledOnce())
    hook.unmount()
    release()
    await sending
    expect(tasks.cancelJob).not.toHaveBeenCalled()
    expect(records['job-session-a'].state).toBe('running')
  })

  it('honors an explicit Stop issued before the submission receipt', async () => {
    const submit = vi.mocked(tasks.submitJob).getMockImplementation()!
    let release!: () => void
    const receipt = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.mocked(tasks.submitJob).mockImplementation(async (...args) => {
      const job = await submit(...args)
      await receipt
      return job
    })
    const hook = renderHook(() => useChat())
    await connect(hook)
    let sending!: Promise<void>
    act(() => {
      sending = hook.result.current.sendMessage('stop this')
    })
    await waitFor(() => expect(tasks.submitJob).toHaveBeenCalledOnce())
    await act(async () => hook.result.current.stopStreaming())
    await act(async () => {
      release()
      await sending
    })
    expect(tasks.cancelJob).toHaveBeenCalledWith('job-session-a', 'unit-token')
    expect(records['job-session-a'].state).toBe('cancelled')
    hook.unmount()
  })

  it('reuses the request key and uploaded attachment after a lost response', async () => {
    const hook = renderHook(() => useChat())
    await connect(hook)
    act(() => hook.result.current.addFiles([new File(['x'], 'a.txt')]))
    vi.mocked(tasks.submitJob).mockRejectedValueOnce(
      new TypeError('Network lost')
    )
    await act(async () => hook.result.current.sendMessage('retry this'))
    expect(hook.result.current.error).toBe('Network lost')
    await act(async () => hook.result.current.sendMessage('retry this'))
    expect(tasks.submitJob).toHaveBeenCalledTimes(2)
    expect(vi.mocked(tasks.submitJob).mock.calls[0]).toEqual(
      vi.mocked(tasks.submitJob).mock.calls[1]
    )
    expect(tasks.uploadAttachment).toHaveBeenCalledOnce()
    hook.unmount()
  })

  it('restores an effective thinking model as its base plus thinking flag', async () => {
    vi.mocked(api.getWebUISession).mockResolvedValue({
      ...a,
      model: 'model-a-thinking',
      messages: []
    })
    const hook = renderHook(() => useChat())
    await connect(hook)
    expect(hook.result.current.selectedModel).toBe('model-a')
    expect(hook.result.current.thinking).toBe(true)
    hook.unmount()
  })
})

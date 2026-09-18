import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatJob, JobEvent } from 'lib/api'
import {
  delay,
  getJob,
  isActiveJob,
  jobEvents,
  listJobs,
  waitJobResult
} from 'lib/jobs'

export function useChatJobs(
  token: string,
  activeSessionId: string | null,
  stream: boolean
) {
  const activeRef = useRef(activeSessionId)
  activeRef.current = activeSessionId
  const [jobs, setJobs] = useState<Record<string, ChatJob>>({})
  const jobsRef = useRef<Record<string, ChatJob>>({})
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [observationError, setObservationError] = useState<string | null>(null)

  const remember = useCallback((incoming: ChatJob) => {
    const old = jobsRef.current[incoming.session_id]
    if (
      old &&
      ((old.id !== incoming.id && old.created_at > incoming.created_at) ||
        (old.id === incoming.id &&
          (old.seq > incoming.seq || old.updated_at > incoming.updated_at)))
    )
      return
    const job =
      old?.id === incoming.id
        ? { ...old, ...incoming, snapshot: incoming.snapshot || old.snapshot }
        : incoming
    jobsRef.current = { ...jobsRef.current, [job.session_id]: job }
    const flush = () => {
      flushTimer.current = null
      setJobs(jobsRef.current)
    }
    if (
      !old ||
      old.id !== job.id ||
      old.state !== job.state ||
      !isActiveJob(job)
    ) {
      if (flushTimer.current) clearTimeout(flushTimer.current)
      flush()
    } else if (!flushTimer.current) {
      flushTimer.current = setTimeout(flush, 50)
    }
  }, [])

  const acceptEvent = useCallback(
    (id: string, event: JobEvent) => {
      if (event.job) {
        remember(event.job)
        return
      }
      const current = Object.values(jobsRef.current).find(
        (job) => job.id === id
      )
      if (!current || event.seq <= current.seq || event.type === 'heartbeat')
        return
      const data = event.data || {}
      const snapshot = { ...current.snapshot, ...data }
      if (event.type === 'delta')
        snapshot.answer =
          (current.snapshot?.answer || '') + (data.content || '')
      remember({
        ...current,
        seq: event.seq,
        state: data.state || current.state,
        snapshot
      })
    },
    [remember]
  )

  useEffect(() => {
    const controller = new AbortController()
    jobsRef.current = {}
    setJobs({})
    setObservationError(null)
    if (token) {
      void (async () => {
        while (!controller.signal.aborted) {
          try {
            const items = await listJobs(token, controller.signal)
            if (controller.signal.aborted) return
            for (const item of items) {
              const old = jobsRef.current[item.session_id]
              // Metadata polling must not advance the active observer's content cursor.
              if (old?.id === item.id && item.session_id === activeRef.current)
                continue
              if (
                old?.id === item.id &&
                isActiveJob(old) &&
                !isActiveJob(item)
              ) {
                const final = await getJob(item.id, token, controller.signal)
                if (controller.signal.aborted) return
                remember(final)
              } else remember(item)
            }
            const keep = new Set(items.map((item) => item.session_id))
            if (activeRef.current) keep.add(activeRef.current)
            jobsRef.current = Object.fromEntries(
              Object.entries(jobsRef.current).filter(([id]) => keep.has(id))
            )
          } catch {
            /* The active observer reports connection failures. */
          }
          try {
            await delay(2000, controller.signal)
          } catch {
            return
          }
        }
      })()
    }
    return () => {
      controller.abort()
      if (flushTimer.current) clearTimeout(flushTimer.current)
      flushTimer.current = null
    }
  }, [token, remember])

  const activeJobId = activeSessionId ? jobs[activeSessionId]?.id : undefined
  useEffect(() => {
    const controller = new AbortController()
    setObservationError(null)
    if (!token || !activeJobId) return () => controller.abort()
    void (async () => {
      let retries = 0
      while (!controller.signal.aborted) {
        try {
          const current = await getJob(activeJobId, token, controller.signal)
          if (controller.signal.aborted) return
          remember(current)
          if (!isActiveJob(current)) return
          if (stream) {
            for await (const event of jobEvents(
              activeJobId,
              token,
              controller.signal
            )) {
              if (controller.signal.aborted) return
              setObservationError(null)
              acceptEvent(activeJobId, event)
            }
          } else {
            const result = await waitJobResult(
              activeJobId,
              token,
              controller.signal
            )
            if (controller.signal.aborted) return
            remember(result)
            if (!isActiveJob(result)) return
          }
          retries = 0
        } catch (error) {
          if (controller.signal.aborted) return
          setObservationError(
            error instanceof Error ? error.message : 'Reconnecting to task…'
          )
          retries++
          try {
            await delay(
              Math.min(5000, 500 * 2 ** Math.min(retries, 3)),
              controller.signal
            )
          } catch {
            return
          }
        }
      }
    })()
    // Closing this observer never cancels the server-owned task.
    return () => controller.abort()
  }, [activeJobId, token, stream, remember, acceptEvent])

  return { jobs, jobsRef, remember, observationError }
}

import { useState } from 'react'
import { PerplexityProgress } from 'lib/api'

interface ProgressTimelineProps {
  progress: PerplexityProgress[]
}

function ProgressIcon({ status }: { status: PerplexityProgress['status'] }) {
  if (status === 'running') {
    return (
      <span
        aria-hidden="true"
        className="h-3 w-3 rounded-full border-2 border-neon-blue/30 border-t-neon-blue animate-spin"
      />
    )
  }
  if (status === 'completed') {
    return (
      <span aria-hidden="true" className="text-acid font-bold">
        ✓
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span aria-hidden="true" className="text-red-400 font-bold">
        !
      </span>
    )
  }
  return (
    <span aria-hidden="true" className="text-gray-500 font-bold">
      –
    </span>
  )
}

export function ProgressTimeline({ progress }: ProgressTimelineProps) {
  const [isOpen, setIsOpen] = useState(true)
  const active = progress.find((item) => item.status === 'running')
  const failed = progress.find((item) => item.status === 'failed')
  const completedCount = progress.filter(
    (item) => item.status === 'completed'
  ).length
  const summary =
    active?.label ||
    failed?.label ||
    `${completedCount}/${progress.length} steps completed`

  if (progress.length === 0) return null

  return (
    <div
      className="mb-4 border border-gray-700 bg-black/30 font-mono text-xs"
      aria-live="polite"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-gray-300 hover:bg-gray-800/50"
        onClick={() => setIsOpen((value) => !value)}
        aria-expanded={isOpen}
      >
        <span className="flex min-w-0 items-center gap-2">
          {active ? (
            <span className="h-2 w-2 shrink-0 rounded-full bg-neon-blue animate-pulse" />
          ) : (
            <span className="text-acid">◆</span>
          )}
          <span className="truncate">{summary}</span>
        </span>
        <span className="shrink-0 text-gray-500">[{isOpen ? '−' : '+'}]</span>
      </button>

      {isOpen && (
        <ol className="space-y-2 border-t border-gray-800 px-3 py-3">
          {progress.map((item) => (
            <li
              key={item.id}
              data-status={item.status}
              className="grid grid-cols-[1rem_1fr] gap-2 text-gray-400"
            >
              <span className="flex h-5 items-center justify-center">
                <ProgressIcon status={item.status} />
              </span>
              <div className="min-w-0">
                <div
                  className={
                    item.status === 'running'
                      ? 'text-neon-blue'
                      : item.status === 'failed'
                        ? 'text-red-400'
                        : item.status === 'cancelled'
                          ? 'text-gray-500'
                          : 'text-gray-300'
                  }
                >
                  {item.label}
                </div>

                {item.detail?.queries && item.detail.queries.length > 0 && (
                  <ul className="mt-1 space-y-1 text-[11px] text-gray-500">
                    {item.detail.queries.map((query, index) => (
                      <li
                        key={`${item.id}-query-${index}`}
                        className="truncate"
                      >
                        ↳ {query}
                      </li>
                    ))}
                  </ul>
                )}

                {typeof item.detail?.source_count === 'number' && (
                  <div className="mt-1 text-[11px] text-gray-500">
                    {item.detail.source_count}{' '}
                    {item.detail.source_count === 1 ? 'source' : 'sources'}{' '}
                    found
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

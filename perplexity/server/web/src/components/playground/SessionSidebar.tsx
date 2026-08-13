import { FormEvent, useEffect, useRef, useState } from 'react'
import { ChatSession } from 'lib/api'

interface SessionSidebarProps {
  sessions: ChatSession[]
  activeSessionId: string | null
  disabled?: boolean
  connected: boolean
  onNew: () => void
  onSelect: (sessionId: string) => void
  onRename: (sessionId: string, title: string) => Promise<boolean>
  onDelete: (sessionId: string) => void
  onClose?: () => void
}

function updatedLabel(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  disabled = false,
  connected,
  onNew,
  onSelect,
  onRename,
  onDelete,
  onClose
}: SessionSidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId) inputRef.current?.focus()
  }, [editingId])

  const beginRename = (session: ChatSession) => {
    setEditingId(session.id)
    setTitle(session.title)
  }

  const submitRename = async (event: FormEvent) => {
    event.preventDefault()
    if (!editingId || !title.trim()) return
    if (await onRename(editingId, title.trim())) setEditingId(null)
  }

  const requestDelete = (session: ChatSession) => {
    if (window.confirm(`Delete “${session.title}”? This cannot be undone.`)) {
      onDelete(session.id)
    }
  }

  return (
    <aside
      aria-label="Conversations"
      className="flex h-full w-[292px] flex-col border-r-2 border-gray-800 bg-[#0b0b0b] text-gray-200"
    >
      <div className="flex items-center justify-between border-b border-gray-800 p-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-neon-blue">
            Native threads
          </p>
          <h2 className="mt-1 text-lg font-black uppercase tracking-tight">
            Conversations
          </h2>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="grid size-9 place-items-center border border-gray-700 text-gray-400 transition-colors hover:border-white hover:text-white"
            aria-label="Close conversations"
          >
            ×
          </button>
        )}
      </div>

      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          disabled={!connected || disabled}
          className="flex w-full items-center justify-between border-2 border-acid bg-acid px-4 py-3 font-mono text-xs font-black uppercase text-void shadow-[3px_3px_0_#fff] transition-transform hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <span>New conversation</span>
          <span className="text-lg leading-none">＋</span>
        </button>
      </div>

      <div className="scrollbar-hidden flex-1 space-y-1 overflow-y-auto px-3 pb-4">
        {!connected && (
          <p className="border border-dashed border-gray-700 px-3 py-4 font-mono text-xs leading-relaxed text-gray-500">
            Connect with your API token to load conversations.
          </p>
        )}
        {connected && sessions.length === 0 && (
          <p className="px-3 py-6 text-center font-mono text-xs text-gray-500">
            Loading conversations…
          </p>
        )}

        {sessions.map((session) => {
          const active = session.id === activeSessionId
          const editing = session.id === editingId
          return (
            <div
              key={session.id}
              data-active={active ? 'true' : 'false'}
              className={`group relative border transition-colors ${
                active
                  ? 'border-neon-blue bg-neon-blue/10'
                  : 'border-transparent hover:border-gray-700 hover:bg-gray-900'
              }`}
            >
              {editing ? (
                <form onSubmit={submitRename} className="p-2">
                  <input
                    ref={inputRef}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    onBlur={() => setEditingId(null)}
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') setEditingId(null)
                    }}
                    maxLength={120}
                    className="w-full border border-neon-blue bg-void px-2 py-1 text-sm outline-none"
                    aria-label="Conversation title"
                  />
                </form>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(session.id)
                      onClose?.()
                    }}
                    disabled={disabled}
                    className="w-full p-3 pr-16 text-left disabled:cursor-not-allowed"
                    aria-current={active ? 'page' : undefined}
                    aria-label={`Open ${session.title}`}
                  >
                    <span className="block truncate text-sm font-semibold text-gray-100">
                      {session.title}
                    </span>
                    <span className="mt-1 flex items-center gap-2 font-mono text-[10px] uppercase text-gray-500">
                      <span>{updatedLabel(session.updated_at)}</span>
                      {session.bound_client_id && (
                        <span
                          className="max-w-[125px] truncate text-acid/70"
                          title={`Locked to ${session.bound_client_id}`}
                        >
                          🔒 {session.bound_client_id}
                        </span>
                      )}
                    </span>
                  </button>
                  <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    <button
                      type="button"
                      onClick={() => beginRename(session)}
                      disabled={disabled}
                      className="grid size-7 place-items-center border border-gray-700 bg-void text-xs text-gray-400 hover:border-neon-blue hover:text-neon-blue disabled:opacity-40"
                      aria-label={`Rename ${session.title}`}
                      title="Rename"
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      onClick={() => requestDelete(session)}
                      disabled={disabled}
                      className="grid size-7 place-items-center border border-gray-700 bg-void text-xs text-gray-400 hover:border-danger hover:text-danger disabled:opacity-40"
                      aria-label={`Delete ${session.title}`}
                      title="Delete"
                    >
                      ×
                    </button>
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>

      <div className="border-t border-gray-800 px-4 py-3 font-mono text-[10px] leading-relaxed text-gray-500">
        A conversation locks to one account after its first send. Start a new
        one to use a different account.
      </div>
    </aside>
  )
}

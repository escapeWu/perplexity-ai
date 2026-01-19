import { useState } from 'react'
import { ClientInfo, apiCall } from 'lib/api'

interface TokenTableProps {
  clients: ClientInfo[]
  adminToken: string
  isAuthenticated: boolean
  onToast: (message: string, type: 'success' | 'error') => void
  onRefresh: () => void
  onAddClick: () => void
  onConfirmDelete: (id: string) => void
}

export function TokenTable({
  clients,
  adminToken,
  isAuthenticated,
  onToast,
  onRefresh,
  onAddClick,
  onConfirmDelete,
}: TokenTableProps) {
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set())

  const getWeightColor = (weight: number) => {
    if (weight >= 70) return 'bg-acid'
    if (weight >= 40) return 'bg-yellow-500'
    return 'bg-danger'
  }

  const maskIdentifier = (id: string) => {
    if (!id || id.length <= 6) return id
    const start = id.substring(0, 3)
    const end = id.substring(id.length - 3)
    return `${start}***${end}`
  }

  const handleClientAction = async (action: string, id: string) => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    const resp = await apiCall(action, { id }, adminToken)
    const actionMap: Record<string, string> = {
      enable: 'ONLINE',
      disable: 'OFFLINE',
      reset: 'RESET',
    }

    if (resp.status === 'ok') {
      onToast(`CLIENT_${id}_${actionMap[action]}`, 'success')
      onRefresh()
    } else {
      onToast(resp.message || 'ERROR', 'error')
    }
  }

  const handleTestClient = async (id: string) => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    setTestingIds((prev) => new Set(prev).add(id))
    try {
      const resp = await apiCall('heartbeat/test', { id }, adminToken)
      if (resp.status === 'ok') {
        onToast(`TEST_${id}_OK`, 'success')
        onRefresh()
      } else {
        onToast(resp.message || 'TEST_FAILED', 'error')
      }
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  return (
    <div className="border-2 border-white bg-black p-1 shadow-[8px_8px_0px_0px_rgba(255,255,255,0.2)]">
      <div className="bg-gray-900 border border-gray-800 p-4 md:p-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4 border-b border-gray-800 pb-6">
          <h2 className="text-2xl font-bold uppercase tracking-tight flex items-center gap-3">
            <span className="w-3 h-3 bg-acid block animate-pulse"></span>
            Active Tokens
          </h2>
          <button
            onClick={() => {
              if (!isAuthenticated) {
                onToast('AUTH_REQUIRED', 'error')
                return
              }
              onAddClick()
            }}
            className={`px-4 py-2 font-bold border transition-all font-mono text-sm uppercase shadow-hard-acid hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] ${
              isAuthenticated
                ? 'bg-acid text-black border-acid hover:bg-transparent hover:text-acid'
                : 'bg-gray-700 text-gray-500 border-gray-600 cursor-not-allowed'
            }`}
          >
            + NEW TOKEN
          </button>
        </div>

        <div className="overflow-x-auto">
          {!clients || clients.length === 0 ? (
            <div className="text-center py-20 font-mono text-gray-500 border-2 border-dashed border-gray-800">
              NO_DATA_FOUND // INJECT_NEW_TOKEN
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b-2 border-gray-700">
                  <th className="p-4 font-mono text-xs text-gray-500 uppercase tracking-widest">
                    Identifier
                  </th>
                  <th className="p-4 font-mono text-xs text-gray-500 uppercase tracking-widest">
                    State
                  </th>
                  <th className="p-4 font-mono text-xs text-gray-500 uppercase tracking-widest">
                    Dynamic Weight
                  </th>
                  <th className="p-4 font-mono text-xs text-gray-500 uppercase tracking-widest">
                    Reqs
                  </th>
                  <th className="p-4 font-mono text-xs text-gray-500 uppercase tracking-widest">
                    Last Check
                  </th>
                  <th className="p-4 font-mono text-xs text-gray-500 uppercase tracking-widest text-right">
                    Controls
                  </th>
                </tr>
              </thead>
              <tbody className="font-mono text-sm">
                {clients.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-gray-800 hover:bg-gray-900/50 transition-colors group"
                  >
                    <td className="p-4 font-bold text-white">
                      <span className="text-neon-blue mr-2">&gt;</span>
                      {maskIdentifier(c.id)}
                    </td>
                    <td className="p-4">
                      {!c.enabled ? (
                        <span className="px-2 py-1 bg-gray-800 text-gray-500 text-xs border border-gray-700">
                          DISABLED
                        </span>
                      ) : !c.available ? (
                        <span className="px-2 py-1 bg-yellow-900/30 text-yellow-400 text-xs border border-yellow-900">
                          BACKOFF
                        </span>
                      ) : c.state === 'offline' ? (
                        <span className="px-2 py-1 bg-red-900/30 text-red-400 text-xs border border-red-900">
                          OFFLINE
                        </span>
                      ) : c.state === 'normal' ? (
                        <span className="px-2 py-1 bg-green-900/30 text-green-400 text-xs border border-green-900">
                          HEALTHY
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-blue-900/30 text-blue-400 text-xs border border-blue-900">
                          READY
                        </span>
                      )}
                    </td>
                    <td className="p-4">
                      <div className="flex items-center gap-3">
                        <div className="w-24 h-2 bg-gray-800 border border-gray-700 overflow-hidden">
                          <div
                            className={`h-full ${getWeightColor(c.weight)} transition-all duration-500`}
                            style={{ width: `${c.weight}%` }}
                          ></div>
                        </div>
                        <span className="text-xs text-gray-500">{c.weight}%</span>
                      </div>
                    </td>
                    <td className="p-4 text-gray-400">
                      <div>{c.request_count || 0}</div>
                      <div
                        className={
                          c.fail_count > 0 || c.pro_fail_count > 0
                            ? 'text-danger text-xs'
                            : 'text-gray-600 text-xs'
                        }
                      >
                        E:{c.fail_count} / P:{c.pro_fail_count}
                      </div>
                    </td>
                    <td className="p-4 text-gray-500 text-xs">
                      {c.last_heartbeat_at
                        ? new Date(c.last_heartbeat_at).toLocaleTimeString()
                        : '-'}
                    </td>
                    <td className="p-4 text-right">
                      <div
                        className={`flex justify-end gap-2 ${isAuthenticated ? '' : 'opacity-50'}`}
                      >
                        {c.enabled ? (
                          <button
                            className={`p-1 transition-colors ${isAuthenticated ? 'hover:text-yellow-500' : 'cursor-not-allowed'}`}
                            onClick={() => handleClientAction('disable', c.id)}
                            title="Disable"
                            disabled={!isAuthenticated}
                          >
                            [PAUSE]
                          </button>
                        ) : (
                          <button
                            className={`p-1 transition-colors ${isAuthenticated ? 'hover:text-green-500' : 'cursor-not-allowed'}`}
                            onClick={() => handleClientAction('enable', c.id)}
                            title="Enable"
                            disabled={!isAuthenticated}
                          >
                            [RESUME]
                          </button>
                        )}
                        <button
                          className={`p-1 transition-colors ${
                            isAuthenticated && !testingIds.has(c.id)
                              ? 'hover:text-neon-blue'
                              : 'cursor-not-allowed opacity-50'
                          }`}
                          onClick={() => handleTestClient(c.id)}
                          title="Test Heartbeat"
                          disabled={!isAuthenticated || testingIds.has(c.id)}
                        >
                          [TEST]
                        </button>
                        <button
                          className={`p-1 transition-colors ${isAuthenticated ? 'hover:text-danger' : 'cursor-not-allowed'}`}
                          onClick={() => onConfirmDelete(c.id)}
                          title="Remove"
                          disabled={!isAuthenticated}
                        >
                          [DEL]
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

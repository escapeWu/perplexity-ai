import { useState } from 'react'
import { ClientInfo, apiCall, updateFallbackConfig, updateIncognitoConfig, downloadSingleTokenConfig } from 'lib/api'

interface TokenTableProps {
  clients: ClientInfo[]
  adminToken: string
  isAuthenticated: boolean
  fallbackToAuto: boolean
  incognitoEnabled: boolean
  onToast: (message: string, type: 'success' | 'error') => void
  onRefresh: () => void
  onAddClick: () => void
  onConfirmDelete: (id: string) => void
  onFallbackChange: (enabled: boolean) => void
  onIncognitoChange: (enabled: boolean) => void
}

export function TokenTable({
  clients,
  adminToken,
  isAuthenticated,
  fallbackToAuto,
  incognitoEnabled,
  onToast,
  onRefresh,
  onAddClick,
  onConfirmDelete,
  onFallbackChange,
  onIncognitoChange,
}: TokenTableProps) {
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set())
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set())
  const [updatingFallback, setUpdatingFallback] = useState(false)
  const [updatingIncognito, setUpdatingIncognito] = useState(false)

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
        onToast(resp.error || resp.message || 'TEST_FAILED', 'error')
      }
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const handleToggleFallback = async () => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    setUpdatingFallback(true)
    try {
      const newValue = !fallbackToAuto
      const resp = await updateFallbackConfig({ fallback_to_auto: newValue }, adminToken)
      if (resp.status === 'ok') {
        onFallbackChange(newValue)
        onToast(
          newValue
            ? 'Downgrade mode active. If req fail, Perplexity free model will auto use.'
            : 'Pro mode active. If req fail, will throw error.',
          'success'
        )
      } else {
        onToast(resp.message || 'ERROR', 'error')
      }
    } finally {
      setUpdatingFallback(false)
    }
  }

  const handleToggleIncognito = async () => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    setUpdatingIncognito(true)
    try {
      const newValue = !incognitoEnabled
      const resp = await updateIncognitoConfig({ enabled: newValue }, adminToken)
      if (resp.status === 'ok') {
        onIncognitoChange(newValue)
        onToast(
          newValue
            ? 'Incognito mode ON. All queries will not save history.'
            : 'Incognito mode OFF. Queries will save history normally.',
          'success'
        )
      } else {
        onToast(resp.message || 'ERROR', 'error')
      }
    } finally {
      setUpdatingIncognito(false)
    }
  }

  const handleDownload = async (id: string) => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    setDownloadingIds((prev) => new Set(prev).add(id))
    try {
      const config = await downloadSingleTokenConfig(id, adminToken)
      const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `token_${id.replace(/[^a-zA-Z0-9]/g, '_')}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      onToast('CONFIG_DOWNLOADED', 'success')
    } catch (err) {
      onToast(err instanceof Error ? err.message : 'DOWNLOAD_FAILED', 'error')
    } finally {
      setDownloadingIds((prev) => {
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
          <div className="flex gap-3">
            <button
              onClick={handleToggleIncognito}
              disabled={!isAuthenticated || updatingIncognito}
              className={`px-4 py-2 font-bold border transition-all font-mono text-sm uppercase flex items-center gap-2 ${
                !isAuthenticated || updatingIncognito
                  ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                  : incognitoEnabled
                    ? 'bg-purple-500 text-black border-purple-500 shadow-[4px_4px_0px_0px_rgba(168,85,247,0.5)] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] hover:bg-white'
                    : 'bg-gray-600 text-white border-gray-600 shadow-[4px_4px_0px_0px_rgba(75,85,99,0.5)] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] hover:bg-white hover:text-black'
              }`}
            >
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d={incognitoEnabled
                    ? "M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"
                    : "M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                  }
                />
              </svg>
              {updatingIncognito ? '...' : incognitoEnabled ? 'INCOGNITO' : 'NORMAL'}
            </button>
            <button
              onClick={handleToggleFallback}
              disabled={!isAuthenticated || updatingFallback}
              className={`px-4 py-2 font-bold border transition-all font-mono text-sm uppercase flex items-center gap-2 ${
                !isAuthenticated || updatingFallback
                  ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                  : fallbackToAuto
                    ? 'bg-orange-500 text-black border-orange-500 shadow-[4px_4px_0px_0px_rgba(249,115,22,0.5)] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] hover:bg-white'
                    : 'bg-green-500 text-black border-green-500 shadow-[4px_4px_0px_0px_rgba(34,197,94,0.5)] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] hover:bg-white'
              }`}
            >
              <svg
                className={`w-4 h-4 transition-transform ${fallbackToAuto ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"
                />
              </svg>
              {updatingFallback ? '...' : fallbackToAuto ? 'DOWNGRADE' : 'PRO'}
            </button>
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
                  ? 'bg-neon-pink text-black border-neon-pink hover:bg-white'
                  : 'bg-gray-700 text-gray-500 border-gray-600 cursor-not-allowed'
              }`}
            >
              + NEW TOKEN
            </button>
          </div>
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
                {clients.map((c) => {
                const isDisabledInProOnlyMode = !fallbackToAuto && c.state === 'downgrade'
                return (
                  <tr
                    key={c.id}
                    className={`border-b border-gray-800 transition-colors group ${
                      isDisabledInProOnlyMode
                        ? 'opacity-40 bg-gray-900/30'
                        : 'hover:bg-gray-900/50'
                    }`}
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
                      ) : c.state === 'downgrade' ? (
                        <span className="px-2 py-1 bg-orange-900/30 text-orange-400 text-xs border border-orange-900">
                          DOWNGRADE
                        </span>
                      ) : c.state === 'normal' ? (
                        <span className="px-2 py-1 bg-green-900/30 text-green-400 text-xs border border-green-900">
                          PRO
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
                        <button
                          className={`p-1 transition-colors ${
                            isAuthenticated && !downloadingIds.has(c.id)
                              ? 'hover:text-neon-blue'
                              : 'cursor-not-allowed opacity-50'
                          }`}
                          onClick={() => handleDownload(c.id)}
                          title="Download Config"
                          disabled={!isAuthenticated || downloadingIds.has(c.id)}
                        >
                          {downloadingIds.has(c.id) ? '[...]' : '[DL]'}
                        </button>
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
                )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

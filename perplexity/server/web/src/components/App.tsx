import { useState, useCallback } from 'react'
import { useAuth } from 'hooks/useAuth'
import { useToast } from 'hooks/useToast'
import { usePool } from 'hooks/usePool'
import { useVersionCheck } from 'hooks/useVersionCheck'
import { apiCall, importTokenConfig, TokenConfig } from 'lib/api'
import { AuthBar } from './AuthBar'
import { StatsGrid } from './StatsGrid'
import { HeartbeatPanel } from './HeartbeatPanel'
import { TokenTable } from './TokenTable'
import { AddTokenModal } from './AddTokenModal'
import { ConfirmModal } from './ConfirmModal'
import { Toast } from './ui/Toast'
import { LogsPanel } from './logs/LogsPanel'

type TabType = 'pool' | 'logs'

export function App() {
  const { adminToken, isAuthenticated, login, logout } = useAuth()
  const { toasts, addToast, removeToast } = useToast()
  const { data, hbConfig, setHbConfig, fallbackConfig, setFallbackConfig, incognitoConfig, setIncognitoConfig, lastSync, refreshData } = usePool()
  const versionInfo = useVersionCheck()

  const [activeTab, setActiveTab] = useState<TabType>('pool')
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isConfirmModalOpen, setIsConfirmModalOpen] = useState(false)
  const [confirmMessage, setConfirmMessage] = useState('')
  const [confirmAction, setConfirmAction] = useState<(() => void) | null>(null)

  const handleLogout = useCallback(() => {
    logout()
    addToast('LOGGED_OUT', 'success')
  }, [logout, addToast])

  const handleAddToken = useCallback(
    async (id: string, csrf: string, session: string) => {
      if (!id || !csrf || !session) {
        addToast('MISSING_FIELDS', 'error')
        return
      }

      const resp = await apiCall(
        'add',
        {
          id,
          csrf_token: csrf,
          session_token: session,
        },
        adminToken
      )

      if (resp.status === 'ok') {
        addToast('TOKEN_INJECTED', 'success')
        setIsAddModalOpen(false)
        refreshData()
      } else {
        addToast(resp.message || 'ERROR', 'error')
      }
    },
    [adminToken, addToast, refreshData]
  )

  const handleDeleteToken = useCallback(
    async (id: string) => {
      const resp = await apiCall('remove', { id }, adminToken)
      if (resp.status === 'ok') {
        addToast('TOKEN_DELETED', 'success')
        refreshData()
      } else {
        addToast(resp.message || 'ERROR', 'error')
      }
    },
    [adminToken, addToast, refreshData]
  )

  const handleImportConfig = useCallback(
    async (tokens: TokenConfig[]) => {
      try {
        const resp = await importTokenConfig(tokens, adminToken)
        if (resp.status === 'ok') {
          addToast(`IMPORTED_${tokens.length}_TOKENS`, 'success')
          setIsAddModalOpen(false)
          refreshData()
        } else {
          addToast(resp.message || 'IMPORT_FAILED', 'error')
        }
      } catch (err) {
        addToast(err instanceof Error ? err.message : 'IMPORT_FAILED', 'error')
      }
    },
    [adminToken, addToast, refreshData]
  )

  const confirmDelete = useCallback(
    (id: string) => {
      if (!isAuthenticated) {
        addToast('AUTH_REQUIRED', 'error')
        return
      }
      setConfirmMessage(
        `Are you sure you want to permanently delete token "${id}"? This action is irreversible.`
      )
      setConfirmAction(() => () => handleDeleteToken(id))
      setIsConfirmModalOpen(true)
    },
    [isAuthenticated, addToast, handleDeleteToken]
  )

  const executeConfirm = useCallback(() => {
    if (confirmAction) confirmAction()
    setIsConfirmModalOpen(false)
  }, [confirmAction])

  return (
    <div className="min-h-screen text-gray-200 font-sans p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <header className="mb-8 border-b-4 border-white pb-6">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
            <div>
              <h1 className="text-5xl md:text-7xl font-black uppercase tracking-tighter leading-none text-white mix-blend-difference">
                Perplexity
                <br />
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-acid via-neon-pink to-neon-blue">
                  Token Pool
                </span>
              </h1>
              <p className="font-mono text-gray-400 mt-2 bg-gray-900 inline-block px-2">
                /// MANAGER_v{__APP_VERSION__}
              </p>
              {versionInfo.hasUpdate && (
                <a
                  href={versionInfo.releaseUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-3 font-mono text-xs bg-neon-pink text-gray-900 px-2 py-1 uppercase font-bold hover:bg-white transition-colors animate-pulse"
                >
                  Update Available: {versionInfo.latestVersion}
                </a>
              )}
            </div>
            <div className="font-mono text-xs md:text-sm text-right">
              <a
                href="/playground/"
                className="inline-block mb-2 text-neon-pink hover:text-acid border-2 border-neon-pink hover:border-acid px-3 py-1 transition-colors uppercase"
              >
                API Playground &rarr;
              </a>
              <div className="text-acid">
                {lastSync ? `LAST_SYNC: ${lastSync}` : 'SYNCING...'}
              </div>
              <div className="text-gray-500">SYSTEM_STATUS: ONLINE</div>
            </div>
          </div>
        </header>

        {/* Auth Bar */}
        <AuthBar
          adminToken={adminToken}
          isAuthenticated={isAuthenticated}
          onLogin={login}
          onLogout={handleLogout}
          onAuthError={(msg) => addToast(msg, 'error')}
        />

        {/* Tab Navigation - Only show Logs tab when authenticated */}
        {isAuthenticated && (
          <div className="mb-6 flex gap-2">
            <button
              onClick={() => setActiveTab('pool')}
              className={`border-2 px-4 py-2 font-mono uppercase transition-colors ${
                activeTab === 'pool'
                  ? 'border-acid bg-acid/10 text-acid'
                  : 'border-gray-600 text-gray-400 hover:border-gray-400'
              }`}
            >
              Token Pool
            </button>
            <button
              onClick={() => setActiveTab('logs')}
              className={`border-2 px-4 py-2 font-mono uppercase transition-colors ${
                activeTab === 'logs'
                  ? 'border-acid bg-acid/10 text-acid'
                  : 'border-gray-600 text-gray-400 hover:border-gray-400'
              }`}
            >
              Logs
            </button>
          </div>
        )}

        {/* Tab Content */}
        {activeTab === 'pool' ? (
          <>
            {/* Stats Grid */}
            <StatsGrid data={data} hbConfig={hbConfig} />

            {/* Heartbeat Controls */}
            {isAuthenticated && hbConfig && (
              <HeartbeatPanel
                hbConfig={hbConfig}
                adminToken={adminToken}
                isAuthenticated={isAuthenticated}
                onConfigUpdate={setHbConfig}
                onToast={addToast}
                onRefresh={refreshData}
              />
            )}

            {/* Token Table */}
            <TokenTable
              clients={data.clients}
              adminToken={adminToken}
              isAuthenticated={isAuthenticated}
              fallbackToAuto={fallbackConfig.fallback_to_auto}
              incognitoEnabled={incognitoConfig.enabled}
              onToast={addToast}
              onRefresh={refreshData}
              onAddClick={() => setIsAddModalOpen(true)}
              onConfirmDelete={confirmDelete}
              onFallbackChange={(enabled) => setFallbackConfig({ fallback_to_auto: enabled })}
              onIncognitoChange={(enabled) => setIncognitoConfig({ enabled })}
            />
          </>
        ) : (
          /* Logs Panel */
          <LogsPanel adminToken={adminToken} />
        )}

        {/* Add Token Modal */}
        <AddTokenModal
          isOpen={isAddModalOpen}
          onClose={() => setIsAddModalOpen(false)}
          onSubmit={handleAddToken}
          onImportConfig={handleImportConfig}
        />

        {/* Confirm Modal */}
        <ConfirmModal
          isOpen={isConfirmModalOpen}
          message={confirmMessage}
          onClose={() => setIsConfirmModalOpen(false)}
          onConfirm={executeConfirm}
        />

        {/* Toasts */}
        {toasts.map((t) => (
          <Toast key={t.id} message={t.message} type={t.type} onClose={() => removeToast(t.id)} />
        ))}
      </div>
    </div>
  )
}

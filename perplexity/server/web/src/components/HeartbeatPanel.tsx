import { useState } from 'react'
import { HeartbeatConfig, updateHeartbeatConfig, apiCall } from 'lib/api'

interface HeartbeatPanelProps {
  hbConfig: HeartbeatConfig
  adminToken: string
  isAuthenticated: boolean
  onConfigUpdate: (config: HeartbeatConfig) => void
  onToast: (message: string, type: 'success' | 'error') => void
  onRefresh: () => void
}

export function HeartbeatPanel({
  hbConfig,
  adminToken,
  isAuthenticated,
  onConfigUpdate,
  onToast,
  onRefresh,
}: HeartbeatPanelProps) {
  const [isConfigOpen, setIsConfigOpen] = useState(false)
  const [isGlobalTesting, setIsGlobalTesting] = useState(false)
  const [configForm, setConfigForm] = useState({
    enable: hbConfig.enable,
    question: hbConfig.question,
    interval: hbConfig.interval,
    tg_bot_token: hbConfig.tg_bot_token,
    tg_chat_id: hbConfig.tg_chat_id,
  })

  const handleHeartbeatAction = async (action: string) => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    if (action === 'test') {
      setIsGlobalTesting(true)
    }

    try {
      const resp = await apiCall(`heartbeat/${action}`, {}, adminToken)
      if (resp.status === 'ok') {
        onToast(`HEARTBEAT_${action.toUpperCase()}_OK`, 'success')
        onRefresh()
      } else {
        onToast(resp.message || 'ERROR', 'error')
      }
    } finally {
      if (action === 'test') {
        setIsGlobalTesting(false)
      }
    }
  }

  const handleSaveConfig = async () => {
    if (!isAuthenticated) {
      onToast('AUTH_REQUIRED', 'error')
      return
    }

    try {
      const resp = await updateHeartbeatConfig(configForm, adminToken)
      if (resp.status === 'ok' && resp.config) {
        onToast('CONFIG_SAVED', 'success')
        onConfigUpdate(resp.config)
        setIsConfigOpen(false)
      } else {
        onToast(resp.message || 'SAVE_FAILED', 'error')
      }
    } catch {
      onToast('SAVE_FAILED', 'error')
    }
  }

  return (
    <div className="mb-8 p-4 border border-gray-700 bg-gray-900/30">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h3 className="font-bold text-white uppercase tracking-wider">♥ Heartbeat Control</h3>
          <div className="text-xs font-mono text-gray-500">INTERVAL: {hbConfig.interval}H</div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsConfigOpen(!isConfigOpen)}
            className="px-3 py-1 bg-gray-800 border border-gray-600 hover:bg-white hover:text-black font-mono text-xs uppercase transition-colors"
          >
            {isConfigOpen ? 'Hide Config' : 'Config'}
          </button>
          <button
            onClick={() => handleHeartbeatAction('test')}
            disabled={isGlobalTesting}
            className={`px-3 py-1 border border-neon-blue text-neon-blue font-mono text-xs uppercase transition-colors ${
              isGlobalTesting
                ? 'opacity-50 cursor-not-allowed'
                : 'hover:bg-neon-blue hover:text-black'
            }`}
          >
            {isGlobalTesting ? 'Testing...' : 'Test All'}
          </button>
        </div>
      </div>

      {isConfigOpen && (
        <div className="border-t border-gray-700 pt-4 mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div>
              <label className="block font-mono text-xs text-gray-500 mb-1 uppercase">
                Enable
              </label>
              <select
                value={configForm.enable ? 'true' : 'false'}
                onChange={(e) =>
                  setConfigForm({ ...configForm, enable: e.target.value === 'true' })
                }
                className="w-full bg-gray-800 border border-gray-700 px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-acid"
              >
                <option value="true">Enabled</option>
                <option value="false">Disabled</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-xs text-gray-500 mb-1 uppercase">
                Interval (Hours)
              </label>
              <input
                type="number"
                min="0.1"
                step="0.1"
                max="24"
                value={configForm.interval}
                onChange={(e) =>
                  setConfigForm({ ...configForm, interval: parseFloat(e.target.value) || 6 })
                }
                className="w-full bg-gray-800 border border-gray-700 px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-acid"
              />
            </div>
            <div>
              <label className="block font-mono text-xs text-gray-500 mb-1 uppercase">
                Test Question
              </label>
              <input
                type="text"
                value={configForm.question}
                onChange={(e) => setConfigForm({ ...configForm, question: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-acid"
              />
            </div>
            <div>
              <label className="block font-mono text-xs text-gray-500 mb-1 uppercase">
                Telegram Bot Token
              </label>
              <input
                type="password"
                value={configForm.tg_bot_token || ''}
                onChange={(e) =>
                  setConfigForm({ ...configForm, tg_bot_token: e.target.value || null })
                }
                placeholder="Optional..."
                className="w-full bg-gray-800 border border-gray-700 px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-acid placeholder-gray-600"
              />
            </div>
            <div>
              <label className="block font-mono text-xs text-gray-500 mb-1 uppercase">
                Telegram Chat ID
              </label>
              <input
                type="text"
                value={configForm.tg_chat_id || ''}
                onChange={(e) =>
                  setConfigForm({ ...configForm, tg_chat_id: e.target.value || null })
                }
                placeholder="Optional..."
                className="w-full bg-gray-800 border border-gray-700 px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-acid placeholder-gray-600"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={handleSaveConfig}
                className="px-4 py-2 bg-acid text-black font-bold font-mono text-sm uppercase hover:bg-white transition-colors shadow-hard-acid hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px]"
              >
                Save Config
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

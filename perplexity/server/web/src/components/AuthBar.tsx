import { useState } from 'react'

interface AuthBarProps {
  adminToken: string
  isAuthenticated: boolean
  onLogin: (token: string) => void
  onLogout: () => void
}

export function AuthBar({ adminToken, isAuthenticated, onLogin, onLogout }: AuthBarProps) {
  const [inputToken, setInputToken] = useState('')

  const handleAuth = () => {
    if (inputToken.trim()) {
      onLogin(inputToken.trim())
      setInputToken('')
    }
  }

  return (
    <div className="mb-8 p-4 border-2 border-gray-700 bg-gray-900/50">
      <div className="flex flex-col md:flex-row items-start md:items-center gap-4">
        <div className="flex items-center gap-2">
          <span
            className={`w-3 h-3 rounded-full ${isAuthenticated ? 'bg-green-500 animate-pulse' : 'bg-gray-600'}`}
          ></span>
          <span className="font-mono text-xs uppercase tracking-widest text-gray-500">
            {isAuthenticated ? 'AUTHENTICATED' : 'GUEST_MODE'}
          </span>
        </div>

        {!isAuthenticated ? (
          <div className="flex gap-2 flex-1 w-full md:w-auto">
            <input
              type="password"
              placeholder="ADMIN_TOKEN..."
              value={inputToken}
              onChange={(e) => setInputToken(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAuth()}
              className="flex-1 bg-gray-800 border border-gray-700 px-4 py-2 text-white font-mono text-sm focus:outline-none focus:border-acid transition-colors placeholder-gray-600"
            />
            <button
              onClick={handleAuth}
              className="px-4 py-2 bg-neon-pink text-black font-bold font-mono text-sm uppercase hover:bg-white transition-colors shadow-hard-acid hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px]"
            >
              AUTH
            </button>
          </div>
        ) : (
          <div className="flex gap-2 items-center">
            <span className="font-mono text-xs text-gray-400">
              TOKEN: ****{adminToken.slice(-4)}
            </span>
            <button
              onClick={onLogout}
              className="px-3 py-1 border border-gray-600 font-mono text-xs text-gray-400 hover:bg-gray-800 transition-colors"
            >
              LOGOUT
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

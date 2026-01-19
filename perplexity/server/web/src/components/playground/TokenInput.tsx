import { useState } from 'react'

interface TokenInputProps {
  token: string
  onSave: (token: string) => void
  onConnect: () => void // Kept for interface compatibility but not used in UI
  isConnected: boolean
  isLoading?: boolean
}

export function TokenInput({ token, onSave, isConnected, isLoading }: TokenInputProps) {
  const [showToken, setShowToken] = useState(false)
  const [inputValue, setInputValue] = useState(token)

  const handleSave = () => {
    onSave(inputValue)
  }

  const isSaved = inputValue === token

  return (
    <div className="p-4 border-2 border-gray-700 bg-gray-900/50">
      <div className="flex flex-col md:flex-row items-start md:items-center gap-4">
        <div className="flex items-center gap-2">
          <span
            className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-gray-600'}`}
          ></span>
          <span className="font-mono text-xs uppercase tracking-widest text-gray-500">
            {isConnected ? 'CONNECTED' : 'DISCONNECTED'}
          </span>
        </div>

        <div className="flex gap-2 flex-1 w-full md:w-auto">
          <div className="flex-1 flex items-center bg-gray-800 border border-gray-700 focus-within:border-acid transition-colors">
            <div className="pl-3 text-gray-500">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="w-4 h-4"
              >
                <path
                  fillRule="evenodd"
                  d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <input
              type={showToken ? 'text' : 'password'}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !isSaved && handleSave()}
              placeholder="API_TOKEN..."
              className="flex-1 bg-transparent text-white font-mono text-sm px-3 py-2 focus:outline-none placeholder-gray-600"
            />
            <button
              type="button"
              onClick={() => setShowToken(!showToken)}
              className="pr-3 text-gray-500 hover:text-gray-300 transition-colors"
            >
              {showToken ? (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="w-4 h-4"
                >
                  <path d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" />
                  <path
                    fillRule="evenodd"
                    d="M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
                    clipRule="evenodd"
                  />
                </svg>
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="w-4 h-4"
                >
                  <path
                    fillRule="evenodd"
                    d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.748 1.748A4 4 0 007.752 6.69zm3.5 3.5l-2.603 2.603a2.5 2.5 0 01-2.603-2.603l2.603-2.603zM5.535 10a4.004 4.004 0 01.9-2.108L4.543 6.002A8.006 8.006 0 002.5 10c1.11 2.768 3.82 4.75 6.999 4.75a8.003 8.003 0 004.81-1.643l-1.712-1.712A4.003 4.003 0 015.535 10z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
            </button>
          </div>
          <button
            onClick={handleSave}
            disabled={isSaved}
            className={`px-4 py-2 font-bold font-mono text-sm uppercase transition-colors ${
              isSaved
                ? isConnected
                  ? 'bg-acid text-black cursor-default'
                  : 'bg-gray-700 text-gray-500 cursor-default'
                : 'bg-neon-pink text-black hover:bg-white shadow-hard-acid hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px]'
            }`}
          >
            {isLoading ? '...' : isSaved ? (isConnected ? 'READY' : 'SAVED') : 'SAVE'}
          </button>
        </div>
      </div>
    </div>
  )
}

import { useState, useRef } from 'react'
import { Modal } from './ui/Modal'
import { TokenConfig } from 'lib/api'

interface AddTokenModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (id: string, csrf: string, session: string) => void
  onImportConfig?: (tokens: TokenConfig[]) => void
}

export function AddTokenModal({ isOpen, onClose, onSubmit, onImportConfig }: AddTokenModalProps) {
  const [form, setForm] = useState({ id: '', csrf: '', session: '' })
  const [mode, setMode] = useState<'manual' | 'upload'>('manual')
  const [uploadedTokens, setUploadedTokens] = useState<TokenConfig[] | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = () => {
    if (mode === 'upload' && uploadedTokens && onImportConfig) {
      onImportConfig(uploadedTokens)
      resetForm()
    } else if (mode === 'manual' && form.id && form.csrf && form.session) {
      onSubmit(form.id, form.csrf, form.session)
      resetForm()
    }
  }

  const resetForm = () => {
    setForm({ id: '', csrf: '', session: '' })
    setMode('manual')
    setUploadedTokens(null)
    setUploadError(null)
  }

  const handleClose = () => {
    resetForm()
    onClose()
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadError(null)
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string
        const parsed = JSON.parse(content)

        // Support both array format and object with tokens array
        let tokens: TokenConfig[]
        if (Array.isArray(parsed)) {
          tokens = parsed
        } else if (parsed.tokens && Array.isArray(parsed.tokens)) {
          tokens = parsed.tokens
        } else {
          throw new Error('Invalid format: expected array of tokens')
        }

        // Validate token structure
        for (const token of tokens) {
          if (!token.id || !token.csrf_token || !token.session_token) {
            throw new Error('Invalid token entry: missing required fields (id, csrf_token, session_token)')
          }
        }

        setUploadedTokens(tokens)
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : 'Failed to parse config file')
        setUploadedTokens(null)
      }
    }
    reader.onerror = () => {
      setUploadError('Failed to read file')
      setUploadedTokens(null)
    }
    reader.readAsText(file)
  }

  const isSubmitDisabled = mode === 'upload'
    ? !uploadedTokens || !onImportConfig
    : !form.id || !form.csrf || !form.session

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      onConfirm={handleSubmit}
      title="Inject Token"
      confirmText={mode === 'upload' ? 'IMPORT CONFIG' : 'CONFIRM UPLOAD'}
      confirmColor="bg-acid"
      borderColor="border-acid"
      confirmDisabled={isSubmitDisabled}
    >
      <div className="space-y-6">
        {/* Mode Toggle */}
        <div className="flex gap-2 border-b border-gray-700 pb-4">
          <button
            onClick={() => setMode('manual')}
            className={`px-4 py-2 font-mono text-xs uppercase transition-colors ${
              mode === 'manual'
                ? 'bg-acid text-black'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            Manual Input
          </button>
          <button
            onClick={() => setMode('upload')}
            className={`px-4 py-2 font-mono text-xs uppercase transition-colors ${
              mode === 'upload'
                ? 'bg-acid text-black'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            Upload Config
          </button>
        </div>

        {mode === 'manual' ? (
          <>
            <div>
              <label className="block font-mono text-xs text-acid mb-2 uppercase tracking-widest">
                Identifier
              </label>
              <input
                type="text"
                placeholder="USER_ID_01"
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                className="w-full bg-gray-900 border-b-2 border-gray-700 p-3 text-white font-mono focus:outline-none focus:border-acid focus:bg-gray-800 transition-colors placeholder-gray-700"
              />
            </div>
            <div>
              <label className="block font-mono text-xs text-acid mb-2 uppercase tracking-widest">
                CSRF Token
              </label>
              <textarea
                rows={2}
                placeholder="ENCRYPTED_STRING..."
                value={form.csrf}
                onChange={(e) => setForm({ ...form, csrf: e.target.value })}
                className="w-full bg-gray-900 border-b-2 border-gray-700 p-3 text-white font-mono focus:outline-none focus:border-acid focus:bg-gray-800 transition-colors placeholder-gray-700 text-xs"
              ></textarea>
            </div>
            <div>
              <label className="block font-mono text-xs text-acid mb-2 uppercase tracking-widest">
                Session Token
              </label>
              <textarea
                rows={3}
                placeholder="SESSION_KEY..."
                value={form.session}
                onChange={(e) => setForm({ ...form, session: e.target.value })}
                className="w-full bg-gray-900 border-b-2 border-gray-700 p-3 text-white font-mono focus:outline-none focus:border-acid focus:bg-gray-800 transition-colors placeholder-gray-700 text-xs"
              ></textarea>
            </div>
          </>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block font-mono text-xs text-acid mb-2 uppercase tracking-widest">
                Upload Config File (JSON)
              </label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json"
                onChange={handleFileUpload}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full bg-gray-900 border-2 border-dashed border-gray-700 p-6 text-gray-400 font-mono text-sm hover:border-acid hover:text-acid transition-colors"
              >
                {uploadedTokens ? (
                  <span className="text-acid">
                    Config loaded: {uploadedTokens.length} token(s)
                  </span>
                ) : (
                  'Click to select tokens.json'
                )}
              </button>
            </div>

            {uploadError && (
              <div className="bg-red-900/30 border border-red-500 p-3 text-red-400 font-mono text-xs">
                ERROR: {uploadError}
              </div>
            )}

            {uploadedTokens && (
              <div className="bg-gray-900 border border-gray-700 p-4 font-mono text-xs space-y-2">
                <div className="text-gray-400">
                  <span className="text-acid">Tokens:</span> {uploadedTokens.length}
                </div>
                <div className="text-gray-500 mt-2 pt-2 border-t border-gray-700">
                  IDs: {uploadedTokens.map(t => t.id).join(', ')}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}

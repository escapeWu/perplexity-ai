import { useState } from 'react'
import { Modal } from './ui/Modal'

interface AddTokenModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (id: string, csrf: string, session: string) => void
}

export function AddTokenModal({ isOpen, onClose, onSubmit }: AddTokenModalProps) {
  const [form, setForm] = useState({ id: '', csrf: '', session: '' })

  const handleSubmit = () => {
    if (form.id && form.csrf && form.session) {
      onSubmit(form.id, form.csrf, form.session)
      setForm({ id: '', csrf: '', session: '' })
    }
  }

  const handleClose = () => {
    setForm({ id: '', csrf: '', session: '' })
    onClose()
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      onConfirm={handleSubmit}
      title="Inject Token"
      confirmText="CONFIRM UPLOAD"
      confirmColor="bg-acid"
      borderColor="border-acid"
    >
      <div className="space-y-6">
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
      </div>
    </Modal>
  )
}

import { ReactNode } from 'react'

interface ModalProps {
  isOpen: boolean
  title: string
  children: ReactNode
  onClose: () => void
  onConfirm: () => void
  confirmText?: string
  confirmColor?: string
  borderColor?: string
  confirmDisabled?: boolean
}

export function Modal({
  isOpen,
  title,
  children,
  onClose,
  onConfirm,
  confirmText = 'Confirm',
  confirmColor = 'bg-acid',
  borderColor = 'border-acid',
  confirmDisabled = false,
}: ModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/90 z-50 flex justify-center items-center backdrop-blur-sm">
      <div
        className={`bg-black border-2 ${borderColor} w-full max-w-lg mx-4 p-8 shadow-[10px_10px_0px_0px_currentColor] relative`}
      >
        <div
          className={`absolute -top-3 -left-3 ${confirmColor} text-black px-2 py-1 font-mono text-xs font-bold transform -rotate-3`}
        >
          SYSTEM_MSG
        </div>
        <h3 className="text-3xl font-black uppercase mb-8 text-white">{title}</h3>
        <div className="text-gray-200">{children}</div>
        <div className="flex justify-end gap-4 mt-10">
          <button
            onClick={onClose}
            className="px-6 py-3 font-mono text-sm border border-gray-600 hover:bg-gray-800 transition-colors text-gray-400"
          >
            CANCEL
          </button>
          <button
            onClick={onConfirm}
            disabled={confirmDisabled}
            className={`px-6 py-3 ${confirmColor} text-black font-bold font-mono text-sm transition-colors shadow-hard hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] ${
              confirmDisabled
                ? 'opacity-50 cursor-not-allowed'
                : 'hover:bg-white'
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}

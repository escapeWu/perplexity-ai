import { Modal } from './ui/Modal'

interface ConfirmModalProps {
  isOpen: boolean
  message: string
  onClose: () => void
  onConfirm: () => void
}

export function ConfirmModal({ isOpen, message, onClose, onConfirm }: ConfirmModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      onConfirm={onConfirm}
      title="Warning"
      confirmText="EXECUTE"
      confirmColor="bg-danger"
      borderColor="border-danger"
    >
      <p className="font-mono text-gray-300 mb-8 border-l-2 border-gray-700 pl-4">{message}</p>
    </Modal>
  )
}

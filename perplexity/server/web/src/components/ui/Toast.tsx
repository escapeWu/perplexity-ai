import { useEffect } from 'react'

interface ToastProps {
  message: string
  type: 'success' | 'error'
  onClose: () => void
}

export function Toast({ message, type, onClose }: ToastProps) {
  useEffect(() => {
    const timer = setTimeout(onClose, 3000)
    return () => clearTimeout(timer)
  }, [onClose])

  const bgColor = type === 'success' ? 'bg-acid text-black' : 'bg-danger text-white'

  return (
    <div
      className={`fixed bottom-5 right-5 ${bgColor} px-6 py-4 font-mono text-sm font-bold shadow-hard z-50 border-2 border-black uppercase animate-bounce`}
    >
      {`>> ${message}`}
    </div>
  )
}

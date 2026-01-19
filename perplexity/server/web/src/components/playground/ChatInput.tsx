import { useState, useCallback, KeyboardEvent } from 'react'
import { OAIModel } from 'lib/api'
import { CustomSelect } from './CustomSelect'

interface ChatInputProps {
  onSend: (message: string) => void
  onClear?: () => void
  disabled?: boolean
  placeholder?: string
  models?: OAIModel[]
  selectedModel?: string
  onSelectModel?: (model: string) => void
}

export function ChatInput({
  onSend,
  onClear,
  disabled,
  placeholder = 'Type your message...',
  models = [],
  selectedModel,
  onSelectModel,
}: ChatInputProps) {
  const [value, setValue] = useState('')

  const handleSend = useCallback(() => {
    if (value.trim() && !disabled) {
      onSend(value)
      setValue('')
    }
  }, [value, disabled, onSend])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  return (
    <div className="flex gap-3 p-4 border-t-2 border-gray-700 bg-concrete items-end">
      {onClear && (
        <button
          onClick={onClear}
          disabled={disabled}
          className="bg-gray-800 text-gray-400 font-mono font-bold uppercase px-3 py-2 border-2 border-gray-600 hover:text-danger hover:border-danger transition-all disabled:opacity-50 disabled:cursor-not-allowed h-[42px] mb-[1px]"
          title="Clear Chat"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
            className="w-5 h-5"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
            />
          </svg>
        </button>
      )}
      <div className="flex-1 flex flex-col gap-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          rows={1}
          className="w-full bg-void border-2 border-gray-600 text-gray-200 font-sans px-4 py-2 resize-none focus:border-acid focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed min-h-[42px]"
        />
      </div>
      {models.length > 0 && onSelectModel && selectedModel && (
        <CustomSelect
          models={models}
          selectedModel={selectedModel}
          onSelect={onSelectModel}
          disabled={disabled}
        />
      )}
      <button
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        className="bg-acid text-void font-mono font-bold uppercase px-6 py-2 border-2 border-acid shadow-hard hover:shadow-hard-hover hover:translate-x-[2px] hover:translate-y-[2px] transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-hard disabled:hover:translate-x-0 disabled:hover:translate-y-0 h-[42px] mb-[1px]"
      >
        Send
      </button>
    </div>
  )
}


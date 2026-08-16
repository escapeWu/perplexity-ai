import { useState, useCallback, useRef, useEffect, KeyboardEvent } from 'react'
import { OAIModel } from 'lib/api'
import { CustomSelect } from './CustomSelect'

function FileChip({ file, onRemove }: { file: File; onRemove?: () => void }) {
  const isImage = file.type.startsWith('image/')
  const [objectUrl, setObjectUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!isImage) return
    const url = URL.createObjectURL(file)
    setObjectUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file, isImage])

  if (isImage && objectUrl) {
    return (
      <div className="group/chip relative inline-block">
        <img
          src={objectUrl}
          alt={file.name}
          title={file.name}
          className="size-16 border border-gray-600 object-cover"
        />
        {onRemove && (
          <button
            onClick={onRemove}
            className="absolute right-0 top-0 flex size-5 items-center justify-center bg-black/70 text-sm leading-none text-gray-400 opacity-0 transition-opacity hover:text-danger group-hover/chip:opacity-100"
            title="Remove"
          >
            ×
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 border border-gray-600 bg-gray-800 px-2 py-1 font-mono text-xs text-gray-300">
      <span className="max-w-[160px] truncate" title={file.name}>
        {file.name}
      </span>
      <span className="text-gray-500">({formatBytes(file.size)})</span>
      {onRemove && (
        <button
          onClick={onRemove}
          className="ml-1 leading-none text-gray-500 transition-colors hover:text-danger"
          title="Remove file"
        >
          ×
        </button>
      )}
    </div>
  )
}

const ACCEPTED_EXTENSIONS = [
  '.pdf',
  '.doc',
  '.docx',
  '.pptx',
  '.xlsx',
  '.csv',
  '.txt',
  '.text',
  '.md',
  '.markdown',
  '.rmd',
  '.latex',
  '.tex',
  '.py',
  '.js',
  '.ts',
  '.jsx',
  '.tsx',
  '.go',
  '.rs',
  '.java',
  '.cpp',
  '.c',
  '.cxx',
  '.h',
  '.hpp',
  '.cs',
  '.rb',
  '.php',
  '.pl',
  '.pm',
  '.swift',
  '.kt',
  '.kts',
  '.scala',
  '.dart',
  '.lua',
  '.r',
  '.R',
  '.m',
  '.sh',
  '.bash',
  '.zsh',
  '.fish',
  '.ksh',
  '.bat',
  '.sql',
  '.html',
  '.htm',
  '.css',
  '.less',
  '.xml',
  '.json',
  '.yaml',
  '.yml',
  '.toml',
  '.ini',
  '.conf',
  '.config',
  '.in',
  '.log',
  '.coffee',
  '.diff',
  '.ipynb',
  '.jpg',
  '.jpeg',
  '.jpe',
  '.jp2',
  '.png',
  '.gif',
  '.bmp',
  '.tiff',
  '.tif',
  '.svg',
  '.webp',
  '.ico',
  '.avif',
  '.heic',
  '.heif',
  '.mp3',
  '.wav',
  '.aiff',
  '.ogg',
  '.flac',
  '.mp4',
  '.mpeg',
  '.mpg',
  '.mov',
  '.avi',
  '.flv',
  '.webm',
  '.wmv',
  '.3gp'
].join(',')

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface ChatInputProps {
  onSend: (message: string) => void
  onClear?: () => void
  disabled?: boolean
  placeholder?: string
  models?: OAIModel[]
  selectedModel?: string
  thinking?: boolean
  onSelectModel?: (model: string) => void
  onThinkingChange?: (enabled: boolean) => void
  streamEnabled?: boolean
  onStreamEnabledChange?: (enabled: boolean) => void
  isGenerating?: boolean
  onStop?: () => void
  pendingFiles?: File[]
  onAddFiles?: (files: File[]) => void
  onRemoveFile?: (index: number) => void
}

export function ChatInput({
  onSend,
  onClear,
  disabled,
  placeholder = 'Type your message...',
  models = [],
  selectedModel,
  thinking = false,
  onSelectModel,
  onThinkingChange,
  streamEnabled = true,
  onStreamEnabledChange,
  isGenerating = false,
  onStop,
  pendingFiles = [],
  onAddFiles,
  onRemoveFile
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleSend = useCallback(() => {
    if ((value.trim() || pendingFiles.length > 0) && !disabled) {
      onSend(value)
      setValue('')
    }
  }, [value, disabled, onSend, pendingFiles.length])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      if (!onAddFiles) return
      const files = Array.from(e.clipboardData.items)
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter((f): f is File => f !== null)
      if (files.length > 0) {
        e.preventDefault()
        onAddFiles(files)
      }
    },
    [onAddFiles]
  )

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || [])
      if (files.length > 0 && onAddFiles) {
        onAddFiles(files)
      }
      // Reset input so the same file can be re-selected
      e.target.value = ''
    },
    [onAddFiles]
  )

  return (
    <div className="flex flex-col gap-2 border-t-2 border-gray-700 bg-concrete p-3 md:p-4">
      {/* File chips */}
      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          {pendingFiles.map((file, idx) => (
            <FileChip
              key={idx}
              file={file}
              onRemove={onRemoveFile ? () => onRemoveFile(idx) : undefined}
            />
          ))}
        </div>
      )}

      {/* Input row */}
      <div className="flex flex-wrap items-end gap-2 md:flex-nowrap md:gap-3">
        {onClear && (
          <button
            onClick={onClear}
            disabled={disabled}
            className="mb-px h-[42px] border-2 border-gray-600 bg-gray-800 px-3 py-2 font-mono font-bold uppercase text-gray-400 transition-all hover:border-danger hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
            title="Clear Chat"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="size-5"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
              />
            </svg>
          </button>
        )}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS}
          className="hidden"
          onChange={handleFileChange}
        />

        {/* Attach button */}
        {onAddFiles && (
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="mb-px h-[42px] border-2 border-gray-600 bg-gray-800 px-3 py-2 font-mono font-bold uppercase text-gray-400 transition-all hover:border-acid hover:text-acid disabled:cursor-not-allowed disabled:opacity-50"
            title="Attach files"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="size-5"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13"
              />
            </svg>
          </button>
        )}

        <div className="order-first flex w-full flex-col gap-2 md:order-none md:w-auto md:flex-1">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={disabled}
            placeholder={placeholder}
            rows={1}
            className="min-h-[42px] w-full resize-none border-2 border-gray-600 bg-void px-4 py-2 font-sans text-gray-200 focus:border-acid focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>

        {models.length > 0 && onSelectModel && selectedModel && (
          <CustomSelect
            models={models}
            selectedModel={selectedModel}
            thinking={thinking}
            onSelect={onSelectModel}
            onThinkingChange={onThinkingChange}
            disabled={disabled}
          />
        )}

        {onStreamEnabledChange && (
          <button
            type="button"
            onClick={() => onStreamEnabledChange(!streamEnabled)}
            disabled={disabled}
            className={`mb-px h-[42px] border-2 p-2 font-mono text-xs font-bold uppercase transition-all disabled:cursor-not-allowed disabled:opacity-50 sm:px-3 sm:text-sm ${
              streamEnabled
                ? 'border-neon-blue bg-neon-blue/20 text-neon-blue'
                : 'border-gray-600 bg-gray-800 text-gray-400'
            }`}
            title={
              streamEnabled
                ? 'Streaming enabled — click to wait for complete responses'
                : 'Complete response mode — click to enable streaming'
            }
          >
            {streamEnabled ? 'Stream' : 'Complete'}
          </button>
        )}

        {isGenerating && onStop ? (
          <button
            type="button"
            onClick={onStop}
            className="mb-px h-[42px] border-2 border-danger bg-danger px-3 py-2 font-mono text-sm font-bold uppercase text-white shadow-hard transition-all hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-hard-hover sm:px-6"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={disabled || (!value.trim() && pendingFiles.length === 0)}
            className="mb-px h-[42px] border-2 border-acid bg-acid px-3 py-2 font-mono text-sm font-bold uppercase text-void shadow-hard transition-all hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-hard-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-x-0 disabled:hover:translate-y-0 disabled:hover:shadow-hard sm:px-6"
          >
            Send
          </button>
        )}
      </div>
    </div>
  )
}

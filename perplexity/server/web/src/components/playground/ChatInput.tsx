import { useState, useCallback, useRef, useEffect, KeyboardEvent } from 'react'
import { OAIModel } from 'lib/api'
import { CustomSelect } from './CustomSelect'

function FileChip({
  file,
  onRemove,
}: {
  file: File
  onRemove?: () => void
}) {
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
      <div className="relative group/chip inline-block">
        <img
          src={objectUrl}
          alt={file.name}
          title={file.name}
          className="h-16 w-16 object-cover border border-gray-600"
        />
        {onRemove && (
          <button
            onClick={onRemove}
            className="absolute top-0 right-0 bg-black/70 text-gray-400 hover:text-danger leading-none w-5 h-5 flex items-center justify-center opacity-0 group-hover/chip:opacity-100 transition-opacity text-sm"
            title="Remove"
          >
            ×
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 bg-gray-800 border border-gray-600 text-gray-300 font-mono text-xs px-2 py-1">
      <span className="max-w-[160px] truncate" title={file.name}>
        {file.name}
      </span>
      <span className="text-gray-500">({formatBytes(file.size)})</span>
      {onRemove && (
        <button
          onClick={onRemove}
          className="ml-1 text-gray-500 hover:text-danger transition-colors leading-none"
          title="Remove file"
        >
          ×
        </button>
      )}
    </div>
  )
}

const ACCEPTED_EXTENSIONS = [
  '.pdf','.doc','.docx','.pptx','.xlsx','.csv','.txt','.text','.md','.markdown',
  '.rmd','.latex','.tex','.py','.js','.ts','.jsx','.tsx','.go','.rs','.java',
  '.cpp','.c','.cxx','.h','.hpp','.cs','.rb','.php','.pl','.pm','.swift',
  '.kt','.kts','.scala','.dart','.lua','.r','.R','.m','.sh','.bash','.zsh',
  '.fish','.ksh','.bat','.sql','.html','.htm','.css','.less','.xml','.json',
  '.yaml','.yml','.toml','.ini','.conf','.config','.in','.log','.coffee',
  '.diff','.ipynb','.jpg','.jpeg','.jpe','.jp2','.png','.gif','.bmp','.tiff',
  '.tif','.svg','.webp','.ico','.avif','.heic','.heif','.mp3','.wav','.aiff',
  '.ogg','.flac','.mp4','.mpeg','.mpg','.mov','.avi','.flv','.webm','.wmv','.3gp',
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
  onSelectModel?: (model: string) => void
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
  onSelectModel,
  pendingFiles = [],
  onAddFiles,
  onRemoveFile,
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
    <div className="flex flex-col gap-2 p-4 border-t-2 border-gray-700 bg-concrete">
      {/* File chips */}
      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 items-end">
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
      <div className="flex gap-3 items-end">
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
            className="bg-gray-800 text-gray-400 font-mono font-bold uppercase px-3 py-2 border-2 border-gray-600 hover:text-acid hover:border-acid transition-all disabled:opacity-50 disabled:cursor-not-allowed h-[42px] mb-[1px]"
            title="Attach files"
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
                d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13"
              />
            </svg>
          </button>
        )}

        <div className="flex-1 flex flex-col gap-2">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
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
          disabled={disabled || (!value.trim() && pendingFiles.length === 0)}
          className="bg-acid text-void font-mono font-bold uppercase px-6 py-2 border-2 border-acid shadow-hard hover:shadow-hard-hover hover:translate-x-[2px] hover:translate-y-[2px] transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-hard disabled:hover:translate-x-0 disabled:hover:translate-y-0 h-[42px] mb-[1px]"
        >
          Send
        </button>
      </div>
    </div>
  )
}

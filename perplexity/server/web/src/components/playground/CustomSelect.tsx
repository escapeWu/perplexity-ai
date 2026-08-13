import { useState, useRef, useEffect } from 'react'
import { OAIModel } from 'lib/api'

interface CustomSelectProps {
  models: OAIModel[]
  selectedModel: string
  onSelect: (model: string) => void
  disabled?: boolean
}

export function CustomSelect({
  models,
  selectedModel,
  onSelect,
  disabled
}: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const selected = models.find((model) => model.id === selectedModel)

  // Close when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const groups = models.reduce(
    (acc, model) => {
      if (model.mode === 'reasoning') {
        acc.reasoning.push(model)
        return acc
      }
      if (model.mode === 'deep research') {
        acc.deepsearch.push(model)
        return acc
      }
      if (model.mode === 'auto' || model.mode === 'pro') {
        acc.search.push(model)
        return acc
      }
      const id = model.id.toLowerCase()
      if (id.includes('reasoning') || id.includes('think')) {
        acc.reasoning.push(model)
      } else if (id.includes('deep') || id.includes('research')) {
        acc.deepsearch.push(model)
      } else if (id.includes('search') || id.includes('sonar')) {
        acc.search.push(model)
      } else {
        acc.other.push(model)
      }
      return acc
    },
    { search: [], reasoning: [], deepsearch: [], other: [] } as Record<
      string,
      OAIModel[]
    >
  )

  const groupLabels: Record<string, string> = {
    search: 'Search',
    reasoning: 'Reasoning',
    deepsearch: 'Deep Research',
    other: 'Other'
  }

  const groupColors: Record<string, string> = {
    search: 'text-acid',
    reasoning: 'text-neon-pink',
    deepsearch: 'text-neon-blue',
    other: 'text-gray-400'
  }

  return (
    <div className="relative mb-px" ref={containerRef}>
      <button
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className="flex h-[42px] w-[140px] items-center justify-between border-2 border-gray-600 bg-concrete px-3 py-2 font-mono text-xs text-gray-300 transition-colors hover:border-acid hover:text-acid focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 sm:w-[180px]"
      >
        <span className="truncate">{selected?.label || selectedModel}</span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
          className={`ml-2 size-4 transition-transform duration-200 ${
            isOpen ? 'rotate-180' : 'rotate-0'
          }`}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19.5 8.25l-7.5 7.5-7.5-7.5"
          />
        </svg>
      </button>

      {isOpen && (
        <div className="animate-in fade-in zoom-in-95 absolute -left-14 bottom-full z-50 mb-2 max-h-[360px] w-[min(300px,calc(100vw-2rem))] origin-bottom-left overflow-y-auto border-2 border-gray-600 bg-black shadow-hard duration-100 sm:left-0">
          {Object.entries(groups).map(([key, groupModels]) => {
            if (groupModels.length === 0) return null
            return (
              <div key={key}>
                <div
                  className={`border-b border-gray-800 bg-gray-900 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider ${groupColors[key]}`}
                >
                  {groupLabels[key]}
                </div>
                {groupModels.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => {
                      onSelect(m.id)
                      setIsOpen(false)
                    }}
                    title={m.description}
                    className={`group w-full px-3 py-2 text-left font-mono text-xs transition-colors hover:bg-white hover:text-black ${
                      selectedModel === m.id
                        ? 'bg-gray-800 text-white'
                        : 'text-gray-400'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-gray-100 group-hover:text-black">
                        {m.label || m.id}
                      </span>
                      {m.subscription_tier === 'max' && (
                        <span className="shrink-0 border border-neon-pink px-1 text-[9px] uppercase text-neon-pink group-hover:border-black group-hover:text-black">
                          Max
                        </span>
                      )}
                    </span>
                    {(m.label || m.description) && (
                      <span className="mt-0.5 block truncate text-[10px] text-gray-500 group-hover:text-gray-700">
                        {m.description || m.id}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

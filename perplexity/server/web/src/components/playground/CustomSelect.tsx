import { useState, useRef, useEffect } from 'react'
import { OAIModel } from 'lib/api'

interface CustomSelectProps {
  models: OAIModel[]
  selectedModel: string
  onSelect: (model: string) => void
  disabled?: boolean
}

export function CustomSelect({ models, selectedModel, onSelect, disabled }: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const groups = models.reduce(
    (acc, model) => {
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
    { search: [], reasoning: [], deepsearch: [], other: [] } as Record<string, OAIModel[]>
  )

  const groupLabels: Record<string, string> = {
    search: 'Search',
    reasoning: 'Reasoning',
    deepsearch: 'Deep Research',
    other: 'Other',
  }

  const groupColors: Record<string, string> = {
    search: 'text-acid',
    reasoning: 'text-neon-pink',
    deepsearch: 'text-neon-blue',
    other: 'text-gray-400',
  }

  return (
    <div className="relative mb-[1px]" ref={containerRef}>
      <button
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className="flex items-center justify-between bg-concrete text-gray-300 font-mono text-xs border-2 border-gray-600 hover:border-acid hover:text-acid px-3 py-2 h-[42px] w-[180px] focus:outline-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className="truncate">{selectedModel}</span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
          className={`w-4 h-4 ml-2 transition-transform duration-200 ${
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
        <div className="absolute bottom-full left-0 mb-2 w-[240px] max-h-[300px] overflow-y-auto bg-black border-2 border-gray-600 shadow-hard z-50 animate-in fade-in zoom-in-95 duration-100 origin-bottom-left">
          {Object.entries(groups).map(([key, groupModels]) => {
            if (groupModels.length === 0) return null
            return (
              <div key={key}>
                <div
                  className={`px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider bg-gray-900 border-b border-gray-800 ${groupColors[key]}`}
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
                    className={`w-full text-left px-3 py-2 text-xs font-mono hover:bg-white hover:text-black transition-colors ${
                      selectedModel === m.id ? 'text-white bg-gray-800' : 'text-gray-400'
                    }`}
                  >
                    {m.id}
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

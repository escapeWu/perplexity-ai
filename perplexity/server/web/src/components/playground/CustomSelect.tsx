import { useEffect, useMemo, useRef, useState } from 'react'
import { OAIModel } from 'lib/api'
import {
  modelBaseId,
  modelIsThinkingOnly,
  modelSupportsThinking
} from 'lib/modelCatalog'

interface CustomSelectProps {
  models: OAIModel[]
  selectedModel: string
  thinking: boolean
  onSelect: (model: string) => void
  onThinkingChange?: (enabled: boolean) => void
  disabled?: boolean
}

export function visibleModelOptions(models: OAIModel[]): OAIModel[] {
  const baseModels = models.filter(
    (model) => modelBaseId(model, models) === model.id
  )
  return [
    ...baseModels.filter((model) => model.mode !== 'deep research'),
    ...baseModels.filter((model) => model.mode === 'deep research')
  ]
}

function optionStatus(
  model: OAIModel,
  models: OAIModel[],
  thinking: boolean
): string {
  if (modelIsThinkingOnly(model, models)) return 'Thinking'
  if (modelSupportsThinking(model, models)) {
    return thinking ? 'Thinking' : 'Thinking available'
  }
  if (model.mode === 'deep research') return 'Deep research'
  return model.description || model.id
}

export function CustomSelect({
  models,
  selectedModel,
  thinking,
  onSelect,
  onThinkingChange,
  disabled
}: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const options = useMemo(() => visibleModelOptions(models), [models])
  const selected =
    options.find((model) => model.id === selectedModel) || options[0]
  const selectedThinkingOnly = Boolean(
    selected && modelIsThinkingOnly(selected, models)
  )
  const selectedSupportsThinking = Boolean(
    selected && modelSupportsThinking(selected, models)
  )
  const thinkingEnabled = Boolean(
    selected && (selectedThinkingOnly || (thinking && selectedSupportsThinking))
  )

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

  if (!selected) return null

  return (
    <div className="relative mb-px" ref={containerRef}>
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={`Select model: ${selected.label || selected.id}${
          thinkingEnabled ? ' — Thinking' : ''
        }`}
        className="flex h-[42px] w-[160px] items-center justify-between border-2 border-gray-600 bg-concrete px-3 py-2 font-mono text-xs text-gray-300 transition-colors hover:border-acid hover:text-acid focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 sm:w-[210px]"
      >
        <span className="min-w-0 truncate">
          {selected.label || selected.id}
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-1.5">
          {thinkingEnabled && (
            <span className="hidden text-[9px] font-bold uppercase text-neon-blue sm:inline">
              Thinking
            </span>
          )}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
            className={`size-4 transition-transform duration-200 ${
              isOpen ? 'rotate-180' : 'rotate-0'
            }`}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 8.25l-7.5 7.5-7.5-7.5"
            />
          </svg>
        </span>
      </button>

      {isOpen && (
        <div
          role="dialog"
          aria-label="Model settings"
          className="absolute -left-14 bottom-full z-50 mb-2 max-h-[70vh] w-[min(580px,calc(100vw-2rem))] origin-bottom-left overflow-y-auto border-2 border-gray-600 bg-black shadow-hard sm:left-0 md:left-auto md:right-0 md:origin-bottom-right md:overflow-visible"
        >
          <div className="grid md:grid-cols-[minmax(0,1fr)_220px]">
            <div className="max-h-[420px] overflow-y-auto border-gray-700 md:border-r">
              {options.map((model) => {
                const isSelected = selected.id === model.id
                const thinkingOnly = modelIsThinkingOnly(model, models)
                const supportsThinking = modelSupportsThinking(model, models)
                const status = optionStatus(
                  model,
                  models,
                  isSelected ? thinkingEnabled : false
                )
                return (
                  <button
                    type="button"
                    key={model.id}
                    onClick={() => onSelect(model.id)}
                    aria-label={`Choose ${model.label || model.id}`}
                    className={`group flex w-full items-center gap-3 border-b border-gray-800 px-3 py-2.5 text-left font-mono transition-colors last:border-b-0 hover:bg-white hover:text-black ${
                      isSelected ? 'bg-gray-800 text-white' : 'text-gray-400'
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`grid size-7 shrink-0 place-items-center border text-xs font-bold ${
                        isSelected
                          ? 'border-acid text-acid group-hover:border-black group-hover:text-black'
                          : 'border-gray-700 text-gray-500 group-hover:border-black group-hover:text-black'
                      }`}
                    >
                      {model.mode === 'deep research'
                        ? 'R'
                        : thinkingOnly
                          ? '✦'
                          : '◇'}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm text-gray-100 group-hover:text-black">
                          {model.label || model.id}
                        </span>
                        {model.subscription_tier === 'max' && (
                          <span className="shrink-0 border border-neon-pink px-1 text-[9px] uppercase text-neon-pink group-hover:border-black group-hover:text-black">
                            Max
                          </span>
                        )}
                      </span>
                      <span
                        className={`mt-0.5 block truncate text-[10px] ${
                          thinkingOnly || supportsThinking
                            ? 'text-neon-blue/80 group-hover:text-gray-700'
                            : 'text-gray-500 group-hover:text-gray-700'
                        }`}
                      >
                        {status}
                      </span>
                    </span>
                    {isSelected && (
                      <span
                        aria-hidden="true"
                        className="shrink-0 text-base text-acid group-hover:text-black"
                      >
                        ✓
                      </span>
                    )}
                  </button>
                )
              })}
            </div>

            <aside className="bg-concrete p-4 font-mono md:min-h-[180px]">
              <div className="border-b border-gray-700 pb-3">
                <h3 className="text-sm font-bold text-white">
                  {selected.label || selected.id}
                </h3>
                <p className="mt-1 text-[10px] leading-relaxed text-gray-500">
                  {selected.description || selected.id}
                </p>
              </div>

              {selectedSupportsThinking && onThinkingChange ? (
                <div className="mt-4 flex items-center justify-between gap-4">
                  <div>
                    <p className="text-xs font-bold text-gray-200">Thinking</p>
                    <p className="mt-1 text-[9px] text-gray-500">
                      Use the reasoning variant
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={thinkingEnabled}
                    aria-label={`Thinking for ${selected.label || selected.id}`}
                    onClick={() => onThinkingChange(!thinkingEnabled)}
                    className={`relative h-6 w-11 shrink-0 rounded-full border-2 transition-colors ${
                      thinkingEnabled
                        ? 'border-neon-blue bg-neon-blue/30'
                        : 'border-gray-600 bg-gray-900'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 size-4 rounded-full transition-all ${
                        thinkingEnabled
                          ? 'left-[21px] bg-neon-blue'
                          : 'left-0.5 bg-gray-500'
                      }`}
                    />
                  </button>
                </div>
              ) : selectedThinkingOnly ? (
                <div className="mt-4 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-bold text-gray-200">Thinking</p>
                    <p className="mt-1 text-[9px] text-gray-500">
                      This model always reasons
                    </p>
                  </div>
                  <span className="border border-neon-blue px-2 py-1 text-[9px] uppercase text-neon-blue">
                    Always on
                  </span>
                </div>
              ) : selectedSupportsThinking ? (
                <p className="mt-4 text-[10px] text-neon-blue">
                  A thinking variant is available through the API.
                </p>
              ) : (
                <p className="mt-4 text-[10px] text-gray-500">
                  {selected.mode === 'deep research'
                    ? 'Runs the full research workflow.'
                    : 'Uses the standard search model.'}
                </p>
              )}
            </aside>
          </div>
        </div>
      )}
    </div>
  )
}

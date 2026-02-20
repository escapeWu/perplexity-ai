import { OAIModel } from 'lib/api'

interface ModelSelectorProps {
  models: OAIModel[]
  selectedModel: string
  onSelect: (model: string) => void
  disabled?: boolean
}

// Group models by mode (based on naming convention)
function groupModels(models: OAIModel[]): Record<string, OAIModel[]> {
  const groups: Record<string, OAIModel[]> = {
    search: [],
    thinking: [],
    deepsearch: [],
    other: [],
  }

  for (const model of models) {
    const id = model.id.toLowerCase()
    if (id.endsWith('-thinking')) {
      groups.thinking.push(model)
    } else if (id.includes('deep') || id.includes('research')) {
      groups.deepsearch.push(model)
    } else if (id.includes('search') || id.includes('sonar')) {
      groups.search.push(model)
    } else {
      groups.other.push(model)
    }
  }

  return groups
}

export function ModelSelector({ models, selectedModel, onSelect, disabled }: ModelSelectorProps) {
  const groups = groupModels(models)

  return (
    <div className="flex items-center gap-3">
      <label className="font-mono text-xs text-gray-400 uppercase">Model:</label>
      <select
        value={selectedModel}
        onChange={(e) => onSelect(e.target.value)}
        disabled={disabled}
        className="bg-concrete border-2 border-gray-600 text-gray-200 font-mono text-sm px-3 py-2 focus:border-acid focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed min-w-[200px]"
      >
        {groups.search.length > 0 && (
          <optgroup label="Search">
            {groups.search.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </optgroup>
        )}
        {groups.thinking.length > 0 && (
          <optgroup label="Thinking">
            {groups.thinking.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </optgroup>
        )}
        {groups.deepsearch.length > 0 && (
          <optgroup label="Deep Research">
            {groups.deepsearch.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </optgroup>
        )}
        {groups.other.length > 0 && (
          <optgroup label="Other">
            {groups.other.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </div>
  )
}

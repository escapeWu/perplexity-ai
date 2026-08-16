import { OAIModel } from './api'

function inferredThinkingBaseId(modelId: string): string | null {
  if (modelId === 'perplexity-thinking') return 'perplexity-search'
  if (modelId.endsWith('-thinking')) {
    return modelId.slice(0, -'-thinking'.length)
  }
  return null
}

export function modelIsThinking(model: OAIModel): boolean {
  return model.thinking ?? model.mode === 'reasoning'
}

export function modelBaseId(model: OAIModel, models: OAIModel[]): string {
  if (model.base_model_id) return model.base_model_id
  if (!modelIsThinking(model)) return model.id

  const candidate = inferredThinkingBaseId(model.id)
  return candidate && models.some((item) => item.id === candidate)
    ? candidate
    : model.id
}

export function modelSupportsThinking(
  model: OAIModel,
  models: OAIModel[]
): boolean {
  if (model.supports_thinking !== undefined) {
    return model.supports_thinking
  }
  if (modelIsThinking(model)) return modelBaseId(model, models) !== model.id

  const candidate =
    model.id === 'perplexity-search'
      ? 'perplexity-thinking'
      : `${model.id}-thinking`
  return models.some((item) => item.id === candidate && modelIsThinking(item))
}

export function modelIsThinkingOnly(
  model: OAIModel,
  models: OAIModel[]
): boolean {
  return (
    model.thinking_only ??
    (modelIsThinking(model) && modelBaseId(model, models) === model.id)
  )
}

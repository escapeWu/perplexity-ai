import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OAIModel } from 'lib/api'
import { CustomSelect } from './CustomSelect'

const models: OAIModel[] = [
  {
    id: 'gpt-5-6-terra',
    object: 'model',
    created: 1700000000,
    owned_by: 'perplexity',
    label: 'GPT-5.6 Terra',
    description: 'Versatile model',
    subscription_tier: 'pro',
    mode: 'pro',
    base_model_id: 'gpt-5-6-terra',
    thinking_model_id: 'gpt-5-6-terra-thinking',
    supports_thinking: true,
    thinking: false,
    thinking_only: false
  },
  {
    id: 'gpt-5-6-terra-thinking',
    object: 'model',
    created: 1700000000,
    owned_by: 'perplexity',
    label: 'GPT-5.6 Terra Thinking',
    description: 'Versatile model',
    subscription_tier: 'pro',
    mode: 'reasoning',
    base_model_id: 'gpt-5-6-terra',
    thinking_model_id: 'gpt-5-6-terra-thinking',
    supports_thinking: true,
    thinking: true,
    thinking_only: false
  },
  {
    id: 'gpt-5-6-sol',
    object: 'model',
    created: 1700000000,
    owned_by: 'perplexity',
    label: 'GPT-5.6 Sol',
    description: 'Most powerful model',
    subscription_tier: 'max',
    mode: 'pro',
    base_model_id: 'gpt-5-6-sol',
    thinking_model_id: null,
    supports_thinking: false,
    thinking: false,
    thinking_only: false
  }
]

const legacyModels: OAIModel[] = models.slice(0, 2).map((model) => ({
  id: model.id,
  object: model.object,
  created: model.created,
  owned_by: model.owned_by,
  label: model.label,
  description: model.description,
  subscription_tier: model.subscription_tier,
  mode: model.mode
}))

describe('CustomSelect upstream-style model picker', () => {
  it('shows one unified entry per model family and preserves the base API id', () => {
    const onSelect = vi.fn()
    render(
      <CustomSelect
        models={models}
        selectedModel="gpt-5-6-terra"
        thinking={false}
        onSelect={onSelect}
        onThinkingChange={vi.fn()}
      />
    )

    fireEvent.click(
      screen.getByRole('button', { name: /Select model: GPT-5.6 Terra/ })
    )

    expect(screen.getByText('Most powerful model')).toBeInTheDocument()
    expect(screen.getByText('Max')).toBeInTheDocument()
    expect(
      screen.getAllByRole('button', { name: 'Choose GPT-5.6 Terra' })
    ).toHaveLength(1)
    expect(
      screen.queryByRole('button', { name: 'Choose GPT-5.6 Terra Thinking' })
    ).not.toBeInTheDocument()
    expect(screen.queryByText('SEARCH')).not.toBeInTheDocument()
    expect(screen.queryByText('REASONING')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Choose GPT-5.6 Sol' }))
    expect(onSelect).toHaveBeenCalledWith('gpt-5-6-sol')
  })

  it('exposes thinking as a toggle for the selected base model', () => {
    const onThinkingChange = vi.fn()
    render(
      <CustomSelect
        models={models}
        selectedModel="gpt-5-6-terra"
        thinking={false}
        onSelect={vi.fn()}
        onThinkingChange={onThinkingChange}
      />
    )

    fireEvent.click(
      screen.getByRole('button', { name: /Select model: GPT-5.6 Terra/ })
    )
    const toggle = screen.getByRole('switch', {
      name: 'Thinking for GPT-5.6 Terra'
    })
    expect(toggle).toHaveAttribute('aria-checked', 'false')

    fireEvent.click(toggle)
    expect(onThinkingChange).toHaveBeenCalledWith(true)
  })

  it('infers paired models from a legacy model response', () => {
    render(
      <CustomSelect
        models={legacyModels}
        selectedModel="gpt-5-6-terra"
        thinking={false}
        onSelect={vi.fn()}
        onThinkingChange={vi.fn()}
      />
    )

    fireEvent.click(
      screen.getByRole('button', { name: /Select model: GPT-5.6 Terra/ })
    )
    expect(
      screen.getAllByRole('button', { name: 'Choose GPT-5.6 Terra' })
    ).toHaveLength(1)
    expect(
      screen.queryByRole('button', { name: 'Choose GPT-5.6 Terra Thinking' })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('switch', { name: 'Thinking for GPT-5.6 Terra' })
    ).toBeInTheDocument()
  })
})

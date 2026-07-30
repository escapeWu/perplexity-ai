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
    mode: 'pro'
  },
  {
    id: 'gpt-5-6-sol',
    object: 'model',
    created: 1700000000,
    owned_by: 'perplexity',
    label: 'GPT-5.6 Sol',
    description: 'Most powerful model',
    subscription_tier: 'max',
    mode: 'pro'
  }
]

describe('CustomSelect catalog metadata', () => {
  it('shows labels, descriptions, and a Max badge while preserving the API id', () => {
    const onSelect = vi.fn()
    render(
      <CustomSelect
        models={models}
        selectedModel="gpt-5-6-terra"
        onSelect={onSelect}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'GPT-5.6 Terra' }))

    expect(screen.getByText('Most powerful model')).toBeInTheDocument()
    expect(screen.getByText('Max')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /GPT-5.6 Sol/ }))
    expect(onSelect).toHaveBeenCalledWith('gpt-5-6-sol')
  })
})

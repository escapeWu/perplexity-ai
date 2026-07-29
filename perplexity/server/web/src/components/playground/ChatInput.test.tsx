import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChatInput } from './ChatInput'

describe('ChatInput streaming controls', () => {
  it('shows streaming as the default mode and allows switching it off', () => {
    const onStreamEnabledChange = vi.fn()

    render(
      <ChatInput
        onSend={vi.fn()}
        streamEnabled
        onStreamEnabledChange={onStreamEnabledChange}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Stream' }))

    expect(onStreamEnabledChange).toHaveBeenCalledWith(false)
  })

  it('shows an active stop button while a request is running', () => {
    const onStop = vi.fn()

    render(<ChatInput onSend={vi.fn()} disabled isGenerating onStop={onStop} />)

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))

    expect(onStop).toHaveBeenCalledOnce()
  })
})

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChatSession } from 'lib/api'
import { SessionSidebar } from './SessionSidebar'

const sessions: ChatSession[] = [
  {
    id: 'sess_00000000000000000000000000000001',
    title: 'Native follow-up',
    bound_client_id: 'account-a',
    model: 'perplexity-search',
    created_at: 1,
    updated_at: 1
  },
  {
    id: 'sess_00000000000000000000000000000002',
    title: 'Unbound chat',
    bound_client_id: null,
    model: null,
    created_at: 2,
    updated_at: 2
  }
]

describe('SessionSidebar', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('highlights the active session and exposes its locked account', () => {
    render(
      <SessionSidebar
        sessions={sessions}
        activeSessionId={sessions[0].id}
        connected
        onNew={vi.fn()}
        onSelect={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    expect(
      screen.getByRole('button', { name: 'Open Native follow-up' })
    ).toHaveAttribute('aria-current', 'page')
    expect(screen.getByTitle('Locked to account-a')).toHaveTextContent(
      'account-a'
    )
  })

  it('creates, selects, renames, and deletes conversations', async () => {
    const onNew = vi.fn()
    const onSelect = vi.fn()
    const onRename = vi.fn().mockResolvedValue(true)
    const onDelete = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(
      <SessionSidebar
        sessions={sessions}
        activeSessionId={sessions[0].id}
        connected
        onNew={onNew}
        onSelect={onSelect}
        onRename={onRename}
        onDelete={onDelete}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /new conversation/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Open Unbound chat' }))
    expect(onNew).toHaveBeenCalledOnce()
    expect(onSelect).toHaveBeenCalledWith(sessions[1].id)

    fireEvent.click(
      screen.getByRole('button', { name: 'Rename Native follow-up' })
    )
    const input = screen.getByRole('textbox', { name: 'Conversation title' })
    fireEvent.change(input, { target: { value: 'Renamed native thread' } })
    fireEvent.submit(input.closest('form')!)
    await waitFor(() =>
      expect(onRename).toHaveBeenCalledWith(
        sessions[0].id,
        'Renamed native thread'
      )
    )

    fireEvent.click(screen.getByRole('button', { name: 'Delete Unbound chat' }))
    expect(onDelete).toHaveBeenCalledWith(sessions[1].id)
  })

  it('closes the mobile drawer after selecting a session', () => {
    const onClose = vi.fn()
    render(
      <SessionSidebar
        sessions={sessions}
        activeSessionId={sessions[0].id}
        connected
        onNew={vi.fn()}
        onSelect={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        onClose={onClose}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Open Unbound chat' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

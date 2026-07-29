import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProgressTimeline } from './ProgressTimeline'

describe('ProgressTimeline', () => {
  it('shows tool stages, details, and lifecycle status', () => {
    const { container } = render(
      <ProgressTimeline
        progress={[
          {
            id: 'progress-1',
            stage: 'search_web',
            status: 'completed',
            label: 'Searching the web',
            detail: { queries: ['glass frog transparency'], query_count: 1 }
          },
          {
            id: 'progress-2',
            stage: 'search_results',
            status: 'running',
            label: 'Reviewing sources',
            detail: { source_count: 2 }
          }
        ]}
      />
    )

    expect(screen.getAllByText('Reviewing sources')).toHaveLength(2)
    expect(screen.getByText(/glass frog transparency/)).toBeInTheDocument()
    expect(screen.getByText(/2 sources found/)).toBeInTheDocument()
    expect(
      container.querySelectorAll('[data-status="completed"]')
    ).toHaveLength(1)
    expect(container.querySelectorAll('[data-status="running"]')).toHaveLength(
      1
    )

    fireEvent.click(screen.getByRole('button', { name: /Reviewing sources/i }))
    expect(
      screen.queryByText(/glass frog transparency/)
    ).not.toBeInTheDocument()
  })
})

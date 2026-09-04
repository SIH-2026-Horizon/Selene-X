import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('adds the status motion hook for the API running state', () => {
    render(<StatusBadge status="running" />)

    expect(screen.getByText('RUNNING').parentElement).toHaveClass('motion-status-running')
  })

  it('renders API lifecycle states and an unknown persisted value without crashing', () => {
    render(<><StatusBadge status="created" /><StatusBadge status="succeeded" /><StatusBadge status="paused_for_maintenance" /></>)

    expect(screen.getByText('CREATED')).toBeInTheDocument()
    expect(screen.getByText('SUCCEEDED')).toBeInTheDocument()
    expect(screen.getByText('PAUSED FOR MAINTENANCE')).toBeInTheDocument()
    expect(screen.getByText('SUCCEEDED').parentElement).not.toHaveClass('motion-status-running')
  })
})

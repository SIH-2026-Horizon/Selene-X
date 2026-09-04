import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SideNavigation } from './SideNavigation'

function renderNavigation(role: 'analyst' | 'reviewer' | 'admin') {
  return render(
    <MemoryRouter>
      <SideNavigation sessionUser={{ username: role, displayName: role, role }} />
    </MemoryRouter>,
  )
}

describe('SideNavigation', () => {
  it('restores the Campaigns menu and hides privileged items from analysts', () => {
    renderNavigation('analyst')

    expect(screen.getByRole('link', { name: /campaigns/i })).toHaveAttribute('href', '/campaigns')
    expect(screen.queryByRole('link', { name: /^review$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /administration/i })).not.toBeInTheDocument()
  })

  it('shows Review to reviewers and Administration only to admins', () => {
    const { rerender } = renderNavigation('reviewer')
    expect(screen.getByRole('link', { name: /^review$/i })).toHaveAttribute('href', '/jobs?state=succeeded')
    expect(screen.queryByRole('link', { name: /administration/i })).not.toBeInTheDocument()

    rerender(<MemoryRouter><SideNavigation sessionUser={{ username: 'admin', displayName: 'admin', role: 'admin' }} /></MemoryRouter>)
    expect(screen.getByRole('link', { name: /administration/i })).toHaveAttribute('href', '/admin')
  })
})

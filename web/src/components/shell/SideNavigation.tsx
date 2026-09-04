import { NavLink, useLocation } from 'react-router-dom'
import type { CSSProperties } from 'react'
import clsx from 'clsx'
import type { SessionUser } from '@/repositories/authRepository'

type Role = SessionUser['role']

interface NavItem {
  label: string
  to: string
  marker: '+' | '-'
  roles?: Role[]
}

interface NavGroup {
  title?: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { label: 'Overview', to: '/', marker: '+' },
      { label: 'Catalogue', to: '/catalog', marker: '+' },
      { label: 'Registration', to: '/register', marker: '+' },
      { label: 'Jobs', to: '/jobs', marker: '+' },
      { label: 'Review', to: '/jobs?state=succeeded', marker: '+', roles: ['reviewer', 'admin'] },
      { label: 'Knowledge', to: '/knowledge', marker: '+' },
    ],
  },
  {
    title: 'Operations',
    items: [
      { label: 'Campaigns', to: '/campaigns', marker: '-' },
      { label: 'Registration graphs', to: '/graphs', marker: '-' },
    ],
  },
  {
    title: 'Research / Configuration',
    items: [
      { label: 'Parameters', to: '/parameters', marker: '-' },
      { label: 'Models', to: '/models', marker: '-' },
    ],
  },
  {
    title: 'System',
    items: [
      { label: 'Audit', to: '/audit', marker: '-' },
      { label: 'Administration', to: '/admin', marker: '-', roles: ['admin'] },
    ],
  },
]

interface SideNavigationProps {
  sessionUser?: SessionUser
}

export function SideNavigation({ sessionUser }: SideNavigationProps) {
  const location = useLocation()
  const currentPath = `${location.pathname}${location.search}`

  return (
    <nav aria-label="Primary" className="motion-reveal flex w-60 shrink-0 flex-col gap-4 overflow-y-auto border-r border-hairline bg-canvas py-4 scrollbar-hairline">
      {NAV_GROUPS.map((group, i) => (
        <div key={i} className={i > 0 ? 'border-t border-hairline pt-4' : ''}>
          {group.title && (
            <div className="px-4 pb-2 text-micro font-medium uppercase tracking-wide text-mute">{group.title}</div>
          )}
          <ul className="motion-stagger flex flex-col">
            {group.items.filter((item) => !item.roles || !sessionUser || item.roles.includes(sessionUser.role)).map((item, itemIndex) => {
              // Items with a query string (e.g. Review -> /jobs?state=...) need an exact
              // pathname+search match — NavLink's own isActive ignores search params. And
              // since Jobs and Review share the /jobs pathname, Jobs is only active when
              // there's no state filter applied (otherwise both would highlight at once).
              const hasQuery = item.to.includes('?')
              const isActive = hasQuery
                ? currentPath === item.to
                : item.to === '/jobs'
                  ? location.pathname === '/jobs' && location.search === ''
                  : location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(`${item.to}/`))

              return (
                <li key={item.label}>
                  <NavLink
                    to={item.to}
                    end={item.to === '/'}
                    className={clsx(
                      'motion-reveal flex items-center gap-2 border-l-2 px-4 py-1.5 text-caption',
                      isActive ? 'border-ink font-semibold text-ink' : 'border-transparent text-body hover:bg-surface-soft',
                    )}
                    style={{ '--motion-index': itemIndex } as CSSProperties}
                  >
                    <span aria-hidden="true" className="text-mute">
                      [{item.marker}]
                    </span>
                    {item.label}
                  </NavLink>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}

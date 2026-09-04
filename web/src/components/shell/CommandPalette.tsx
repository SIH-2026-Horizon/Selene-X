import { useEffect, useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useCommandPaletteStore } from '@/stores/commandPaletteStore'
import { catalogRepository } from '@/repositories/catalogRepository'
import { jobsRepository } from '@/repositories/jobsRepository'
import { knowledgeRepository } from '@/repositories/knowledgeRepository'

interface Command { id: string; label: string; hint?: string; run: () => void }

export function CommandPalette() {
  const isOpen = useCommandPaletteStore((state) => state.isOpen)
  const close = useCommandPaletteStore((state) => state.close)
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [debouncedTerm, setDebouncedTerm] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const term = query.trim()
  const searchPending = Boolean(term) && term !== debouncedTerm
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedTerm(term), 250)
    return () => window.clearTimeout(timer)
  }, [term])
  const [productsQuery, runsQuery, entitiesQuery] = useQueries({ queries: [
    { queryKey: ['command', 'products', debouncedTerm], queryFn: ({ signal }) => catalogRepository.searchProducts(debouncedTerm, { signal }), enabled: isOpen && Boolean(debouncedTerm) },
    { queryKey: ['command', 'runs', debouncedTerm], queryFn: ({ signal }) => jobsRepository.searchJobs(debouncedTerm, { signal }), enabled: isOpen && Boolean(debouncedTerm) },
    { queryKey: ['command', 'knowledge-entities', debouncedTerm], queryFn: ({ signal }) => knowledgeRepository.query({ query: debouncedTerm, limit: 10 }, { signal }), enabled: isOpen && Boolean(debouncedTerm) },
  ] })
  const staticCommands = useMemo<Command[]>(() => [
    { id: 'nav-overview', label: 'Open overview', run: () => navigate('/') }, { id: 'nav-catalog', label: 'Open catalogue', run: () => navigate('/catalog') }, { id: 'nav-register', label: 'Create persisted run', run: () => navigate('/register') }, { id: 'nav-jobs', label: 'Open persisted runs', run: () => navigate('/jobs') }, { id: 'nav-knowledge', label: 'Open semantic knowledge', run: () => navigate('/knowledge') }, { id: 'nav-graphs', label: 'Open registration provenance graph', run: () => navigate('/graphs') },
  ], [navigate])
  const commands = useMemo<Command[]>(() => {
    if (!term) return staticCommands
    const lower = term.toLowerCase()
    if (searchPending) return staticCommands.filter((command) => command.label.toLowerCase().includes(lower))
    return [
      ...(productsQuery.data?.items ?? []).slice(0, 4).map((product) => ({ id: `product-${product.id}`, label: product.productIdentity, hint: `${product.payloadType} product`, run: () => navigate(`/catalog/${product.id}`) })),
      ...(runsQuery.data?.items ?? []).slice(0, 4).map((run) => ({ id: `run-${run.id}`, label: run.id, hint: `run — ${run.state}`, run: () => navigate(`/jobs/${run.id}`) })),
      ...(entitiesQuery.data?.nodes ?? []).slice(0, 4).map((entity) => ({ id: `entity-${entity.id}`, label: entity.label, hint: entity.type, run: () => navigate(entity.type === 'CRATER' ? `/knowledge/craters/${entity.id}` : `/knowledge?q=${encodeURIComponent(entity.label)}`) })),
      ...staticCommands.filter((command) => command.label.toLowerCase().includes(lower)),
    ]
  }, [entitiesQuery.data, navigate, productsQuery.data, runsQuery.data, searchPending, staticCommands, term])
  useEffect(() => { if (!isOpen) { setQuery(''); setDebouncedTerm(''); setActiveIndex(0) } }, [isOpen])
  useEffect(() => { setActiveIndex(0) }, [commands.length])
  useEffect(() => { const listener = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }; if (isOpen) document.addEventListener('keydown', listener); return () => document.removeEventListener('keydown', listener) }, [close, isOpen])
  if (!isOpen) return null
  function run(command: Command) { command.run(); close() }
  function keyDown(event: React.KeyboardEvent<HTMLInputElement>) { if (event.key === 'ArrowDown') { event.preventDefault(); setActiveIndex((index) => Math.min(commands.length - 1, index + 1)) } else if (event.key === 'ArrowUp') { event.preventDefault(); setActiveIndex((index) => Math.max(0, index - 1)) } else if (event.key === 'Enter' && commands[activeIndex]) run(commands[activeIndex]) }
  return <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/40 pt-24" onClick={close}><div role="dialog" aria-modal="true" aria-label="Command palette" onClick={(event) => event.stopPropagation()} className="w-full max-w-lg border border-hairline-strong bg-canvas"><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={keyDown} placeholder="Search persisted products, runs, or semantic entities…" className="w-full border-b border-hairline px-4 py-3 text-body focus:outline-none" /><ul className="max-h-80 overflow-y-auto scrollbar-hairline">{term && (searchPending || productsQuery.isLoading || runsQuery.isLoading || entitiesQuery.isLoading) && <li className="px-4 py-3 text-caption text-mute">Searching persisted records…</li>}{term && !searchPending && !productsQuery.isLoading && !runsQuery.isLoading && !entitiesQuery.isLoading && commands.length === 0 && <li className="px-4 py-3 text-caption text-mute">No matching persisted records in the first result page.</li>}{commands.map((command, index) => <li key={command.id}><button onClick={() => run(command)} className={'flex w-full items-center justify-between px-4 py-2 text-left text-caption ' + (index === activeIndex ? 'bg-surface-soft' : '')}><span>{command.label}</span>{command.hint && <span className="text-micro text-mute">{command.hint}</span>}</button></li>)}</ul></div></div>
}

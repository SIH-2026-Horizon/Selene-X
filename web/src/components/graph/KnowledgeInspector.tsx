import { Link } from 'react-router-dom'
import type { KnowledgeNode } from '@/types/knowledge'
import { KNOWLEDGE_ENTITY_MARKER } from '@/types/knowledge'
import { MetadataGrid } from '@/components/ui/MetadataGrid'

export function KnowledgeInspector({ node }: { node: KnowledgeNode | null }) {
  if (!node) return <p className="text-caption text-mute">Select a persisted semantic entity to inspect its stored properties.</p>
  return <div className="space-y-4"><div><div className="text-section-title">{KNOWLEDGE_ENTITY_MARKER[node.type] ?? '[?]'} {node.label}</div><p className="mt-1 break-all text-caption text-mute">{node.type} · {node.id}</p></div><MetadataGrid columns={1} entries={[{ label: 'External ID', value: node.externalId ?? 'N/A' }, { label: 'Location CRS', value: node.locationCrs ?? 'N/A / no persisted location' }, { label: 'Created', value: new Date(node.createdAt).toISOString() }]} /><details><summary className="cursor-pointer text-caption text-accent">Persisted properties</summary><pre className="mt-2 whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{JSON.stringify(node.properties, null, 2)}</pre></details>{node.type === 'CRATER' && <Link to={`/knowledge/craters/${node.id}`} className="inline-block border border-hairline px-3 py-2 text-caption text-accent hover:bg-surface-soft">Open crater entity →</Link>}</div>
}

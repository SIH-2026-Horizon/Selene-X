import { create } from 'zustand'
import type { KnowledgeEntityType, KnowledgeRelationType } from '@/types/knowledge'

export type KnowledgeTab = 'graph' | 'map' | 'results'

interface KnowledgeViewState {
  activeTab: KnowledgeTab
  setActiveTab: (tab: KnowledgeTab) => void
  selectedNodeId: string | null
  setSelectedNodeId: (id: string | null) => void
  entityTypeFilters: KnowledgeEntityType[]
  toggleEntityTypeFilter: (type: KnowledgeEntityType) => void
  relationFilters: KnowledgeRelationType[]
  toggleRelationFilter: (relation: KnowledgeRelationType) => void
  reset: () => void
}

export const useKnowledgeViewStore = create<KnowledgeViewState>((set) => ({
  activeTab: 'graph',
  setActiveTab: (tab) => set({ activeTab: tab }),
  selectedNodeId: null,
  setSelectedNodeId: (id) => set({ selectedNodeId: id }),
  entityTypeFilters: [],
  toggleEntityTypeFilter: (type) =>
    set((s) => ({
      entityTypeFilters: s.entityTypeFilters.includes(type)
        ? s.entityTypeFilters.filter((t) => t !== type)
        : [...s.entityTypeFilters, type],
    })),
  relationFilters: [],
  toggleRelationFilter: (relation) =>
    set((s) => ({
      relationFilters: s.relationFilters.includes(relation)
        ? s.relationFilters.filter((r) => r !== relation)
        : [...s.relationFilters, relation],
    })),
  reset: () => set({ selectedNodeId: null, activeTab: 'graph' }),
}))

import { create } from 'zustand'

export type ReviewViewMode =
  | 'source'
  | 'reference'
  | 'registered'
  | 'split'
  | 'checkerboard'
  | 'difference'
  | 'tiepoints'
  | 'residuals'
  | 'uniformity'

interface WorkspaceState {
  viewMode: ReviewViewMode
  setViewMode: (mode: ReviewViewMode) => void
  syncViews: boolean
  toggleSync: () => void
  checkerboardCellSize: number
  setCheckerboardCellSize: (size: number) => void
  differenceOpacity: number
  setDifferenceOpacity: (opacity: number) => void
  selectedTiePointId: string | null
  setSelectedTiePointId: (id: string | null) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  viewMode: 'split',
  setViewMode: (mode) => set({ viewMode: mode }),
  syncViews: true,
  toggleSync: () => set((s) => ({ syncViews: !s.syncViews })),
  checkerboardCellSize: 64,
  setCheckerboardCellSize: (size) => set({ checkerboardCellSize: size }),
  differenceOpacity: 0.5,
  setDifferenceOpacity: (opacity) => set({ differenceOpacity: opacity }),
  selectedTiePointId: null,
  setSelectedTiePointId: (id) => set({ selectedTiePointId: id }),
}))

import { ScatterplotLayer } from '@deck.gl/layers'
import type { TiePoint } from '@/types/tiepoint'

interface CreateTiePointLayerOptions {
  id: string
  tiePoints: TiePoint[]
  useReference?: boolean
  selectedId?: string | null
  onClick?: (tiePoint: TiePoint) => void
}

export function createTiePointLayer({ id, tiePoints, useReference, selectedId, onClick }: CreateTiePointLayerOptions) {
  return new ScatterplotLayer<TiePoint>({
    id,
    data: tiePoints,
    pickable: true,
    radiusUnits: 'common',
    getPosition: (d) => (useReference ? [d.reference.x, d.reference.y] : [d.source.x, d.source.y]),
    getRadius: (d) => 3 + d.confidence * 3,
    radiusMinPixels: 2,
    radiusMaxPixels: 14,
    stroked: true,
    lineWidthMinPixels: 1,
    getLineColor: [253, 252, 252, 200],
    getFillColor: (d) => (d.id === selectedId ? [0, 122, 255, 255] : [32, 29, 29, 170]),
    updateTriggers: {
      getFillColor: [selectedId],
    },
    onClick: (info) => {
      if (info.object) onClick?.(info.object)
    },
  })
}

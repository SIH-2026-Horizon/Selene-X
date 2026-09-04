import { LineLayer } from '@deck.gl/layers'
import type { TiePoint } from '@/types/tiepoint'

interface CreateResidualVectorLayerOptions {
  id: string
  tiePoints: TiePoint[]
  /** Sub-pixel residuals are exaggerated so direction is visible at typical zoom. */
  exaggeration?: number
}

export function createResidualVectorLayer({ id, tiePoints, exaggeration = 15 }: CreateResidualVectorLayerOptions) {
  return new LineLayer<TiePoint>({
    id,
    data: tiePoints,
    pickable: false,
    widthUnits: 'pixels',
    getWidth: 1.5,
    getSourcePosition: (d) => [d.source.x, d.source.y],
    getTargetPosition: (d) => [
      d.source.x + (d.reference.x - d.source.x) * exaggeration,
      d.source.y + (d.reference.y - d.source.y) * exaggeration,
    ],
    getColor: [255, 159, 10, 220],
  })
}

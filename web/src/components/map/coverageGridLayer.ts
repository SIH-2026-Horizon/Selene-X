import { SolidPolygonLayer } from '@deck.gl/layers'
import type { UniformityGrid } from '@/types/tiepoint'

interface CoveragePolygon {
  polygon: [number, number][]
  occupied: boolean
  eligible: boolean
}

interface CreateCoverageGridLayerOptions {
  id: string
  grid: UniformityGrid
  imageSize: number
}

export function createCoverageGridLayer({ id, grid, imageSize }: CreateCoverageGridLayerOptions) {
  const cellW = imageSize / grid.cols
  const cellH = imageSize / grid.rows

  const polygons: CoveragePolygon[] = grid.cells.map((cell) => ({
    occupied: cell.occupied,
    eligible: cell.eligible,
    polygon: [
      [cell.col * cellW, cell.row * cellH],
      [(cell.col + 1) * cellW, cell.row * cellH],
      [(cell.col + 1) * cellW, (cell.row + 1) * cellH],
      [cell.col * cellW, (cell.row + 1) * cellH],
    ],
  }))

  return new SolidPolygonLayer<CoveragePolygon>({
    id,
    data: polygons,
    pickable: false,
    getPolygon: (d) => d.polygon,
    getFillColor: (d) => (!d.eligible ? [110, 110, 115, 30] : d.occupied ? [48, 209, 88, 55] : [255, 59, 48, 70]),
    getLineColor: [32, 29, 29, 130],
    wireframe: true,
    filled: true,
  })
}

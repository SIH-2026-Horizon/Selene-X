export interface ImageCoord {
  x: number
  y: number
}

export interface Covariance {
  sigmaX: number
  sigmaY: number
  rho: number
}

export interface TiePoint {
  id: string
  source: ImageCoord
  reference: ImageCoord
  residualPx: number
  confidence: number
  covariance: Covariance
  score: number
}

export interface UniformityCell {
  col: number
  row: number
  occupied: boolean
  eligible: boolean
  pointCount: number
}

export interface UniformityGrid {
  cols: number
  rows: number
  cells: UniformityCell[]
  coveragePct: number
  largestEmptyRegionPct: number
}

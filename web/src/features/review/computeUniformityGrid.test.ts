import { describe, expect, it } from 'vitest'
import { computeUniformityGrid } from './computeUniformityGrid'
import type { TiePoint } from '@/types/tiepoint'

function makePoint(x: number, y: number): TiePoint {
  return {
    id: `TP-${x}-${y}`,
    source: { x, y },
    reference: { x: x + 1, y: y + 1 },
    residualPx: 0.4,
    confidence: 0.9,
    covariance: { sigmaX: 0.1, sigmaY: 0.1, rho: 0 },
    score: 0.9,
  }
}

describe('computeUniformityGrid', () => {
  it('marks every eligible cell empty when there are no tie points', () => {
    const grid = computeUniformityGrid([], 800, 8)
    expect(grid.coveragePct).toBe(0)
    expect(grid.cells.every((cell) => !cell.occupied)).toBe(true)
  })

  it('marks the cell containing a tie point as occupied', () => {
    // 800px / 8 = 100px cells; a point at (150, 150) falls in cell col=1,row=1
    const grid = computeUniformityGrid([makePoint(150, 150)], 800, 8)
    const cell = grid.cells.find((c) => c.col === 1 && c.row === 1)
    expect(cell?.occupied).toBe(true)
    expect(cell?.pointCount).toBe(1)
  })

  it('reaches 100% coverage when every eligible cell has a point', () => {
    const gridSize = 4
    const cellSize = 400 / gridSize
    const points: TiePoint[] = []
    for (let row = 0; row < gridSize; row++) {
      for (let col = 0; col < gridSize; col++) {
        points.push(makePoint(col * cellSize + 1, row * cellSize + 1))
      }
    }
    const grid = computeUniformityGrid(points, 400, gridSize)
    expect(grid.coveragePct).toBe(100)
  })
})

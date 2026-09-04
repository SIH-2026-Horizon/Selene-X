import type { TiePoint, UniformityGrid } from '@/types/tiepoint'

export function computeUniformityGrid(tiePoints: TiePoint[], imageSize: number, gridSize = 8): UniformityGrid {
  const cellSize = imageSize / gridSize
  const counts = new Map<string, number>()

  for (const tp of tiePoints) {
    const col = Math.min(gridSize - 1, Math.floor(tp.source.x / cellSize))
    const row = Math.min(gridSize - 1, Math.floor(tp.source.y / cellSize))
    const key = `${col}:${row}`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  const cells: UniformityGrid['cells'] = []
  let occupiedEligible = 0
  let eligibleCount = 0

  for (let row = 0; row < gridSize; row++) {
    for (let col = 0; col < gridSize; col++) {
      const count = counts.get(`${col}:${row}`) ?? 0
      const eligible = true
      if (eligible) {
        eligibleCount++
        if (count > 0) occupiedEligible++
      }
      cells.push({ col, row, occupied: count > 0, eligible, pointCount: count })
    }
  }

  let largestEmptyRun = 0
  for (let row = 0; row < gridSize; row++) {
    let run = 0
    for (let col = 0; col < gridSize; col++) {
      const cell = cells[row * gridSize + col]
      if (cell.eligible && !cell.occupied) {
        run++
        largestEmptyRun = Math.max(largestEmptyRun, run)
      } else {
        run = 0
      }
    }
  }

  return {
    cols: gridSize,
    rows: gridSize,
    cells,
    coveragePct: eligibleCount === 0 ? 0 : Math.round((occupiedEligible / eligibleCount) * 100),
    largestEmptyRegionPct: Math.round((largestEmptyRun / gridSize) * 100),
  }
}

import { useState } from 'react'
import type { TiePoint, UniformityGrid } from '@/types/tiepoint'
import { useWorkspaceStore, type ReviewViewMode } from '@/stores/workspaceStore'
import { ImageStage } from './ImageStage'
import { SyncedImageView } from './SyncedImageView'
import { CheckerboardViewer } from './CheckerboardViewer'
import { DifferenceViewer } from './DifferenceViewer'
import { DeckOverlay } from './DeckOverlay'
import { fitViewport, type ImageViewport } from './viewport'
import { createTiePointLayer } from '@/components/map/tiePointLayer'
import { createResidualVectorLayer } from '@/components/map/residualVectorLayer'
import { createCoverageGridLayer } from '@/components/map/coverageGridLayer'

const DEFAULT_VIEWPORT: ImageViewport = { scale: 1, tx: 0, ty: 0 }

const VIEW_MODES: { id: ReviewViewMode; label: string }[] = [
  { id: 'source', label: 'Source' },
  { id: 'reference', label: 'Reference' },
  { id: 'registered', label: 'Registered' },
  { id: 'split', label: 'Split' },
  { id: 'checkerboard', label: 'Checkerboard' },
  { id: 'difference', label: 'Difference' },
  { id: 'tiepoints', label: 'Tie Points' },
  { id: 'residuals', label: 'Residuals' },
  { id: 'uniformity', label: 'Uniformity' },
]

interface ImageComparatorProps {
  imageSize: number
  sourceUrl: string
  referenceUrl: string
  registeredUrl: string
  tiePoints: TiePoint[]
  uniformityGrid: UniformityGrid
  onSelectTiePoint: (tiePoint: TiePoint) => void
}

export function ImageComparator({
  imageSize,
  sourceUrl,
  referenceUrl,
  registeredUrl,
  tiePoints,
  uniformityGrid,
  onSelectTiePoint,
}: ImageComparatorProps) {
  const {
    viewMode,
    setViewMode,
    syncViews,
    toggleSync,
    checkerboardCellSize,
    setCheckerboardCellSize,
    differenceOpacity,
    setDifferenceOpacity,
    selectedTiePointId,
  } = useWorkspaceStore()

  const [primaryViewport, setPrimaryViewport] = useState<ImageViewport>(DEFAULT_VIEWPORT)
  const [secondaryViewport, setSecondaryViewport] = useState<ImageViewport>(DEFAULT_VIEWPORT)
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })

  const effectiveSecondary = syncViews ? primaryViewport : secondaryViewport

  function handleRightViewportChange(next: ImageViewport) {
    if (syncViews) setPrimaryViewport(next)
    else setSecondaryViewport(next)
  }

  function resetView() {
    if (containerSize.width === 0) return
    const fitted = fitViewport(containerSize.width, containerSize.height, imageSize)
    setPrimaryViewport(fitted)
    setSecondaryViewport(fitted)
  }

  function handleTiePointClick(tp: TiePoint) {
    onSelectTiePoint(tp)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b border-hairline bg-surface-soft px-2 py-1.5">
        {VIEW_MODES.map((mode) => (
          <button
            key={mode.id}
            onClick={() => setViewMode(mode.id)}
            className={
              'rounded px-2.5 py-1 text-caption ' +
              (viewMode === mode.id ? 'bg-ink text-canvas' : 'text-body hover:bg-surface-card')
            }
          >
            {mode.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          {viewMode === 'split' && (
            <label className="flex items-center gap-1.5 text-caption text-body">
              <input type="checkbox" checked={syncViews} onChange={toggleSync} className="accent-ink" />
              Sync views
            </label>
          )}
          {viewMode === 'checkerboard' && (
            <label className="flex items-center gap-2 text-caption text-body">
              Cell size
              <input
                type="range"
                min={16}
                max={256}
                step={8}
                value={checkerboardCellSize}
                onChange={(e) => setCheckerboardCellSize(Number(e.target.value))}
              />
              <span className="tabular-nums text-mute">{checkerboardCellSize}px</span>
            </label>
          )}
          {viewMode === 'difference' && (
            <label className="flex items-center gap-2 text-caption text-body">
              Opacity
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={differenceOpacity}
                onChange={(e) => setDifferenceOpacity(Number(e.target.value))}
              />
              <span className="tabular-nums text-mute">{Math.round(differenceOpacity * 100)}%</span>
            </label>
          )}
          <button onClick={resetView} className="text-caption text-mute hover:text-ink">
            fit
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {viewMode === 'source' && (
          <ImageStage imageSize={imageSize} viewport={primaryViewport} onViewportChange={setPrimaryViewport} onCursorImagePosition={setCursor} onContainerSize={setContainerSize} label="Source">
            <img src={sourceUrl} width={imageSize} height={imageSize} draggable={false} alt="Source" />
          </ImageStage>
        )}
        {viewMode === 'reference' && (
          <ImageStage imageSize={imageSize} viewport={primaryViewport} onViewportChange={setPrimaryViewport} onCursorImagePosition={setCursor} onContainerSize={setContainerSize} label="Reference">
            <img src={referenceUrl} width={imageSize} height={imageSize} draggable={false} alt="Reference" />
          </ImageStage>
        )}
        {viewMode === 'registered' && (
          <ImageStage imageSize={imageSize} viewport={primaryViewport} onViewportChange={setPrimaryViewport} onCursorImagePosition={setCursor} onContainerSize={setContainerSize} label="Registered">
            <img src={registeredUrl} width={imageSize} height={imageSize} draggable={false} alt="Registered" />
          </ImageStage>
        )}
        {viewMode === 'split' && (
          <SyncedImageView
            imageSize={imageSize}
            leftLabel="SOURCE"
            leftUrl={sourceUrl}
            rightLabel="REFERENCE"
            rightUrl={referenceUrl}
            leftViewport={primaryViewport}
            onLeftViewportChange={setPrimaryViewport}
            rightViewport={effectiveSecondary}
            onRightViewportChange={handleRightViewportChange}
          />
        )}
        {viewMode === 'checkerboard' && (
          <CheckerboardViewer
            sourceUrl={sourceUrl}
            referenceUrl={referenceUrl}
            imageSize={imageSize}
            viewport={primaryViewport}
            onViewportChange={setPrimaryViewport}
            cellSize={checkerboardCellSize}
          />
        )}
        {viewMode === 'difference' && (
          <DifferenceViewer
            sourceUrl={sourceUrl}
            referenceUrl={referenceUrl}
            imageSize={imageSize}
            viewport={primaryViewport}
            onViewportChange={setPrimaryViewport}
            opacity={differenceOpacity}
          />
        )}
        {viewMode === 'tiepoints' && (
          <ImageStage
            imageSize={imageSize}
            viewport={primaryViewport}
            onViewportChange={setPrimaryViewport}
            onCursorImagePosition={setCursor}
            onContainerSize={setContainerSize}
            label="Tie points"
            overlayInteractive
            overlay={(w, h) => (
              <DeckOverlay
                viewport={primaryViewport}
                containerWidth={w}
                containerHeight={h}
                layers={[
                  createTiePointLayer({
                    id: 'tie-points',
                    tiePoints,
                    selectedId: selectedTiePointId,
                    onClick: handleTiePointClick,
                  }),
                ]}
              />
            )}
          >
            <img src={sourceUrl} width={imageSize} height={imageSize} draggable={false} alt="Source" />
          </ImageStage>
        )}
        {viewMode === 'residuals' && (
          <ImageStage
            imageSize={imageSize}
            viewport={primaryViewport}
            onViewportChange={setPrimaryViewport}
            onCursorImagePosition={setCursor}
            onContainerSize={setContainerSize}
            label="Residual vectors"
            overlay={(w, h) => (
              <DeckOverlay
                viewport={primaryViewport}
                containerWidth={w}
                containerHeight={h}
                layers={[
                  createResidualVectorLayer({ id: 'residual-vectors', tiePoints }),
                  createTiePointLayer({ id: 'residual-points', tiePoints }),
                ]}
              />
            )}
          >
            <img src={sourceUrl} width={imageSize} height={imageSize} draggable={false} alt="Source" />
          </ImageStage>
        )}
        {viewMode === 'uniformity' && (
          <ImageStage
            imageSize={imageSize}
            viewport={primaryViewport}
            onViewportChange={setPrimaryViewport}
            onCursorImagePosition={setCursor}
            onContainerSize={setContainerSize}
            label="Uniformity grid"
            overlay={(w, h) => (
              <DeckOverlay
                viewport={primaryViewport}
                containerWidth={w}
                containerHeight={h}
                layers={[createCoverageGridLayer({ id: 'coverage-grid', grid: uniformityGrid, imageSize })]}
              />
            )}
          >
            <img src={sourceUrl} width={imageSize} height={imageSize} draggable={false} alt="Source" />
          </ImageStage>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-hairline bg-surface-soft px-3 py-1.5 text-micro text-mute">
        <span>
          {cursor ? `x ${cursor.x.toFixed(1)}  y ${cursor.y.toFixed(1)}` : 'x —  y —'}
        </span>
        <span>zoom {(primaryViewport.scale * 100).toFixed(0)}%</span>
        <span>{tiePoints.length} tie points</span>
      </div>
    </div>
  )
}

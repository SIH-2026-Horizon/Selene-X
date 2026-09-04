import { useMemo } from 'react'
import { ImageStage } from './ImageStage'
import type { ImageViewport } from './viewport'

function createCheckerTile(): string {
  const canvas = document.createElement('canvas')
  canvas.width = 2
  canvas.height = 2
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  // CSS mask-image in Chromium masks by alpha, not luminance — opaque squares
  // reveal, fully transparent squares hide. Two opaque colors would show through
  // uniformly and produce no visible checkering at all.
  ctx.clearRect(0, 0, 2, 2)
  ctx.fillStyle = '#000000'
  ctx.fillRect(0, 0, 1, 1)
  ctx.fillRect(1, 1, 1, 1)
  return canvas.toDataURL()
}

interface CheckerboardViewerProps {
  sourceUrl: string
  referenceUrl: string
  imageSize: number
  viewport: ImageViewport
  onViewportChange: (viewport: ImageViewport) => void
  cellSize: number
}

export function CheckerboardViewer({
  sourceUrl,
  referenceUrl,
  imageSize,
  viewport,
  onViewportChange,
  cellSize,
}: CheckerboardViewerProps) {
  const maskUrl = useMemo(createCheckerTile, [])

  return (
    <ImageStage imageSize={imageSize} viewport={viewport} onViewportChange={onViewportChange} label="Checkerboard comparison">
      <img src={sourceUrl} width={imageSize} height={imageSize} draggable={false} alt="Source" className="absolute left-0 top-0" />
      <img
        src={referenceUrl}
        width={imageSize}
        height={imageSize}
        draggable={false}
        alt="Reference"
        className="absolute left-0 top-0"
        style={{
          maskImage: `url(${maskUrl})`,
          WebkitMaskImage: `url(${maskUrl})`,
          maskSize: `${cellSize * 2}px ${cellSize * 2}px`,
          WebkitMaskSize: `${cellSize * 2}px ${cellSize * 2}px`,
          maskRepeat: 'repeat',
          WebkitMaskRepeat: 'repeat',
        }}
      />
    </ImageStage>
  )
}

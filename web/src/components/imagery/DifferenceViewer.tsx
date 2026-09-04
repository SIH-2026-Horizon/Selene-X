import { ImageStage } from './ImageStage'
import type { ImageViewport } from './viewport'

interface DifferenceViewerProps {
  sourceUrl: string
  referenceUrl: string
  imageSize: number
  viewport: ImageViewport
  onViewportChange: (viewport: ImageViewport) => void
  opacity: number
}

export function DifferenceViewer({
  sourceUrl,
  referenceUrl,
  imageSize,
  viewport,
  onViewportChange,
  opacity,
}: DifferenceViewerProps) {
  return (
    <ImageStage imageSize={imageSize} viewport={viewport} onViewportChange={onViewportChange} label="Difference comparison">
      <img src={sourceUrl} width={imageSize} height={imageSize} draggable={false} alt="Source" className="absolute left-0 top-0" />
      <img
        src={referenceUrl}
        width={imageSize}
        height={imageSize}
        draggable={false}
        alt="Reference"
        className="absolute left-0 top-0"
        style={{ mixBlendMode: 'difference', opacity }}
      />
    </ImageStage>
  )
}

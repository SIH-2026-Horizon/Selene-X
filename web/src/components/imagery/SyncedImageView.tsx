import { ImageStage } from './ImageStage'
import type { ImageViewport } from './viewport'

interface SyncedImageViewProps {
  imageSize: number
  leftLabel: string
  leftUrl: string
  rightLabel: string
  rightUrl: string
  leftViewport: ImageViewport
  onLeftViewportChange: (viewport: ImageViewport) => void
  rightViewport: ImageViewport
  onRightViewportChange: (viewport: ImageViewport) => void
}

export function SyncedImageView({
  imageSize,
  leftLabel,
  leftUrl,
  rightLabel,
  rightUrl,
  leftViewport,
  onLeftViewportChange,
  rightViewport,
  onRightViewportChange,
}: SyncedImageViewProps) {
  return (
    <div className="grid h-full grid-cols-2 divide-x divide-hairline-strong">
      <div className="relative h-full">
        <span className="absolute left-2 top-2 z-10 bg-surface-dark/85 px-1.5 py-0.5 text-micro text-canvas">
          {leftLabel}
        </span>
        <ImageStage imageSize={imageSize} viewport={leftViewport} onViewportChange={onLeftViewportChange} label={leftLabel}>
          <img src={leftUrl} width={imageSize} height={imageSize} draggable={false} alt={leftLabel} />
        </ImageStage>
      </div>
      <div className="relative h-full">
        <span className="absolute left-2 top-2 z-10 bg-surface-dark/85 px-1.5 py-0.5 text-micro text-canvas">
          {rightLabel}
        </span>
        <ImageStage imageSize={imageSize} viewport={rightViewport} onViewportChange={onRightViewportChange} label={rightLabel}>
          <img src={rightUrl} width={imageSize} height={imageSize} draggable={false} alt={rightLabel} />
        </ImageStage>
      </div>
    </div>
  )
}

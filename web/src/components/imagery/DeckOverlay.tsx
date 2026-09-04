import DeckGL from '@deck.gl/react'
import { OrthographicView } from '@deck.gl/core'
import type { Layer } from '@deck.gl/core'
import { toDeckOrthoViewState } from './viewport'
import type { ImageViewport } from './viewport'

const VIEW = new OrthographicView({ id: 'image-space' })

interface DeckOverlayProps {
  viewport: ImageViewport
  containerWidth: number
  containerHeight: number
  layers: Layer[]
}

export function DeckOverlay({ viewport, containerWidth, containerHeight, layers }: DeckOverlayProps) {
  const viewState = toDeckOrthoViewState(viewport, containerWidth, containerHeight)
  return (
    <DeckGL views={VIEW} viewState={viewState} controller={false} layers={layers} style={{ position: 'absolute', inset: '0' }} />
  )
}

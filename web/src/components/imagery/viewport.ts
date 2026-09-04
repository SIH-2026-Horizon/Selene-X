export interface ImageViewport {
  scale: number
  tx: number
  ty: number
}

export function fitViewport(containerWidth: number, containerHeight: number, imageSize: number): ImageViewport {
  const scale = Math.max(0.001, Math.min(containerWidth, containerHeight) / imageSize)
  return {
    scale,
    tx: (containerWidth - imageSize * scale) / 2,
    ty: (containerHeight - imageSize * scale) / 2,
  }
}

export function zoomAt(viewport: ImageViewport, clientX: number, clientY: number, deltaY: number): ImageViewport {
  const factor = Math.exp(-deltaY * 0.0015)
  const newScale = Math.min(24, Math.max(0.02, viewport.scale * factor))
  const imgX = (clientX - viewport.tx) / viewport.scale
  const imgY = (clientY - viewport.ty) / viewport.scale
  return { scale: newScale, tx: clientX - imgX * newScale, ty: clientY - imgY * newScale }
}

export function panBy(viewport: ImageViewport, dx: number, dy: number): ImageViewport {
  return { ...viewport, tx: viewport.tx + dx, ty: viewport.ty + dy }
}

export function screenToImage(viewport: ImageViewport, clientX: number, clientY: number) {
  return { x: (clientX - viewport.tx) / viewport.scale, y: (clientY - viewport.ty) / viewport.scale }
}

export function toDeckOrthoViewState(viewport: ImageViewport, containerWidth: number, containerHeight: number) {
  const zoom = Math.log2(viewport.scale)
  const centerX = (containerWidth / 2 - viewport.tx) / viewport.scale
  const centerY = (containerHeight / 2 - viewport.ty) / viewport.scale
  return { target: [centerX, centerY, 0] as [number, number, number], zoom, minZoom: -8, maxZoom: 10 }
}

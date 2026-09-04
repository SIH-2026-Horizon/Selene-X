import { useEffect, useRef, useState, type PointerEvent, type ReactNode, type WheelEvent } from 'react'
import clsx from 'clsx'
import { fitViewport, panBy, screenToImage, zoomAt, type ImageViewport } from './viewport'

interface ImageStageProps {
  imageSize: number
  viewport: ImageViewport
  onViewportChange: (viewport: ImageViewport) => void
  children?: ReactNode
  overlay?: (containerWidth: number, containerHeight: number) => ReactNode
  overlayInteractive?: boolean
  label?: string
  onCursorImagePosition?: (position: { x: number; y: number } | null) => void
  onContainerSize?: (size: { width: number; height: number }) => void
}

export function ImageStage({
  imageSize,
  viewport,
  onViewportChange,
  children,
  overlay,
  overlayInteractive,
  label,
  onCursorImagePosition,
  onContainerSize,
}: ImageStageProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect()
      setSize({ width: rect.width, height: rect.height })
      onContainerSize?.({ width: rect.width, height: rect.height })
    })
    ro.observe(el)
    const rect = el.getBoundingClientRect()
    setSize({ width: rect.width, height: rect.height })
    onContainerSize?.({ width: rect.width, height: rect.height })
    if (viewport.scale === 1 && viewport.tx === 0 && viewport.ty === 0) {
      onViewportChange(fitViewport(rect.width, rect.height, imageSize))
    }
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleWheel(e: WheelEvent<HTMLDivElement>) {
    e.preventDefault()
    const rect = containerRef.current!.getBoundingClientRect()
    onViewportChange(zoomAt(viewport, e.clientX - rect.left, e.clientY - rect.top, e.deltaY))
  }

  function handlePointerDown(e: PointerEvent<HTMLDivElement>) {
    dragging.current = true
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }

  function handlePointerMove(e: PointerEvent<HTMLDivElement>) {
    if (dragging.current) {
      onViewportChange(panBy(viewport, e.movementX, e.movementY))
    }
    if (onCursorImagePosition) {
      const rect = containerRef.current!.getBoundingClientRect()
      onCursorImagePosition(screenToImage(viewport, e.clientX - rect.left, e.clientY - rect.top))
    }
  }

  function handlePointerUp(e: PointerEvent<HTMLDivElement>) {
    dragging.current = false
    ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
  }

  function handlePointerLeave() {
    onCursorImagePosition?.(null)
  }

  return (
    <div
      ref={containerRef}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerLeave}
      className="relative h-full w-full touch-none overflow-hidden bg-surface-dark"
      aria-label={label}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: imageSize,
          height: imageSize,
          transform: `translate(${viewport.tx}px, ${viewport.ty}px) scale(${viewport.scale})`,
          transformOrigin: '0 0',
        }}
      >
        {children}
      </div>
      {overlay && size.width > 0 && (
        <div className={clsx('absolute inset-0', overlayInteractive ? 'pointer-events-auto' : 'pointer-events-none')}>
          {overlay(size.width, size.height)}
        </div>
      )}
    </div>
  )
}

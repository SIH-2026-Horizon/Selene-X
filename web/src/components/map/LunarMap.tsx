import { useEffect, useRef } from 'react'
import Map from 'ol/Map'
import View from 'ol/View'
import Graticule from 'ol/layer/Graticule'
import Stroke from 'ol/style/Stroke'
import type MapBrowserEvent from 'ol/MapBrowserEvent'
import { createEmpty, extendCoordinate, isEmpty as isEmptyExtent } from 'ol/extent'
import { ensureMoonProjectionRegistered, MOON_PROJECTION } from './moonProjection'
import { createFootprintLayer, FOOTPRINT_LAYER_ID } from './footprintLayer'
import { createCraterPointLayer, CRATER_POINT_LAYER_ID, type CraterMapPoint } from './craterPointLayer'
import type { Product } from '@/types/product'

import 'ol/ol.css'

ensureMoonProjectionRegistered()

interface LunarMapProps {
  products?: Product[]
  selectedProductId?: string | null
  onSelectProduct?: (productId: string) => void
  craterPoints?: CraterMapPoint[]
  selectedCraterId?: string | null
  onSelectCrater?: (craterId: string) => void
  center?: [number, number]
  zoom?: number
  className?: string
}

export function LunarMap({
  products = [],
  selectedProductId,
  onSelectProduct,
  craterPoints = [],
  selectedCraterId,
  onSelectCrater,
  center = [0, 0],
  zoom = 3,
  className,
}: LunarMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<Map | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const graticule = new Graticule({
      strokeStyle: new Stroke({ color: 'rgba(32,29,29,0.18)', width: 1, lineDash: [2, 4] }),
      showLabels: false,
    })

    const map = new Map({
      target: containerRef.current,
      layers: [graticule],
      view: new View({
        projection: MOON_PROJECTION,
        center,
        zoom,
        minZoom: 1,
        maxZoom: 12,
      }),
      controls: [],
    })
    mapRef.current = map

    // Flex/grid parents can finish laying out after this measurement, leaving OL's
    // canvas sized to a stale container rect unless it's told to re-measure.
    const resizeObserver = new ResizeObserver(() => map.updateSize())
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      map.setTarget(undefined)
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Products/footprints: on first load, fit the view to every footprint so a fresh
  // result set is visible at a glance. Once that's happened, a later change to
  // selectedProductId (the user picking a different row) instead flies to just that
  // one footprint — these two behaviors must not both fire for the same selection,
  // or the fly-to always wins and the initial overview is never seen.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const existing = map.getLayers().getArray().find((l) => l.get('id') === FOOTPRINT_LAYER_ID)
    if (existing) map.removeLayer(existing)
    const footprintLayer = createFootprintLayer(products, selectedProductId)
    map.addLayer(footprintLayer)

    const alreadyFitted = map.get('hasAutoFit') as boolean | undefined

    if (!alreadyFitted && products.length > 0) {
      const extent = footprintLayer.getSource()?.getExtent() ?? createEmpty()
      if (!isEmptyExtent(extent)) {
        map.updateSize()
        map.getView().fit(extent, { padding: [40, 40, 40, 40], maxZoom: 6, duration: 0 })
        map.set('hasAutoFit', true)
      }
    } else if (alreadyFitted && selectedProductId) {
      const selectedFeature = footprintLayer.getSource()?.getFeatureById(selectedProductId)
      const extent = selectedFeature?.getGeometry()?.getExtent() ?? createEmpty()
      if (!isEmptyExtent(extent)) {
        map.getView().fit(extent, { padding: [100, 100, 100, 100], maxZoom: 9, duration: 300 })
      }
    }
  }, [products, selectedProductId])

  // Same pairing for crater points — see the comment above.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const existing = map.getLayers().getArray().find((l) => l.get('id') === CRATER_POINT_LAYER_ID)
    if (existing) map.removeLayer(existing)
    map.addLayer(createCraterPointLayer(craterPoints, selectedCraterId))

    const alreadyFitted = map.get('hasAutoFit') as boolean | undefined

    if (!alreadyFitted && craterPoints.length > 0) {
      const extent = createEmpty()
      for (const point of craterPoints) extendCoordinate(extent, [point.location.lon, point.location.lat])
      if (!isEmptyExtent(extent)) {
        map.updateSize()
        map.getView().fit(extent, { padding: [60, 60, 60, 60], maxZoom: 6, duration: 0 })
        map.set('hasAutoFit', true)
      }
    } else if (alreadyFitted && selectedCraterId) {
      const point = craterPoints.find((p) => p.id === selectedCraterId)
      if (point) {
        const view = map.getView()
        view.animate({
          center: [point.location.lon, point.location.lat],
          zoom: Math.max(view.getZoom() ?? 3, 6),
          duration: 300,
        })
      }
    }
  }, [craterPoints, selectedCraterId])

  useEffect(() => {
    const map = mapRef.current
    if (!map || (!onSelectProduct && !onSelectCrater)) return
    const handler = (event: MapBrowserEvent) => {
      const feature = map.forEachFeatureAtPixel(event.pixel, (f) => f)
      const id = feature?.getId()
      const kind = feature?.get('kind')
      if (typeof id !== 'string') return
      if (kind === 'product') onSelectProduct?.(id)
      if (kind === 'crater') onSelectCrater?.(id)
    }
    map.on('click', handler)
    return () => {
      map.un('click', handler)
    }
  }, [onSelectProduct, onSelectCrater])

  return (
    <div
      ref={containerRef}
      role="application"
      aria-label="Lunar map"
      className={className}
      style={{ background: '#8f8f8f' }}
    />
  )
}

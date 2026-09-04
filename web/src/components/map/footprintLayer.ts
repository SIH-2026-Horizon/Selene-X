import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import Feature from 'ol/Feature'
import Style from 'ol/style/Style'
import Stroke from 'ol/style/Stroke'
import Fill from 'ol/style/Fill'
import GeoJSON from 'ol/format/GeoJSON'
import type { Product } from '@/types/product'
import { MOON_PROJECTION } from './moonProjection'

export const FOOTPRINT_LAYER_ID = 'footprint-layer'

/** The current map is only a selenographic plate-carrée map. Unknown persisted
 * CRSs must not be drawn as though they used that coordinate system. */
export function supportsLunarFootprint(product: Product): boolean {
  return product.footprintCrs === MOON_PROJECTION.getCode() && product.footprintSrid === null
}

export function createFootprintLayer(products: Product[], selectedProductId?: string | null) {
  const source = new VectorSource()

  const format = new GeoJSON()
  for (const product of products) {
    if (!product.footprintGeojson || !supportsLunarFootprint(product)) continue
    let feature: Feature | null = null
    try {
      const parsed = format.readFeature(product.footprintGeojson, { dataProjection: MOON_PROJECTION, featureProjection: MOON_PROJECTION })
      const geometryType = !Array.isArray(parsed) ? parsed.getGeometry()?.getType() : undefined
      if (!Array.isArray(parsed) && (geometryType === 'Polygon' || geometryType === 'MultiPolygon')) feature = parsed
    } catch {
      // Invalid persisted GeoJSON is not rendered as an estimated footprint.
    }
    if (!feature) continue
    feature.setId(product.id)
    feature.set('kind', 'product')
    source.addFeature(feature)
  }

  const layer = new VectorLayer({
    source,
    style: (feature) => {
      const isSelected = feature.getId() === selectedProductId
      return new Style({
        stroke: new Stroke({
          color: isSelected ? '#007aff' : '#201d1d',
          width: isSelected ? 2 : 1,
        }),
        fill: new Fill({
          color: isSelected ? 'rgba(0,122,255,0.12)' : 'rgba(32,29,29,0.04)',
        }),
      })
    },
  })
  layer.set('id', FOOTPRINT_LAYER_ID)
  return layer
}

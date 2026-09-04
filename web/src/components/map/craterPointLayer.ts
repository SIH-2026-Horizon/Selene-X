import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import Feature from 'ol/Feature'
import Point from 'ol/geom/Point'
import Style from 'ol/style/Style'
import CircleStyle from 'ol/style/Circle'
import Stroke from 'ol/style/Stroke'
import Fill from 'ol/style/Fill'
export interface LonLat {
  lon: number
  lat: number
}

export const CRATER_POINT_LAYER_ID = 'crater-point-layer'

export interface CraterMapPoint {
  id: string
  label: string
  location: LonLat
}

export function createCraterPointLayer(points: CraterMapPoint[], selectedId?: string | null) {
  const source = new VectorSource()

  for (const point of points) {
    const feature = new Feature({ geometry: new Point([point.location.lon, point.location.lat]) })
    feature.setId(point.id)
    feature.set('kind', 'crater')
    source.addFeature(feature)
  }

  const layer = new VectorLayer({
    source,
    style: (feature) => {
      const isSelected = feature.getId() === selectedId
      return new Style({
        image: new CircleStyle({
          radius: isSelected ? 7 : 5,
          fill: new Fill({ color: isSelected ? '#007aff' : '#f1eeee' }),
          stroke: new Stroke({ color: '#201d1d', width: 1.5 }),
        }),
      })
    },
  })
  layer.set('id', CRATER_POINT_LAYER_ID)
  return layer
}

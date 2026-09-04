import { Projection, addProjection, addCoordinateTransforms, get as getProjection } from 'ol/proj'

/** A flat plate-carrée projection over selenographic lon/lat — there is no Earth
 * basemap here, so coordinates are used directly rather than reprojected. */
export const MOON_PROJECTION = new Projection({
  code: 'MOON:PLATE_CARREE',
  units: 'degrees',
  extent: [-180, -90, 180, 90],
  worldExtent: [-180, -90, 180, 90],
})

let registered = false
export function ensureMoonProjectionRegistered() {
  if (!registered) {
    addProjection(MOON_PROJECTION)
    // Graticule and other OL internals expect a real transform to/from EPSG:4326.
    // There is no actual reprojection here — lon/lat is used as-is — so the
    // transform is the identity function.
    const identity = (coord: number[]) => coord
    const wgs84 = getProjection('EPSG:4326')
    if (wgs84) {
      addCoordinateTransforms(wgs84, MOON_PROJECTION, identity, identity)
    }
    registered = true
  }
}

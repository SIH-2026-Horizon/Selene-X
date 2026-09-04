import type { JsonDocument } from '@/services/api/contracts'

export type Payload = string
export type ReferenceSource = string

/** Persisted product metadata. Fields not supplied by storage are deliberately absent. */
export interface Product {
  id: string
  productIdentity: string
  payloadType: string
  payloadMetadata: JsonDocument
  validationState: string
  validationDetails: JsonDocument
  manifestSha256: string
  quarantineReason: string | null
  footprintGeojson: JsonDocument | null
  footprintCrs: string | null
  footprintSrid: number | null
  createdAt: string
}

/** TypeScript mirror of the versioned persisted-state API response documents. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type JsonDocument = { [key: string]: JsonValue }

export interface CursorPage<T> {
  items: T[]
  next_cursor: string | null
}

export interface ApiProduct {
  id: string
  owner_subject_id: string
  product_identity: string
  payload_type: string
  payload_metadata: JsonDocument
  validation_state: string
  validation_details: JsonDocument
  manifest_sha256: string
  quarantine_reason: string | null
  footprint_geojson: JsonDocument | null
  footprint_crs: string | null
  footprint_srid: number | null
  created_at: string
}

export interface ApiRun {
  id: string
  owner_subject_id: string
  source_product_id: string
  reference_product_id: string
  parameter_manifest: JsonDocument | null
  parameter_manifest_available: boolean
  parameters_sha256: string
  algorithm_versions: JsonDocument
  model_versions: JsonDocument
  execution_state: string
  state_version: number
  event_sequence: number
  computed_verdict: string | null
  effective_disposition: string
  code_revision: string
  environment_fingerprint: string
  created_at: string
  updated_at: string
}

export interface ApiStage {
  id: string
  run_id: string
  stage_name: string
  stage_ordinal: number
  attempt: number
  execution_state: string
  input_sha256: string | null
  output_sha256: string | null
  lease_holder: string | null
  lease_expires_at: string | null
  warning_document: JsonDocument | null
  failure_document: JsonDocument | null
  completed_at: string | null
  atomic_completion_marker: string | null
  created_at: string
}

export interface ApiArtifact {
  id: string
  run_id: string
  run_stage_id: string | null
  kind: string
  storage_uri: string
  media_type: string
  byte_size: number
  sha256: string
  schema_uri: string | null
  crs_metadata: JsonDocument | null
  validation_document: JsonDocument
  publication_state: string
  validated_at: string
  published_at: string
  created_at: string
}

export interface ApiMetric {
  id: string
  run_id: string
  report_kind: string
  report_version: string
  report_document: JsonDocument
  indexed_fields: JsonDocument
  computed_verdict: string | null
  created_at: string
}

export interface ApiRunEvent {
  id: string
  run_id: string
  actor_subject_id: string | null
  event_type: string
  execution_state: string | null
  sequence: number
  event_document: JsonDocument
  recorded_at: string
}

export interface ApiReview {
  id: string
  run_id: string
  actor_subject_id: string
  decision: string
  reason_code: string
  note: string | null
  source_computed_verdict: string | null
  recorded_at: string
}

export interface ApiKnowledgeEntity {
  id: string
  created_by_subject_id: string
  entity_type: string
  external_id: string | null
  label: string
  properties: JsonDocument
  location_geojson: JsonDocument | null
  location_crs: string | null
  location_srid: number | null
  created_at: string
}

export interface ApiKnowledgeEdge {
  id: string
  created_by_subject_id: string
  source_entity_id: string
  target_entity_id: string
  relation_type: string
  properties: JsonDocument
  weight: number | null
  created_at: string
}

export interface ApiSemanticGraph {
  nodes: ApiKnowledgeEntity[]
  edges: ApiKnowledgeEdge[]
  next_cursor: string | null
  edges_truncated: boolean
  relationship_expansions: Array<{
    entity_id: string
    neighbors_path: string
  }>
}

export interface ApiRegistrationGraphNode {
  id: string
  type: string
  label: string
  attributes: JsonDocument
}

export interface ApiRegistrationGraphEdge {
  id: string
  source: string
  target: string
  relation: string
  weight: number | null
}

export interface ApiRegistrationGraph {
  nodes: ApiRegistrationGraphNode[]
  edges: ApiRegistrationGraphEdge[]
  next_cursor: string | null
  child_collections_truncated: Array<{
    collection: 'stages' | 'artifacts' | 'metrics' | 'reviews'
    limit: number
  }>
}

export interface ApiSessionUser {
  username: string
  display_name: string
  role: 'analyst' | 'reviewer' | 'admin'
}

export interface ApiProfileUpdate {
  display_name?: string
  current_password?: string
  new_password?: string
}

export interface ApiUserAccount {
  id: string
  username: string
  display_name: string
  role: 'analyst' | 'reviewer' | 'admin'
  is_active: boolean
}

export interface ApiUserAccountPage {
  items: ApiUserAccount[]
}

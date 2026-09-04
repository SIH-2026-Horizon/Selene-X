"""Pydantic contracts for the persisted v1 REST API."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

_SHA256 = r"^[0-9a-f]{64}$"
Sha256 = Annotated[str, Field(pattern=_SHA256)]
_FORBIDDEN_METADATA_PATH_KEYS = frozenset(
    {
        "file_path",
        "filepath",
        "filesystem_path",
        "local_path",
        "path",
        "server_path",
        "source_path",
    }
)


def _reject_server_paths(value: object) -> None:
    """Reject server-local filesystem locations anywhere in supplied metadata."""

    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            if normalized_key in _FORBIDDEN_METADATA_PATH_KEYS:
                raise ValueError("server filesystem paths are not accepted")
            _reject_server_paths(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _reject_server_paths(nested_value)
    elif isinstance(value, str) and value.casefold().startswith("file://"):
        raise ValueError("server filesystem paths are not accepted")


class ProductCreateRequest(BaseModel):
    """Durable metadata supplied after product validation has already occurred."""

    model_config = ConfigDict(extra="forbid")

    product_identity: str = Field(min_length=1, max_length=512)
    payload_type: str = Field(min_length=1, max_length=64)
    payload_metadata: dict[str, JsonValue]
    validation_state: str = Field(min_length=1, max_length=32)
    validation_details: dict[str, JsonValue]
    manifest_sha256: Sha256
    quarantine_reason: str | None = Field(default=None, max_length=10_000)
    footprint_geojson: dict[str, JsonValue] | None = None
    footprint_crs: str | None = Field(default=None, max_length=20_000)
    footprint_srid: int | None = None

    @field_validator("payload_metadata", "validation_details")
    @classmethod
    def no_server_filesystem_metadata(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        _reject_server_paths(value)
        return value

    @model_validator(mode="after")
    def footprint_has_explicit_lunar_crs(self) -> ProductCreateRequest:
        if self.footprint_geojson is not None and not self.footprint_crs:
            raise ValueError("footprint_crs is required when footprint_geojson is supplied")
        if self.footprint_geojson is None and (
            self.footprint_crs is not None or self.footprint_srid is not None
        ):
            raise ValueError("footprint_geojson is required with footprint CRS metadata")
        return self


class ProductResponse(BaseModel):
    """Persisted product metadata; no server paths or preprocessing fiction."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_subject_id: UUID
    product_identity: str
    payload_type: str
    payload_metadata: dict[str, JsonValue]
    validation_state: str
    validation_details: dict[str, JsonValue]
    manifest_sha256: str
    quarantine_reason: str | None
    footprint_geojson: dict[str, JsonValue] | None
    footprint_crs: str | None
    footprint_srid: int | None
    created_at: datetime


class ProductPageResponse(BaseModel):
    """Cursor-paginated persisted catalog records."""

    model_config = ConfigDict(frozen=True)

    items: list[ProductResponse]
    next_cursor: str | None


class RunCreateRequest(BaseModel):
    """A complete immutable execution definition, not a request to do science."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_product_id: UUID
    reference_product_id: UUID
    parameter_manifest: dict[str, JsonValue] = Field(
        min_length=1,
        validation_alias=AliasChoices("parameter_manifest", "parameters"),
    )
    parameters_sha256: Sha256 | None = None
    algorithm_versions: dict[str, JsonValue] = Field(min_length=1)
    model_versions: dict[str, JsonValue] = Field(default_factory=dict)
    code_revision: str = Field(min_length=1, max_length=128)
    environment_fingerprint: str = Field(min_length=1, max_length=128)

    @field_validator("parameter_manifest", "algorithm_versions", "model_versions")
    @classmethod
    def no_server_paths_in_frozen_documents(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        _reject_server_paths(value)
        return value


class RunResponse(BaseModel):
    """Truthful persisted state for a requested scientific run."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_subject_id: UUID
    source_product_id: UUID
    reference_product_id: UUID
    parameter_manifest: dict[str, JsonValue] | None
    parameter_manifest_available: bool
    parameters_sha256: str
    algorithm_versions: dict[str, JsonValue]
    model_versions: dict[str, JsonValue]
    execution_state: str
    state_version: int
    event_sequence: int
    computed_verdict: str | None
    effective_disposition: str
    code_revision: str
    environment_fingerprint: str
    created_at: datetime
    updated_at: datetime


class RunPageResponse(BaseModel):
    """Cursor-paginated persisted runs."""

    model_config = ConfigDict(frozen=True)

    items: list[RunResponse]
    next_cursor: str | None


class StageResponse(BaseModel):
    """A persisted stage attempt, if a trusted runner wrote one."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    stage_name: str
    stage_ordinal: int
    attempt: int
    execution_state: str
    input_sha256: str | None
    output_sha256: str | None
    lease_holder: str | None
    lease_expires_at: datetime | None
    warning_document: dict[str, JsonValue] | None
    failure_document: dict[str, JsonValue] | None
    completed_at: datetime | None
    atomic_completion_marker: str | None
    created_at: datetime


class StagePageResponse(BaseModel):
    """Cursor-paginated persisted stage attempts."""

    model_config = ConfigDict(frozen=True)

    items: list[StageResponse]
    next_cursor: str | None


class ArtifactResponse(BaseModel):
    """A persisted, already-published external artifact record."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    run_stage_id: UUID | None
    kind: str
    storage_uri: str
    media_type: str
    byte_size: int
    sha256: str
    schema_uri: str | None
    crs_metadata: dict[str, JsonValue] | None
    validation_document: dict[str, JsonValue]
    publication_state: str
    validated_at: datetime
    published_at: datetime
    created_at: datetime


class ArtifactPageResponse(BaseModel):
    """Cursor-paginated persisted artifact records."""

    model_config = ConfigDict(frozen=True)

    items: list[ArtifactResponse]
    next_cursor: str | None


class MetricResponse(BaseModel):
    """A persisted metric report, never a fabricated visualisation payload."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    report_kind: str
    report_version: str
    report_document: dict[str, JsonValue]
    indexed_fields: dict[str, JsonValue]
    computed_verdict: str | None
    created_at: datetime


class MetricPageResponse(BaseModel):
    """Cursor-paginated persisted metric reports."""

    model_config = ConfigDict(frozen=True)

    items: list[MetricResponse]
    next_cursor: str | None


class RunEventResponse(BaseModel):
    """An append-only lifecycle or provenance event."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    actor_subject_id: UUID | None
    event_type: str
    execution_state: str | None
    sequence: int
    event_document: dict[str, JsonValue]
    recorded_at: datetime


class RunEventPageResponse(BaseModel):
    """Cursor-paginated append-only event history."""

    model_config = ConfigDict(frozen=True)

    items: list[RunEventResponse]
    next_cursor: str | None


class ReviewCreateRequest(BaseModel):
    """Immutable human disposition for a run's independently-computed verdict."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    reason_code: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def rejected_reviews_need_an_explanation(self) -> ReviewCreateRequest:
        if self.decision == "rejected" and not (self.note and self.note.strip()):
            raise ValueError("a rejected review requires an explanatory note")
        return self


class ReviewResponse(BaseModel):
    """An immutable review history entry."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    actor_subject_id: UUID
    decision: str
    reason_code: str
    note: str | None
    source_computed_verdict: str | None
    recorded_at: datetime


class ReviewPageResponse(BaseModel):
    """Cursor-paginated immutable review history."""

    model_config = ConfigDict(frozen=True)

    items: list[ReviewResponse]
    next_cursor: str | None


class GraphNodeResponse(BaseModel):
    """One stable provenance graph node derived from a durable record."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    label: str
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class GraphEdgeResponse(BaseModel):
    """One stable provenance relationship derived from a real foreign key."""

    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    target: str
    relation: str
    weight: float | None = None


class GraphCollectionTruncationResponse(BaseModel):
    """One bounded provenance child collection in a graph projection."""

    model_config = ConfigDict(frozen=True)

    collection: Literal["stages", "artifacts", "metrics", "reviews"]
    limit: int = Field(ge=1)


class KnowledgeGraphResponse(BaseModel):
    """Cursor-paginated, DB-derived provenance graph projection.

    The cursor advances root runs. Child stage, artifact, metric, and review
    expansions are each bounded to the requested page limit. When
    ``child_collections_truncated`` is nonempty, the graph is a partial
    projection and the named run-detail collection must be paged separately.
    """

    model_config = ConfigDict(frozen=True)

    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    next_cursor: str | None
    child_collections_truncated: list[GraphCollectionTruncationResponse] = Field(
        default_factory=list
    )


class KnowledgeEntityCreateRequest(BaseModel):
    """An explicit semantic entity supplied by an operator or trusted importer."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=64)
    external_id: str | None = Field(default=None, min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=512)
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    location_geojson: dict[str, JsonValue] | None = None
    location_crs: str | None = Field(default=None, max_length=20_000)
    location_srid: int | None = None

    @field_validator("properties")
    @classmethod
    def no_server_paths_in_properties(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        _reject_server_paths(value)
        return value

    @model_validator(mode="after")
    def location_has_explicit_lunar_crs(self) -> KnowledgeEntityCreateRequest:
        if self.location_geojson is not None and not self.location_crs:
            raise ValueError("location_crs is required when location_geojson is supplied")
        if self.location_geojson is None and (
            self.location_crs is not None or self.location_srid is not None
        ):
            raise ValueError("location_geojson is required with location CRS metadata")
        return self


class KnowledgeEntityResponse(BaseModel):
    """A real stored semantic node with an optional explicitly declared location."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    created_by_subject_id: UUID
    entity_type: str
    external_id: str | None
    label: str
    properties: dict[str, JsonValue]
    location_geojson: dict[str, JsonValue] | None
    location_crs: str | None
    location_srid: int | None
    created_at: datetime


class KnowledgeEntityPageResponse(BaseModel):
    """Cursor-paginated semantic entity rows."""

    model_config = ConfigDict(frozen=True)

    items: list[KnowledgeEntityResponse]
    next_cursor: str | None


class KnowledgeEdgeCreateRequest(BaseModel):
    """A directed relationship between two already persisted semantic entities."""

    model_config = ConfigDict(extra="forbid")

    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str = Field(min_length=1, max_length=128)
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    weight: float | None = None

    @field_validator("properties")
    @classmethod
    def no_server_paths_in_edge_properties(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        _reject_server_paths(value)
        return value

    @field_validator("weight")
    @classmethod
    def finite_weight(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("weight must be finite when supplied")
        return value


class KnowledgeEdgeResponse(BaseModel):
    """A real stored semantic edge; weight is present only when persisted."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    created_by_subject_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str
    properties: dict[str, JsonValue]
    weight: float | None
    created_at: datetime


class KnowledgeEdgePageResponse(BaseModel):
    """Cursor-paginated semantic relationship rows."""

    model_config = ConfigDict(frozen=True)

    items: list[KnowledgeEdgeResponse]
    next_cursor: str | None


class SemanticRelationshipExpansionResponse(BaseModel):
    """A reachable per-entity relationship continuation for a bounded query."""

    model_config = ConfigDict(frozen=True)

    entity_id: UUID
    neighbors_path: str


class SemanticKnowledgeGraphResponse(BaseModel):
    """A bounded semantic graph projection with no dangling edge endpoints.

    ``next_cursor`` advances only the requested root entity page. For a
    requested ``limit``, at most that many root entities and incident edges
    are returned, plus their endpoint entities. ``edges_truncated`` means
    some incident edges were not included in this root page; each entry in
    ``relationship_expansions`` names a paginatable neighbor endpoint that
    can retrieve those stored relationships without claiming completeness.
    """

    model_config = ConfigDict(frozen=True)

    nodes: list[KnowledgeEntityResponse]
    edges: list[KnowledgeEdgeResponse]
    next_cursor: str | None
    edges_truncated: bool = False
    relationship_expansions: list[SemanticRelationshipExpansionResponse] = Field(
        default_factory=list
    )


class LoginRequest(BaseModel):
    """Operator-supplied login credentials."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class SessionUserResponse(BaseModel):
    """The logged-in operator's public identity — never the password hash."""

    model_config = ConfigDict(frozen=True)

    username: str
    display_name: str
    role: Literal["analyst", "reviewer", "admin"]


class ProfileUpdateRequest(BaseModel):
    """A session operator's own editable profile fields.

    Roles deliberately do not appear here.  They are an administrative
    control assigned to a different account by an Admin, never a preference
    that the current user can change for themself.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    current_password: str | None = Field(default=None, min_length=1, max_length=512)
    new_password: str | None = Field(default=None, min_length=8, max_length=512)

    @field_validator("display_name")
    @classmethod
    def display_name_is_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name must not be blank")
        return normalized

    @model_validator(mode="after")
    def contains_a_complete_profile_change(self) -> ProfileUpdateRequest:
        if self.display_name is None and self.new_password is None:
            raise ValueError("provide display_name or new_password")
        if self.new_password is not None and self.current_password is None:
            raise ValueError("current_password is required when changing password")
        if self.current_password is not None and self.new_password is None:
            raise ValueError("new_password is required when supplying current_password")
        return self


class UserAccountCreateRequest(BaseModel):
    """Admin-supplied definition of a new operator account."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=512)
    role: Literal["analyst", "reviewer", "admin"]
    display_name: str = Field(min_length=1, max_length=255)


class UserAccountResponse(BaseModel):
    """Public operator-account view — never the password hash."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    username: str
    display_name: str
    role: Literal["analyst", "reviewer", "admin"]
    is_active: bool


class UserAccountPageResponse(BaseModel):
    """The full operator-account roster — small enough to never need paging."""

    model_config = ConfigDict(frozen=True)

    items: list[UserAccountResponse]


class UserAccountUpdateRequest(BaseModel):
    """Partial admin update to an account's role, activity, or password.

    A role change may only target a different account; activity and
    password changes may also be self-targeted (see
    ``auth_services.update_user_account``).
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["analyst", "reviewer", "admin"] | None = None
    is_active: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=512)

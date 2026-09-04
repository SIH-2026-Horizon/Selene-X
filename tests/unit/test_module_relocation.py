"""Tests proving the pipeline-layering fix relocated symbols cleanly.

Covers two things:

* The `selene_core.pipeline.failures`/`selene_core.pipeline.hashing`/
  `selene_core.pipeline.results._Contract` re-export shims are genuine
  re-exports of the new bottom-layer canonical modules
  (`selene_core.errors`, `selene_core.hashing`, `selene_core.contracts`) —
  identity, not just equality, so a duplicate/drifted redefinition would
  fail these tests.
* The six import sites that previously violated the `core-layers`
  import-linter contract (`selene_core.ingest.pds4`,
  `selene_core.ingest.pvl`, `selene_core.ingest.payload_adapter`,
  `selene_core.match.protocol`, `selene_core.match.correspondence`) still
  work end to end against the relocated symbols.
"""

from __future__ import annotations

import pytest

from selene_core import contracts as contracts_module
from selene_core import errors as errors_module
from selene_core import hashing as hashing_module
from selene_core.ingest.payload_adapter import (
    OhrcAdapter,
    PayloadFamily,
    QuarantineRecord,
    validate_product,
)
from selene_core.ingest.pds4 import Pds4ParseError, parse_pds4_label
from selene_core.ingest.pvl import PvlParseError, parse_pvl_label
from selene_core.match import protocol as protocol_module
from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.pipeline import failures as pipeline_failures
from selene_core.pipeline import hashing as pipeline_hashing
from selene_core.pipeline import results as pipeline_results
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_VALID_SHA256 = "a" * 64
_VALID_SHA256_B = "b" * 64
_VALID_SHA256_C = "c" * 64

# A minimal, well-formed (non-hostile) PDS4 XML label.
_VALID_PDS4_LABEL = b'<?xml version="1.0"?><Product_Observational><a/></Product_Observational>'

# Genuinely malformed, non-hostile XML: mismatched tag, no DOCTYPE/entity
# markers, so it fails during parsing rather than at the hostile-pattern
# pre-scan.
_MALFORMED_PDS4_LABEL = b"<a><b></a>"

# Malformed, non-hostile PVL: an unterminated group.
_MALFORMED_PVL_LABEL = b"Group = Instrument\nInstrumentId = OHRC\n"


class TestFailuresShimIsGenuineReexport:
    """`selene_core.pipeline.failures` re-exports `selene_core.errors`."""

    def test_failure_code_identity(self) -> None:
        assert pipeline_failures.FailureCode is errors_module.FailureCode

    def test_failure_category_identity(self) -> None:
        assert pipeline_failures.FailureCategory is errors_module.FailureCategory

    def test_failure_definition_identity(self) -> None:
        assert pipeline_failures.FailureDefinition is errors_module.FailureDefinition

    def test_definition_for_identity(self) -> None:
        assert pipeline_failures.definition_for is errors_module.definition_for

    def test_is_retryable_identity(self) -> None:
        assert pipeline_failures.is_retryable is errors_module.is_retryable


class TestHashingShimIsGenuineReexport:
    """`selene_core.pipeline.hashing` re-exports `selene_core.hashing`."""

    def test_digest_json_identity(self) -> None:
        assert pipeline_hashing.digest_json is hashing_module.digest_json

    def test_is_sha256_identity(self) -> None:
        assert pipeline_hashing.is_sha256 is hashing_module.is_sha256

    def test_digest_file_identity(self) -> None:
        assert pipeline_hashing.digest_file is hashing_module.digest_file

    def test_digest_many_identity(self) -> None:
        assert pipeline_hashing.digest_many is hashing_module.digest_many

    def test_canonical_json_identity(self) -> None:
        assert pipeline_hashing.canonical_json is hashing_module.canonical_json

    def test_empty_digest_identity(self) -> None:
        assert pipeline_hashing.EMPTY_DIGEST == hashing_module.EMPTY_DIGEST


class TestContractAliasIsGenuineReexport:
    """`pipeline.results._Contract` is the shared `selene_core.contracts.Contract`."""

    def test_contract_identity(self) -> None:
        assert pipeline_results._Contract is contracts_module.Contract


class TestIngestModulesUseRelocatedFailureCode:
    """`ingest.pds4`/`ingest.pvl`/`ingest.payload_adapter` use `selene_core.errors`."""

    def test_parse_pds4_label_succeeds_on_valid_fixture(self) -> None:
        root = parse_pds4_label(_VALID_PDS4_LABEL)
        assert root.tag == "Product_Observational"

    def test_parse_pds4_label_raises_canonical_failure_code(self) -> None:
        with pytest.raises(Pds4ParseError) as excinfo:
            parse_pds4_label(_MALFORMED_PDS4_LABEL)
        assert excinfo.value.code is errors_module.FailureCode.INPUT_LABEL_UNPARSEABLE

    def test_parse_pvl_label_raises_canonical_failure_code(self) -> None:
        with pytest.raises(PvlParseError) as excinfo:
            parse_pvl_label(_MALFORMED_PVL_LABEL)
        assert excinfo.value.code is errors_module.FailureCode.INPUT_LABEL_UNPARSEABLE

    def test_payload_adapter_quarantine_uses_canonical_failure_code(self) -> None:
        record = validate_product(OhrcAdapter(), _MALFORMED_PDS4_LABEL)
        assert isinstance(record, QuarantineRecord)
        assert record.payload_family is PayloadFamily.OHRC
        assert record.reason is errors_module.FailureCode.INPUT_LABEL_UNPARSEABLE


class TestMatchModulesUseRelocatedHashingAndContract:
    """`match.correspondence`/`match.protocol` use `selene_core.hashing`/`.contracts`."""

    def test_correspondence_record_base_is_canonical_contract(self) -> None:
        assert CorrespondenceRecord.__mro__[1] is contracts_module.Contract

    def test_correspondence_record_construction_end_to_end(self) -> None:
        record = CorrespondenceRecord(
            job_id="job-1",
            algorithm="phase_correlation",
            algorithm_version="1.0",
            source_pixel=SourcePixel(line=10.0, sample=20.0),
            reference_pixel=ReferencePixel(line=11.0, sample=21.0),
            raw_score=0.9,
            selected_for_coverage=False,
            input_digest=_VALID_SHA256,
            reference_digest=_VALID_SHA256_B,
            parameter_set_digest=_VALID_SHA256_C,
        )
        assert record.job_id == "job-1"
        assert record.input_digest == _VALID_SHA256

    def test_match_prior_construction_end_to_end(self) -> None:
        prior = protocol_module.MatchPrior(
            displacement_px=(1.5, -2.0),
            displacement_uncertainty_px=(0.5, 0.5),
            search_radius_px=10.0,
        )
        assert prior.search_radius_px == 10.0
        assert prior.displacement_px == (1.5, -2.0)

"""Tests for failure taxonomy and codes.

Covers FailureCategory, FailureCode, FailureDefinition, definition_for, and
is_retryable.
"""

import pytest

from selene_core.pipeline.failures import (
    FailureCategory,
    FailureCode,
    FailureDefinition,
    definition_for,
    is_retryable,
)

pytestmark = pytest.mark.unit


class TestFailureCategory:
    """Tests for FailureCategory enum."""

    def test_failure_category_values_are_strings(self) -> None:
        """FailureCategory members are StrEnum with string values."""
        assert isinstance(FailureCategory.INPUT.value, str)
        assert FailureCategory.INPUT.value == "input"

    def test_failure_category_all_members_defined(self) -> None:
        """All FailureCategory members exist."""
        categories = [
            FailureCategory.INPUT,
            FailureCategory.REFERENCE,
            FailureCategory.GEOMETRY,
            FailureCategory.MATCHING,
            FailureCategory.REFINEMENT,
            FailureCategory.COVERAGE,
            FailureCategory.ADJUSTMENT,
            FailureCategory.PRODUCT,
            FailureCategory.VALIDATION,
            FailureCategory.RESOURCE,
            FailureCategory.INTERNAL,
        ]
        assert len(categories) == 11


class TestFailureCodeDefinitions:
    """Tests for FailureCode and definitions."""

    def test_every_failure_code_has_definition(self) -> None:
        """Every FailureCode member has a definition_for entry."""
        for code in FailureCode:
            definition = definition_for(code)
            assert definition is not None
            assert definition.code == code

    def test_definition_for_returns_failure_definition(self) -> None:
        """definition_for returns a FailureDefinition instance."""
        code = FailureCode.INPUT_MISSING_FILE
        definition = definition_for(code)
        assert isinstance(definition, FailureDefinition)

    def test_failure_definition_fields_non_empty(self) -> None:
        """FailureDefinition has required non-empty fields for all codes."""
        for code in FailureCode:
            definition = definition_for(code)
            assert definition.code == code
            assert isinstance(definition.category, FailureCategory)
            assert len(definition.summary) > 0
            assert len(definition.remediation) > 0
            assert isinstance(definition.retryable, bool)

    def test_input_code_has_input_category(self) -> None:
        """INPUT codes have INPUT category."""
        code = FailureCode.INPUT_MISSING_FILE
        definition = definition_for(code)
        assert definition.category == FailureCategory.INPUT

    def test_product_code_has_product_category(self) -> None:
        """PRODUCT codes have PRODUCT category."""
        code = FailureCode.PRODUCT_WRITE_FAILED
        definition = definition_for(code)
        assert definition.category == FailureCategory.PRODUCT

    def test_validation_code_has_validation_category(self) -> None:
        """VALIDATION codes have VALIDATION category."""
        code = FailureCode.VALIDATION_UNKNOWN_PARAMETER
        definition = definition_for(code)
        assert definition.category == FailureCategory.VALIDATION


class TestIsRetryable:
    """Tests for is_retryable function."""

    def test_transient_resource_failures_are_retryable(self) -> None:
        """Transient resource failures are retryable."""
        assert is_retryable(FailureCode.PRODUCT_WRITE_FAILED)
        assert is_retryable(FailureCode.RESOURCE_TIMEOUT)
        assert is_retryable(FailureCode.RESOURCE_MEMORY_BUDGET_EXCEEDED)
        assert is_retryable(FailureCode.RESOURCE_STORAGE_EXHAUSTED)
        assert is_retryable(FailureCode.RESOURCE_DEVICE_UNAVAILABLE)

    def test_deterministic_validation_not_retryable(self) -> None:
        """Deterministic validation failures are not retryable."""
        assert not is_retryable(FailureCode.INPUT_MISSING_FILE)
        assert not is_retryable(FailureCode.INPUT_CHECKSUM_MISMATCH)
        assert not is_retryable(FailureCode.VALIDATION_UNKNOWN_PARAMETER)

    def test_scientific_gate_failures_not_retryable(self) -> None:
        """Scientific gate failures are not retryable."""
        assert not is_retryable(FailureCode.GEOMETRY_NO_OVERLAP)
        assert not is_retryable(FailureCode.MATCHING_INSUFFICIENT_CANDIDATES)
        assert not is_retryable(FailureCode.REFINEMENT_DID_NOT_CONVERGE)
        assert not is_retryable(FailureCode.ADJUSTMENT_DID_NOT_CONVERGE)

    def test_internal_failures_not_retryable(self) -> None:
        """Internal failures are not retryable."""
        assert not is_retryable(FailureCode.INTERNAL_CANCELLED)
        assert not is_retryable(FailureCode.INTERNAL_UNEXPECTED_ERROR)

    def test_model_unavailable_is_retryable(self) -> None:
        """Model unavailable is retryable (device not being ready is transient)."""
        assert is_retryable(FailureCode.MATCHING_MODEL_UNAVAILABLE)

    def test_product_checksum_mismatch_is_retryable(self) -> None:
        """Product checksum mismatch is retryable (storage may be faulty)."""
        assert is_retryable(FailureCode.PRODUCT_CHECKSUM_MISMATCH)

    def test_is_retryable_matches_definition(self) -> None:
        """is_retryable returns the definition's retryable value."""
        for code in FailureCode:
            definition = definition_for(code)
            assert is_retryable(code) == definition.retryable


class TestFailureDefinitionContent:
    """Tests for specific failure definition content."""

    def test_input_missing_file_definition(self) -> None:
        """INPUT_MISSING_FILE has correct definition."""
        definition = definition_for(FailureCode.INPUT_MISSING_FILE)
        assert definition.category == FailureCategory.INPUT
        assert not definition.retryable
        assert "file" in definition.summary.lower()

    def test_product_write_failed_definition(self) -> None:
        """PRODUCT_WRITE_FAILED has correct definition."""
        definition = definition_for(FailureCode.PRODUCT_WRITE_FAILED)
        assert definition.category == FailureCategory.PRODUCT
        assert definition.retryable
        assert "storage" in definition.remediation.lower()

    def test_resource_timeout_definition(self) -> None:
        """RESOURCE_TIMEOUT has correct definition."""
        definition = definition_for(FailureCode.RESOURCE_TIMEOUT)
        assert definition.category == FailureCategory.RESOURCE
        assert definition.retryable

    def test_internal_cancelled_definition(self) -> None:
        """INTERNAL_CANCELLED has correct definition."""
        definition = definition_for(FailureCode.INTERNAL_CANCELLED)
        assert definition.category == FailureCategory.INTERNAL
        assert not definition.retryable

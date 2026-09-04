"""Contracts for operator password hashing."""

from __future__ import annotations

import pytest

from selene_service.api.password_auth import hash_password, verify_password


@pytest.mark.unit
def test_hash_password_never_returns_the_raw_value() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


@pytest.mark.unit
def test_verify_password_accepts_the_matching_raw_value() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


@pytest.mark.unit
def test_verify_password_rejects_a_wrong_value() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("wrong password", hashed) is False


@pytest.mark.unit
def test_verify_password_rejects_a_malformed_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


@pytest.mark.unit
def test_hash_password_is_salted_so_two_hashes_of_one_password_differ() -> None:
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert verify_password("same password", first) is True
    assert verify_password("same password", second) is True

"""Public, non-leaking errors raised by the API service layer."""

from __future__ import annotations


class APIProblem(Exception):
    """An expected client error with a stable HTTP status and error code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class BadRequestProblem(APIProblem):
    """The caller supplied a syntactically valid but unusable request."""

    def __init__(self, message: str = "The request could not be processed.") -> None:
        super().__init__(400, "bad_request", message)


class NotFoundProblem(APIProblem):
    """A requested persisted resource does not exist."""

    def __init__(self, message: str = "The requested resource was not found.") -> None:
        super().__init__(404, "not_found", message)


class ConflictProblem(APIProblem):
    """A request conflicts with durable resource state."""

    def __init__(
        self,
        message: str = "The request conflicts with the current resource state.",
    ) -> None:
        super().__init__(409, "conflict", message)

"""Shared error base types for domain concepts."""


class BaseError(Exception):
    """Base class for expected errors."""

    code = "error"
    retryable = False


class DomainError(BaseError):
    """Base class for domain rule errors."""

    code = "domain.error"



"""Infrastructure error types raised by concrete adapters."""

from domain.exceptions import BaseError


class InfraError(BaseError):
    """Base class for expected infrastructure adapter errors."""

    code = "infra.error"
    retryable = True

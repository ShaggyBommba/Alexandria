"""Infrastructure error types raised by concrete adapters."""

from domain.exceptions import BaseError


class InfraError(BaseError):
    """Base class for expected infrastructure adapter errors."""

    code = "infra.error"
    retryable = True


class AgentError(InfraError):
    """Raised when an LLM agent adapter fails."""

    code = "infra.agent.error"


class ReferenceRepoError(InfraError):
    """Base class for expected reference repository errors."""

    code = "infra.reference_repo.error"


class ReferenceSourceMismatch(ReferenceRepoError):
    """Raised when replacement refs do not belong to the requested source."""

    code = "infra.reference_repo.source_mismatch"
    retryable = False

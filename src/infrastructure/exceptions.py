"""Infrastructure error types raised by concrete adapters."""

from domain.exceptions import BaseError


class InfraError(BaseError):
    """Base class for expected infrastructure adapter errors."""

    code = "infra.error"
    retryable = True


class AgentError(InfraError):
    """Base class for expected agent adapter errors."""

    code = "infra.agent.error"


class SummarizerError(AgentError):
    """Base class for expected summarizer adapter errors."""

    code = "infra.summarizer.error"


class SummarizerConfigError(SummarizerError):
    """Raised when summarizer settings are incomplete or invalid."""

    code = "infra.summarizer.config"
    retryable = False


class SplitterError(AgentError):
    """Base class for expected splitter adapter errors."""

    code = "infra.splitter.error"


class SplitterConfigError(SplitterError):
    """Raised when splitter settings are incomplete or invalid."""

    code = "infra.splitter.config"
    retryable = False


class SplitterResponseError(SplitterError):
    """Raised when a splitter provider returns unusable data."""

    code = "infra.splitter.response"
    retryable = False


class RankerError(AgentError):
    """Base class for expected ranker adapter errors."""

    code = "infra.ranker.error"


class RankerConfigError(RankerError):
    """Raised when ranker settings are incomplete or invalid."""

    code = "infra.ranker.config"
    retryable = False


class RankerResponseError(RankerError):
    """Raised when a ranker provider returns unusable data."""

    code = "infra.ranker.response"
    retryable = False


class EmbedderError(InfraError):
    """Base class for expected embedding adapter errors."""

    code = "infra.embedder.error"


class EmbedderConfigError(EmbedderError):
    """Raised when embedding adapter settings cannot be used."""

    code = "infra.embedder.config"
    retryable = False


class EmbedderClientError(EmbedderError):
    """Raised when the embedding endpoint cannot serve the request."""

    code = "infra.embedder.client"


class EmbedderRequestError(EmbedderError):
    """Raised when the embedding endpoint rejects the request permanently."""

    code = "infra.embedder.request"
    retryable = False


class EmbedderResponseError(EmbedderError):
    """Raised when the embedding endpoint returns unusable data."""

    code = "infra.embedder.response"
    retryable = False


class ReferenceRepoError(InfraError):
    """Base class for expected reference repository errors."""

    code = "infra.reference_repo.error"


class ReferenceSourceMismatch(ReferenceRepoError):
    """Raised when replacement refs do not belong to the requested source."""

    code = "infra.reference_repo.source_mismatch"
    retryable = False

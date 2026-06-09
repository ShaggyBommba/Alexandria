"""Application error types raised by use cases and ports."""

from domain.exceptions import BaseError


class AppError(BaseError):
    """Base class for expected application workflow errors."""

    code = "app.error"


class MissingUnitOfWork(AppError):
    """Raised when a use case requiring durable writes has no unit of work."""

    code = "app.missing_unit_of_work"


class IngestDependencyError(AppError):
    """Raised when ingest is missing a required dependency."""

    code = "app.ingest.dependency"


class IngestLeafError(AppError):
    """Raised when ingest cannot choose a valid attachment leaf."""

    code = "app.ingest.leaf"


class RouteDependencyError(AppError):
    """Raised when route traversal is missing required dependencies."""

    code = "app.route.dependency"

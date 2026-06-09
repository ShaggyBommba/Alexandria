"""Application error types raised by use cases and ports."""

from domain.exceptions import BaseError


class AppError(BaseError):
    """Base class for expected application workflow errors."""

    code = "app.error"


class MissingUnitOfWork(AppError):
    """Raised when a use case requiring durable writes has no unit of work."""

    code = "app.missing_unit_of_work"


class RouteDependencyError(AppError):
    """Raised when route traversal is missing required dependencies."""

    code = "app.route.dependency"


class RetrieveDependencyError(AppError):
    """Raised when retrieval is missing required dependencies."""

    code = "app.retrieve.dependency"

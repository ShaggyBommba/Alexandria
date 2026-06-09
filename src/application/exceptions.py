"""Application error types raised by use cases and ports."""

from domain.exceptions import BaseError


class AppError(BaseError):
    """Base class for expected application workflow errors."""

    code = "app.error"


class RouteDependencyError(AppError):
    """Raised when route traversal is missing required dependencies."""

    code = "app.route.dependency"

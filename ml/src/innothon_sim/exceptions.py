class NetworkValidationError(ValueError):
    """Raised when the network JSON is missing required fields."""


class PandapowerUnavailableError(RuntimeError):
    """Raised when pandapower is required but not installed."""

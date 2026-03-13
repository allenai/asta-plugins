"""Authentication exceptions."""


class AuthenticationError(Exception):
    """Base authentication error."""

    pass


class AuthenticationTimeout(AuthenticationError):
    """Authentication timed out."""

    pass

"""Exception hierarchy for xhh_sdk.

Every error carries a public, printable message. Credentials, cookies and raw
upstream bodies never appear in exception text.
"""
from __future__ import annotations


class XhhError(Exception):
    """Base class for every SDK error."""


class XhhConfigError(XhhError):
    """Configuration is missing or invalid."""


class XhhSignerError(XhhError):
    """The offline signer could not produce a signature."""


class XhhTransportError(XhhError):
    """Network-level failure (DNS, TLS, timeout, connection reset)."""


class XhhAuthError(XhhError):
    """The platform rejected the session (login required or expired)."""


class XhhRateLimitError(XhhError):
    """The platform throttled this action (发帖频率过快, code 10006)."""


class XhhAPIError(XhhError):
    """The platform answered with a non-ok status."""

    def __init__(self, message: str, *, status: str = "", path: str = ""):
        super().__init__(message)
        self.status = status
        self.path = path

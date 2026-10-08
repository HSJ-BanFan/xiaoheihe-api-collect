"""xhh_sdk — unofficial Python SDK for the xiaoheihe creation/upload APIs.

Companion to the xiaoheihe API documentation project. Redistribution rights
remain under review; keep credentials out of version control.
"""
from .client import XhhClient
from .config import XhhConfig
from .exceptions import (
    XhhAPIError,
    XhhAuthError,
    XhhConfigError,
    XhhError,
    XhhRateLimitError,
    XhhSignerError,
    XhhTransportError,
)
from .interaction import InteractionMixin
from .payload import Post, plain_text
from .routes import VERIFIED_READ_ROUTES, is_verified_read
from .signer import Signer
from .transport import Transport, cos_authorization

__version__ = "0.5.0rc4+standalone.6"

__all__ = [
    "XhhClient",
    "XhhConfig",
    "Post",
    "InteractionMixin",
    "Signer",
    "Transport",
    "VERIFIED_READ_ROUTES",
    "cos_authorization",
    "is_verified_read",
    "plain_text",
    "XhhError",
    "XhhConfigError",
    "XhhSignerError",
    "XhhTransportError",
    "XhhAuthError",
    "XhhRateLimitError",
    "XhhAPIError",
    "__version__",
]

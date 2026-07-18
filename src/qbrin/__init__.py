"""qbrin — the verification layer for AI agents.

Ask questions against your organisation's own sources and get back answers
with a citation behind every claim — or an honest tri-state verdict
(``verified`` / ``rejected`` / ``need_more_evidence``) instead of a guess.
"""

from .client import DEFAULT_BASE_URL, Qbrin, __version__
from .errors import (
    APIError,
    AuthenticationError,
    FeatureDisabledError,
    QbrinError,
    RateLimitError,
    TransportError,
)
from .models import (
    DECISION_NEED_MORE_EVIDENCE,
    DECISION_REJECTED,
    DECISION_VERIFIED,
    AskResult,
    ClaimVerdict,
    Evidence,
    Freshness,
    VerifyResult,
)

__all__ = [
    "Qbrin",
    "DEFAULT_BASE_URL",
    "__version__",
    "QbrinError",
    "TransportError",
    "APIError",
    "AuthenticationError",
    "RateLimitError",
    "FeatureDisabledError",
    "VerifyResult",
    "AskResult",
    "Evidence",
    "ClaimVerdict",
    "Freshness",
    "DECISION_VERIFIED",
    "DECISION_REJECTED",
    "DECISION_NEED_MORE_EVIDENCE",
]

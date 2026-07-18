"""Typed results returned by the qbrin client.

The server is the source of truth; these dataclasses are thin, forward-
compatible views. Unknown fields are preserved in ``raw`` so an SDK upgrade
is never required to read a new server field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: The three verification decisions. ``verified`` is the only decision that
#: carries an answer — the other two explain themselves in ``explanation``.
DECISION_VERIFIED = "verified"
DECISION_REJECTED = "rejected"
DECISION_NEED_MORE_EVIDENCE = "need_more_evidence"


@dataclass
class Evidence:
    """One cited source excerpt backing a verified answer."""

    n: Optional[int] = None
    document_id: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    score: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Evidence":
        return cls(
            n=d.get("n"),
            document_id=d.get("documentId"),
            source=d.get("source"),
            title=d.get("title"),
            snippet=d.get("snippet"),
            score=d.get("score"),
            raw=d,
        )


@dataclass
class ClaimVerdict:
    """The verifier's per-claim audit of a verified answer."""

    claim: str
    citations: List[str]
    supported: bool
    reason: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ClaimVerdict":
        return cls(
            claim=d.get("claim", ""),
            citations=[str(c) for c in d.get("citations") or []],
            supported=bool(d.get("supported")),
            reason=d.get("reason"),
        )


@dataclass
class Freshness:
    """When the evidence was authored, and whether any of it was queried live."""

    checked_at: Optional[str] = None
    live_evidence_count: int = 0
    oldest_evidence: Optional[str] = None
    newest_evidence: Optional[str] = None

    @property
    def used_live_evidence(self) -> bool:
        return self.live_evidence_count > 0

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> Optional["Freshness"]:
        if not d:
            return None
        return cls(
            checked_at=d.get("checkedAt"),
            live_evidence_count=int(d.get("liveEvidenceCount") or 0),
            oldest_evidence=d.get("oldestEvidence"),
            newest_evidence=d.get("newestEvidence"),
        )


@dataclass
class VerifyResult:
    """The tri-state verification contract from ``POST /api/verify``."""

    decision: str
    reason: Optional[str]
    explanation: Optional[str]
    answer: Optional[str]
    evidence: List[Evidence]
    claims: Optional[List[ClaimVerdict]]
    freshness: Optional[Freshness]
    trust: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_verified(self) -> bool:
        return self.decision == DECISION_VERIFIED

    @property
    def is_rejected(self) -> bool:
        return self.decision == DECISION_REJECTED

    @property
    def needs_more_evidence(self) -> bool:
        return self.decision == DECISION_NEED_MORE_EVIDENCE

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VerifyResult":
        claims = d.get("claims")
        return cls(
            decision=d.get("decision", DECISION_NEED_MORE_EVIDENCE),
            reason=d.get("reason"),
            explanation=d.get("explanation"),
            answer=d.get("answer"),
            evidence=[Evidence.from_dict(e) for e in d.get("evidence") or []],
            claims=[ClaimVerdict.from_dict(c) for c in claims] if claims else None,
            freshness=Freshness.from_dict(d.get("freshness")),
            trust=d.get("trust"),
            raw=d,
        )


@dataclass
class AskResult:
    """A grounded answer from ``POST /api/ask`` — every claim carries a citation."""

    answer: str
    citations: List[Evidence]
    covered_by_map: bool
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AskResult":
        return cls(
            answer=d.get("answer", ""),
            citations=[Evidence.from_dict(c) for c in d.get("citations") or []],
            covered_by_map=bool(d.get("coveredBySnapshot")),
            raw=d,
        )

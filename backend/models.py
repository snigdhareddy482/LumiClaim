"""Shared data models for LumiClaim's backend services."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Adjustment(BaseModel):
	"""Represents an individual adjustment applied to a claim line."""

	type: str
	amount: float | None = None


class ClaimRow(BaseModel):
	"""Structured representation of an EOB row extracted from source documents."""

	line_id: str
	page: int
	cell_id: str
	cpt: str | None = None
	modifier: str | None = None
	billed: float
	allowed: float
	insurer_paid: float
	adjustments: list[Adjustment] = Field(default_factory=list)
	patient_resp: float | None = None


class ExplainResponse(BaseModel):
	"""Payload returned when explaining how a claim line reconciles mathematically."""

	doc_id: str
	verifiability_score: float
	breakdown: list[dict[str, Any]]
	explain_like_12: str
	citations: list[dict[str, Any]]
	calcs: list[dict[str, Any]]
	warnings: list[str] = Field(default_factory=list)
	unverifiable_fields: list[str] = Field(default_factory=list)
	takeaway: str
	risk_flags: list[dict[str, Any]] = Field(default_factory=list)


class AskRequest(BaseModel):
	"""Question posed to the LumiClaim reasoning pipeline."""

	question: str
	doc_id: str | None = None
	policy_id: str | None = None


class PSLRequest(BaseModel):
	"""Request payload for policy simulation layer interactions."""

	doc_id: str
	deductible_remaining: float
	coinsurance: float
	oop_remaining: float


class SimulateRequest(BaseModel):
    """Backward-compatible simulate request allowing optional policy fields and session lookup.

    Fields deductible_remaining, coinsurance, and oop_remaining are optional — when missing,
    the server will try to load a profile using `session_id` and infer defaults where possible.
    """

    doc_id: str
    session_id: str | None = None
    deductible_remaining: float | None = None
    coinsurance: float | None = None
    oop_remaining: float | None = None

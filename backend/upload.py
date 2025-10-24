"""Utilities for redacting sensitive text prior to ingest."""

from __future__ import annotations

import re
from typing import Dict, Pattern, Tuple


_REDACTED_STORE: Dict[str, str] = {}


_LABEL_PATTERNS: Tuple[Tuple[Pattern[str], str], ...] = (
	(
		re.compile(r"(?i)\b((?:patient|member|subscriber|provider)\s+name\s*[:\-]\s*)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
		r"\1[REDACTED_NAME]",
	),
	(
		re.compile(r"(?i)\b((?:mrn|medical\s+record\s+number)\s*[:#]?\s*)([A-Za-z0-9-]+)"),
		r"\1[REDACTED_MRN]",
	),
	(
		re.compile(r"(?i)\b((?:phone|tel|telephone|contact)\s*[:\-]\s*)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"),
		r"\1[REDACTED_PHONE]",
	),
	(
		re.compile(r"(?i)\b((?:dob|date\s+of\s+birth)\s*[:\-]\s*)(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})"),
		r"\1[REDACTED_DATE]",
	),
)

_GENERIC_PATTERNS: Tuple[Tuple[Pattern[str], str], ...] = (
	(
		re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"),
		"[REDACTED_PHONE]",
	),
	(
		re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
		"[REDACTED_DATE]",
	),
	(
		re.compile(r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b"),
		"[REDACTED_DATE]",
	),
	(
		re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
		"[REDACTED_EMAIL]",
	),
)


def redact_text(text: str) -> str:
	"""Return text with simple PII markers replaced for demo purposes."""

	redacted = text
	for pattern, replacement in _LABEL_PATTERNS:
		redacted = pattern.sub(replacement, redacted)
	for pattern, replacement in _GENERIC_PATTERNS:
		redacted = pattern.sub(replacement, redacted)
	return redacted


def store_redacted_document(doc_id: str, content: str) -> None:
	"""Persist a redacted copy in memory for the current session."""

	_REDACTED_STORE[doc_id] = content


def get_redacted_document(doc_id: str) -> str | None:
	"""Return the redacted copy for the provided document id if present."""

	return _REDACTED_STORE.get(doc_id)


def list_redacted_documents() -> Dict[str, str]:
	"""Expose a shallow copy of the in-memory store for debugging/tests."""

	return dict(_REDACTED_STORE)

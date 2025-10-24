"""Vertex AI adapter interface placeholder."""

from __future__ import annotations

from typing import Any


def verbalize(outputs: dict[str, Any], citations: list[dict[str, Any]]) -> dict[str, Any]:
	"""Call Vertex AI to craft a grounded response.

	Implementations should take structured retrieval outputs and citations, run the
	desired Vertex model, and return a dictionary containing the response payload
	(e.g., ``{"answer": "...", "metadata": {...}}``).
	"""

	raise NotImplementedError("Vertex adapter is not configured in local mode")

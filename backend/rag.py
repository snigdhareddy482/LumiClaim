"""Retrieval-augmented generation helpers for LumiClaim."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from backend.config import USE_ELASTIC, USE_VERTEX
from backend.hybrid_local import search as local_search

if USE_ELASTIC:
	from backend.search_adapters import elastic_adapter
else:  # pragma: no cover - local mode default
	elastic_adapter = None

if USE_VERTEX:
	from backend.llm_adapters.vertex_adapter import verbalize as vertex_verbalize
else:  # pragma: no cover - local mode default
	vertex_verbalize = None


def answer_with_citations(question: str, doc_id: str | None, policy_id: str | None, session_id: str | None = None) -> dict:
	"""Retrieve supporting evidence and return a grounded answer stub."""

	# Load profile data if available
	profile_data = _load_profile(session_id) if session_id else None
	
	if USE_ELASTIC and elastic_adapter is not None:
		result = elastic_adapter.search(question, doc_id=doc_id, top_k=3)
		hits = _normalize_hits(result.get("hits", []))
		retrieval_source = "elasticsearch"
		retrieval_debug = {
			"engine": retrieval_source,
			"query": question,
			"doc_filter": doc_id,
			"raw": result.get("debug", {}),
			"hits": hits,
		}
	else:
		hits = _normalize_hits(local_search(question, doc_id=doc_id, session_id=session_id, top_k=3))
		retrieval_source = "hybrid_local"
		retrieval_debug = {
			"engine": retrieval_source,
			"query": question,
			"doc_filter": doc_id,
			"hits": hits,
		}
	
	# Build answer with profile context
	profile_context = ""
	if profile_data:
		profile_context = _format_profile_context(profile_data)
	
	if hits:
		summary = "; ".join(
			f"{hit['doc_id']} line {hit['line_id']} (page {hit['page']})"
			for hit in hits
		)
		answer_parts = []
		if profile_context:
			answer_parts.append(f"Your insurance profile: {profile_context}")
		answer_parts.append(f"Relevant claims data: {summary}")
		answer = ". ".join(answer_parts) + "."
		verifiability = min(0.95, 0.8 + 0.05 * len(hits))
	else:
		if profile_context:
			answer = f"Your insurance profile: {profile_context}. No claims found yet."
			verifiability = 0.7
		else:
			answer = "No supporting data was found."
			verifiability = 0.5

	citations = _to_citations(hits)

	payload = {
		"answer": answer,
		"citations": citations,
		"verifiability_score": verifiability,
		"retrieval_source": retrieval_source,
		"retrieval_debug": retrieval_debug,
	}

	if USE_VERTEX and vertex_verbalize is not None:
		try:
			model_output = vertex_verbalize(payload, citations)
			if isinstance(model_output, dict):
				payload.update(model_output)
		except NotImplementedError:  # pragma: no cover - adapter may not be wired
			pass

	return payload


def _normalize_hits(hits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Ensure downstream consumers receive a consistent hit payload."""

	result: list[dict[str, Any]] = []
	for hit in hits:
		if not isinstance(hit, dict):  # defensive guard for adapter discrepancies
			continue
		doc_id = str(hit.get("doc_id") or "").strip()
		if not doc_id:
			continue
		line_id = str(hit.get("line_id") or "").strip() or "na"
		page = int(hit.get("page") or 0)
		cell = str(hit.get("cell") or "").strip()
		score_raw = hit.get("score")
		try:
			score = float(score_raw)
		except (TypeError, ValueError):
			score = 0.0
		snippet = hit.get("snippet") or hit.get("why") or ""
		result.append(
			{
				"doc_id": doc_id,
				"line_id": line_id,
				"page": page,
				"cell": cell,
				"score": round(score, 6),
				"snippet": str(snippet)[:220],
			},
		)
	return result


def _to_citations(hits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
	return [
		{
			"doc": f"{hit['doc_id']}.pdf",
			"page": hit.get("page"),
			"cell": hit.get("cell"),
			"line_id": hit.get("line_id"),
			"score": hit.get("score"),
		}
		for hit in hits
	]


def _load_profile(session_id: str) -> dict[str, Any] | None:
	"""Load profile data for the session."""
	profile_path = Path(os.path.dirname(__file__)) / ".." / "data" / "user_sessions" / session_id / "profile.json"
	if not profile_path.exists():
		return None
	try:
		with open(profile_path, "r", encoding="utf-8") as f:
			return json.load(f)
	except Exception:
		return None


def _format_profile_context(profile: dict[str, Any]) -> str:
	"""Format profile data into a readable context string."""
	parts = []
	if profile.get("patient_name"):
		parts.append(f"Patient: {profile['patient_name']}")
	if profile.get("deductible_individual"):
		parts.append(f"Deductible: ${profile['deductible_individual']:.2f}")
	if profile.get("oop_max_individual"):
		parts.append(f"Out-of-Pocket Max: ${profile['oop_max_individual']:.2f}")
	if profile.get("coinsurance_pct"):
		parts.append(f"Coinsurance: {profile['coinsurance_pct']}%")
	return ", ".join(parts) if parts else "Plan details available"

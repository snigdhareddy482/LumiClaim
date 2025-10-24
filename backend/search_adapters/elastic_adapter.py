"""Minimal Elasticsearch adapter used when USE_ELASTIC is enabled."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import ApiError

from backend.config import ELASTIC_PASSWORD, ELASTIC_URL, ELASTIC_USERNAME

LOGGER = logging.getLogger(__name__)
_INDEX_NAME = "claims_raw"


class ElasticAdapter:
	"""Lightweight helper to interact with an Elasticsearch cluster."""

	def __init__(self) -> None:
		auth = (ELASTIC_USERNAME, ELASTIC_PASSWORD) if ELASTIC_USERNAME or ELASTIC_PASSWORD else None
		self._client = Elasticsearch(hosts=[ELASTIC_URL], basic_auth=auth, timeout=20)
		self.ensure_indices()

	def ensure_indices(self) -> None:
		"""Create the claims_raw index if it does not exist."""

		mapping = {
			"settings": {
				"number_of_shards": 1,
				"number_of_replicas": 0,
			},
			"mappings": {
				"properties": {
					"session_id": {"type": "keyword"},
					"doc_id": {"type": "keyword"},
					"page": {"type": "integer"},
					"raw_text": {"type": "text"},
				},
			},
		}

		try:
			if not self._client.indices.exists(index=_INDEX_NAME):
				self._client.indices.create(index=_INDEX_NAME, **mapping)
		except ApiError as exc:  # pragma: no cover - depends on cluster availability
			LOGGER.warning("Unable to create index %s: %s", _INDEX_NAME, exc)

	def index_minimal(self, samples_path: str | Path) -> Dict[str, Any]:
		"""Bulk index a handful of sample documents for quick experimentation."""

		samples_path = Path(samples_path)
		if not samples_path.exists():
			raise FileNotFoundError(f"Sample file not found: {samples_path}")

		with samples_path.open("r", encoding="utf-8") as handle:
			payload = json.load(handle)
		if not isinstance(payload, dict):
			raise ValueError("Sample file must contain a JSON object of doc_id → rows")

		self.ensure_indices()

		actions = list(self._yield_actions(payload))
		if not actions:
			LOGGER.info("No sample rows found to index at %s", samples_path)
			return {"indexed": 0}

		try:
			helpers.bulk(self._client, actions, refresh="wait_for")
		except ApiError as exc:  # pragma: no cover - bulk failures depend on cluster
			LOGGER.error("Bulk indexing failed: %s", exc)
			return {"indexed": 0, "error": str(exc)}

		LOGGER.info("Indexed %s sample rows into %s", len(actions), _INDEX_NAME)
		return {"indexed": len(actions)}

	def search(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
		"""Return the top matching rows for the supplied query."""

		if not query.strip():
			return []

		body = {
			"size": k,
			"query": {"match": {"raw_text": {"query": query}}},
		}
		try:
			response = self._client.search(index=_INDEX_NAME, body=body)
		except ApiError as exc:  # pragma: no cover - cluster dependent
			LOGGER.error("Elasticsearch search failed: %s", exc)
			return []

		return [self._format_hit(hit) for hit in response.get("hits", {}).get("hits", [])]

	def _yield_actions(self, payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
		for doc_id, rows in payload.items():
			if not isinstance(rows, list):
				continue
			for idx, row in enumerate(rows):
				if not isinstance(row, dict):
					continue
				page = int(row.get("page") or 0)
				text = self._row_to_text(doc_id, row)
				yield {
					"_index": _INDEX_NAME,
					"_id": f"{doc_id}:{idx}",
					"_source": {
						"session_id": doc_id,
						"doc_id": doc_id,
						"page": page,
						"raw_text": text,
					},
				}

	@staticmethod
	def _row_to_text(doc_id: str, row: Dict[str, Any]) -> str:
		parts = [f"Document {doc_id}"]
		if row.get("line_id"):
			parts.append(f"line {row['line_id']}")
		if row.get("cpt"):
			parts.append(f"CPT {row['cpt']}")
		if row.get("modifier"):
			parts.append(f"modifier {row['modifier']}")
		if row.get("billed") is not None:
			parts.append(f"billed {row['billed']}")
		if row.get("allowed") is not None:
			parts.append(f"allowed {row['allowed']}")
		if row.get("insurer_paid") is not None:
			parts.append(f"insurer paid {row['insurer_paid']}")
		if row.get("patient_resp") is not None:
			parts.append(f"patient responsibility {row['patient_resp']}")
		return ", ".join(str(part) for part in parts if part)

	@staticmethod
	def _format_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
		source = hit.get("_source", {})
		return {
			"doc_id": source.get("doc_id"),
			"page": source.get("page"),
			"why": (source.get("raw_text") or "")[:220],
			"score": float(hit.get("_score") or 0.0),
		}


_ADAPTER: ElasticAdapter | None = None


def _get_adapter() -> ElasticAdapter:
	global _ADAPTER
	if _ADAPTER is None:
		_ADAPTER = ElasticAdapter()
	return _ADAPTER


def ensure_indices() -> None:
	_get_adapter().ensure_indices()


def index_minimal(samples_path: str | Path) -> Dict[str, Any]:
	return _get_adapter().index_minimal(samples_path)


def search(query: str, k: int = 3) -> List[Dict[str, Any]]:
	return _get_adapter().search(query, k=k)


__all__ = [
	"ElasticAdapter",
	"ensure_indices",
	"index_minimal",
	"search",
]

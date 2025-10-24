"""Local hybrid retrieval combining BM25 with optional vector scoring."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from rank_bm25 import BM25Okapi

from backend.math_guard import DATA_PATH, _load_struct

try:  # Optional dependency; degrade gracefully if missing.
	from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
	SentenceTransformer = None  # type: ignore[assignment]

_TOKEN_SPLIT = re.compile(r"[^a-zA-Z0-9]+")


@dataclass
class IndexedSegment:
	doc_id: str
	line_id: str
	page: int
	cell: str
	cpt: str | None
	modifier: str | None
	text: str
	tokens: list[str]


class HybridLocalEngine:
	"""Hybrid retriever backed by BM25 and optional embeddings."""

	def __init__(self) -> None:
		self._segments: list[IndexedSegment] = []
		self._bm25: BM25Okapi | None = None
		self._st_model: Any | None = None
		self._embeddings: np.ndarray | None = None
		self._embedding_norms: np.ndarray | None = None
		self._build_index()

	def _build_index(self) -> None:
		with open(Path(DATA_PATH), "r", encoding="utf-8") as handle:
			doc_ids = list(json.load(handle).keys())

		for doc_id in doc_ids:
			rows = _load_struct(doc_id)
			for row in rows:
				text = self._row_to_text(row)
				tokens = self._tokenize(text)
				segment = IndexedSegment(
					doc_id=doc_id,
					line_id=row.line_id,
					page=row.page,
					cell=row.cell_id,
					cpt=row.cpt,
					modifier=row.modifier,
					text=text,
					tokens=tokens,
				)
				self._segments.append(segment)

		if self._segments:
			doc_tokens = [segment.tokens for segment in self._segments]
			self._bm25 = BM25Okapi(doc_tokens)

		self._init_vector_store()

	def _init_vector_store(self) -> None:
		if SentenceTransformer is None:
			return
		try:
			model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
		except Exception:  # pragma: no cover - model download may fail offline
			self._st_model = None
			self._embeddings = None
			self._embedding_norms = None
			return

		texts = [segment.text for segment in self._segments]
		if not texts:
			self._st_model = None
			self._embeddings = None
			self._embedding_norms = None
			return

		try:
			embeddings = model.encode(texts, convert_to_numpy=True, batch_size=16, show_progress_bar=False)
		except Exception:  # pragma: no cover - encoding failures should not crash
			self._st_model = None
			self._embeddings = None
			self._embedding_norms = None
			return

		if not isinstance(embeddings, np.ndarray):
			embeddings = np.array(embeddings)

		norms = np.linalg.norm(embeddings, axis=1)
		norms[norms == 0] = 1e-9

		self._st_model = model
		self._embeddings = embeddings
		self._embedding_norms = norms

	@staticmethod
	def _tokenize(text: str) -> list[str]:
		return [token for token in _TOKEN_SPLIT.split(text.lower()) if token]

	@staticmethod
	def _row_to_text(row: Any) -> str:
		parts: list[str] = []
		parts.append(f"Line {row.line_id} on page {row.page} (cell {row.cell_id})")
		if row.cpt:
			parts.append(f"CPT {row.cpt}")
		if row.modifier:
			parts.append(f"modifier {row.modifier}")
		parts.append(f"billed {row.billed:.2f}")
		parts.append(f"allowed {row.allowed:.2f}")
		parts.append(f"insurer paid {row.insurer_paid:.2f}")
		parts.append(f"patient responsibility {row.patient_resp if row.patient_resp is not None else 0.0:.2f}")
		adjust_total = sum(adj.amount for adj in row.adjustments) if row.adjustments else 0.0
		parts.append(f"adjustments {adjust_total:.2f}")
		return ", ".join(parts)

	def search(self, query: str, *, doc_id: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
		if not query.strip() or not self._segments:
			return []

		candidate_indices = [
			idx
			for idx, segment in enumerate(self._segments)
			if doc_id is None or segment.doc_id == doc_id
		]
		if not candidate_indices:
			return []

		bm25_ranked, bm25_scores = self._bm25_scores(query, candidate_indices)
		vector_ranked, vector_scores = self._vector_scores(query, candidate_indices)

		fusion_scores: dict[int, float] = defaultdict(float)
		contrib: dict[int, dict[str, float]] = defaultdict(lambda: {"bm25": 0.0, "vector": 0.0})
		k_value = 60.0

		for rank, idx in enumerate(bm25_ranked, start=1):
			increment = 1.0 / (k_value + rank)
			fusion_scores[idx] += increment
			contrib[idx]["bm25"] += increment

		for rank, idx in enumerate(vector_ranked, start=1):
			increment = 1.0 / (k_value + rank)
			fusion_scores[idx] += increment
			contrib[idx]["vector"] += increment

		if not fusion_scores:
			fusion_scores = {idx: 1.0 / (k_value + pos) for pos, idx in enumerate(bm25_ranked, start=1)}

		sorted_hits = sorted(fusion_scores.items(), key=lambda item: item[1], reverse=True)
		results: list[dict[str, Any]] = []
		for idx, score in sorted_hits[:top_k]:
			segment = self._segments[idx]
			bm25_raw = float(bm25_scores.get(idx, 0.0))
			vector_raw = float(vector_scores.get(idx, 0.0))
			fields = {
				"cpt": getattr(segment, "cpt", None),
				"modifier": getattr(segment, "modifier", None),
			}
			results.append(
				{
					"doc_id": segment.doc_id,
					"line_id": segment.line_id,
					"page": segment.page,
					"cell": segment.cell,
					"snippet": segment.text[:220],
					"score": round(score, 6),
					"contrib": {
						"bm25": round(contrib[idx]["bm25"], 6),
						"vector": round(contrib[idx]["vector"], 6),
					},
					"raw_scores": {
						"bm25": round(bm25_raw, 6),
						"vector": round(vector_raw, 6),
					},
					"fields": fields,
				}
			)

		return results

	def _bm25_scores(self, query: str, indices: Iterable[int]) -> tuple[list[int], dict[int, float]]:
		if self._bm25 is None:
			return [], {}
		tokens = self._tokenize(query)
		if not tokens:
			return [], {}
		scores = self._bm25.get_scores(tokens)
		candidate_scores = {idx: float(scores[idx]) for idx in indices}
		ordered = [idx for idx, _ in sorted(candidate_scores.items(), key=lambda item: item[1], reverse=True)]
		return ordered, candidate_scores

	def _vector_scores(self, query: str, indices: Iterable[int]) -> tuple[list[int], dict[int, float]]:
		if self._st_model is None or self._embeddings is None or self._embedding_norms is None:
			return [], {}
		if not query.strip():
			return [], {}
		try:
			query_vec = self._st_model.encode(query, convert_to_numpy=True)
		except Exception:  # pragma: no cover - embedding failures fall back to BM25 only
			return [], {}

		if not isinstance(query_vec, np.ndarray):
			query_vec = np.array(query_vec)

		query_norm = float(np.linalg.norm(query_vec))
		if math.isclose(query_norm, 0.0):
			return [], {}

		numerator = self._embeddings @ query_vec
		similarities = numerator / (self._embedding_norms * query_norm)

		candidate_scores = {idx: float(similarities[idx]) for idx in indices}
		ordered = [idx for idx, _ in sorted(candidate_scores.items(), key=lambda item: item[1], reverse=True)]
		return ordered, candidate_scores


_ENGINE: HybridLocalEngine | None = None


def _get_engine() -> HybridLocalEngine:
	global _ENGINE
	if _ENGINE is None:
		_ENGINE = HybridLocalEngine()
	return _ENGINE


def search(query: str, doc_id: str | None = None, *, top_k: int = 5) -> list[dict[str, Any]]:
	"""Return top-matching segments for the query using hybrid retrieval."""
	return _get_engine().search(query, doc_id=doc_id, top_k=top_k)

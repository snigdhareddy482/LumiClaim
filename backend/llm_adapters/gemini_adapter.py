"""Gemini adapter for generating grounded summaries."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

# Load .env for local development
from dotenv import load_dotenv
load_dotenv()

try:  # Optional dependency to keep local development light.
	import google.generativeai as genai  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - adapter requires runtime dependency
	genai = None  # type: ignore[assignment]


class NotConfigured(RuntimeError):
	"""Raised when the Gemini adapter cannot run due to missing setup."""


def verbalize(persona: str, level: str, payload: Dict[str, Any]) -> str:
	"""Return a concise Gemini-generated paragraph constrained to provided facts."""

	api_key = os.getenv("GEMINI_API_KEY")
	if not api_key:
		raise NotConfigured("GEMINI_API_KEY is not configured")
	if genai is None:
		raise NotConfigured("google-generativeai package is not installed")

	genai.configure(api_key=api_key)

	instruction = (
		"Only describe numbers & facts present in payload. Do not invent amounts. "
		f"Persona={persona}, Level={level}."
	)
	serialized_payload = json.dumps(payload, indent=2, sort_keys=True)

	model = genai.GenerativeModel("gemini-1.5-flash")
	reply = model.generate_content([
		{"role": "system", "parts": [instruction]},
		{"role": "user", "parts": [serialized_payload]},
	])

	text = _extract_text(reply)
	if not text:
		raise RuntimeError("Gemini response did not contain any text output")

	return text.strip()


def _extract_text(response: Any) -> str:
	"""Best-effort extraction of plain text from a Gemini response payload."""

	if response is None:
		return ""
	if getattr(response, "text", None):
		return str(response.text)

	candidates = getattr(response, "candidates", None)
	if candidates:
		for candidate in candidates:
			parts = getattr(candidate, "content", None)
			if parts and getattr(parts, "parts", None):
				for part in parts.parts:
					text = getattr(part, "text", None)
					if text:
						return str(text)

	return ""


def extract_text_from_image(image_data: Any) -> str:
    """Use Gemini Vision to extract text from an image (PIL Image)."""
    if genai is None:
        return ""
        
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return ""

    try:
        genai.configure(api_key=api_key)
        # Use Flash for speed
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Prompt for extraction
        response = model.generate_content(["Extract all text from this EOB document page verbatim.", image_data])
        
        return response.text if response else ""
    except Exception as e:
        print(f"[GEMINI OCR] Failed: {e}")
        return ""

__all__ = ["NotConfigured", "verbalize", "extract_text_from_image"]

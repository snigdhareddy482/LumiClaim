"""Configuration flags for LumiClaim backend features."""

from __future__ import annotations

import os
from typing import Final


def _get_bool(env_var: str, default: bool) -> bool:
	value = os.getenv(env_var)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


USE_ELASTIC: Final[bool] = _get_bool("USE_ELASTIC", False)
USE_VERTEX: Final[bool] = _get_bool("USE_VERTEX", False)

ELASTIC_URL: Final[str] = os.getenv("ELASTIC_URL", "http://localhost:9200")
ELASTIC_USERNAME: Final[str] = os.getenv("ELASTIC_USERNAME", "")
ELASTIC_PASSWORD: Final[str] = os.getenv("ELASTIC_PASSWORD", "")

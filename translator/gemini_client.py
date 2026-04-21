from __future__ import annotations

import logging
import re
import time
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Maximum number of retries for rate-limited requests
_MAX_RETRIES = 12
# Fallback wait (seconds) when no retry_delay is provided by the API
_FALLBACK_WAIT = 60
# How many consecutive 429s (each after a full wait) before we assume RPD exhaustion.
# RPM quota clears after one wait cycle; repeated 429s strongly indicate a daily cap.
_MAX_CONSECUTIVE_429 = 3

# Substrings in 429 messages that indicate a daily (RPD) quota exhaustion.
# These are unrecoverable until midnight Pacific time — no point retrying.
_RPD_KEYWORDS = (
    "per_day",
    "per day",
    "daily",
    "GenerateRequestsPerDay",
    "requests_per_day",
)


class DailyQuotaExhaustedError(RuntimeError):
    """Raised when the Gemini daily request quota (RPD) has been exhausted."""
    pass


def _parse_retry_delay(exc: Exception) -> float:
    """Extract the suggested retry delay (seconds) from a 429 exception message."""
    text = str(exc)
    # The API embeds e.g. "retry_delay { seconds: 57 }" in the error message
    m = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', text)
    if m:
        return float(m.group(1)) + 2.0   # small buffer
    # Also handle "Please retry in N.NNs"
    m2 = re.search(r'retry in (\d+\.?\d*)s', text)
    if m2:
        return float(m2.group(1)) + 2.0
    return _FALLBACK_WAIT


class GeminiClient:
    """
    Thin wrapper around the google-genai SDK with:
    - configurable model
    - rate-limit-aware retry: honours the retry_delay returned by the API
    - exponential backoff for non-rate-limit transient errors
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash") -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required.")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.4,
        max_output_tokens: int = 16384,
    ) -> str:
        """Generate text, retrying on rate-limits and transient errors."""
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system_instruction,
        )

        backoff = 5.0
        consecutive_429 = 0
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as exc:
                is_last = attempt == _MAX_RETRIES
                exc_str = str(exc)
                is_rate_limit = "429" in exc_str or "ResourceExhausted" in exc_str or "RESOURCE_EXHAUSTED" in exc_str

                if is_last:
                    raise

                if is_rate_limit:
                    exc_str_lower = exc_str.lower()
                    if any(kw.lower() in exc_str_lower for kw in _RPD_KEYWORDS):
                        raise DailyQuotaExhaustedError(
                            "Daily Gemini quota (RPD) exhausted. "
                            "The free tier resets at midnight Pacific time. "
                            f"Original error: {exc_str[:300]}"
                        ) from exc

                    consecutive_429 += 1
                    if consecutive_429 >= _MAX_CONSECUTIVE_429:
                        raise DailyQuotaExhaustedError(
                            f"Got {consecutive_429} consecutive 429 responses — "
                            "daily RPD quota is likely exhausted. "
                            "The free tier resets at midnight Pacific time."
                        ) from exc

                    wait = _parse_retry_delay(exc)
                    logger.warning(
                        "Rate limit hit (attempt %d/%d, consecutive=%d). Waiting %.0fs…",
                        attempt, _MAX_RETRIES, consecutive_429, wait,
                    )
                else:
                    consecutive_429 = 0  # non-429 error resets the streak
                    wait = backoff
                    backoff = min(backoff * 2, 120)
                    logger.warning(
                        "Transient error (attempt %d/%d): %s — retrying in %.0fs",
                        attempt, _MAX_RETRIES, exc_str[:120], wait,
                    )

                time.sleep(wait)

        raise RuntimeError("generate() exhausted all retries")  # unreachable

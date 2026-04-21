from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

from .epub_handler import Chapter
from .gemini_client import GeminiClient
from .glossary import Glossary
from .prompts import EVALUATION_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# How much of each chapter we send to the evaluator (avoids huge token costs)
_MAX_EVAL_CHARS = 3000


class Evaluator:
    """
    Second-pass AI quality check: compares the source chapter against the
    translation and returns a numeric score plus structured feedback.
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        self.client = gemini_client

    # ------------------------------------------------------------------

    def evaluate(
        self,
        original: Chapter,
        translated_title: str,
        translated_content: str,
        glossary: Optional[Glossary] = None,
    ) -> Tuple[float, str, str]:
        """
        Returns (score, feedback, issues).
        score  — float 0-100
        feedback — short prose summary
        issues   — bullet-point list of concrete problems
        """
        glossary_section = ""
        if glossary:
            text = glossary.to_prompt_text()
            if text:
                glossary_section = text

        # Truncate to keep evaluation costs reasonable
        src_content = original.content[:_MAX_EVAL_CHARS]
        if len(original.content) > _MAX_EVAL_CHARS:
            src_content += "\n...[truncated]"

        tgt_content = translated_content[:_MAX_EVAL_CHARS]
        if len(translated_content) > _MAX_EVAL_CHARS:
            tgt_content += "\n...[truncated]"

        prompt = EVALUATION_PROMPT_TEMPLATE.format(
            glossary_section=glossary_section,
            source_title=original.title,
            source_content=src_content,
            translated_title=translated_title,
            translated_content=tgt_content,
        )

        try:
            response = self.client.generate(
                prompt=prompt,
                temperature=0.1,
                max_output_tokens=2048,
            )
            return self._parse(response)
        except Exception as exc:
            logger.warning("Evaluation failed for '%s': %s", original.title, exc)
            return 0.0, "Evaluation failed due to API error.", str(exc)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(response: str) -> Tuple[float, str, str]:
        score = 0.0
        feedback = ""
        issues = ""

        if "###SCORE###" in response:
            part = response.split("###SCORE###", 1)[1]
            chunk = part.split("###", 1)[0].strip()
            nums = re.findall(r"\d+(?:\.\d+)?", chunk)
            if nums:
                score = min(float(nums[0]), 100.0)

        if "###FEEDBACK###" in response:
            part = response.split("###FEEDBACK###", 1)[1]
            feedback = part.split("###", 1)[0].strip()

        if "###ISSUES###" in response:
            part = response.split("###ISSUES###", 1)[1]
            issues = part.strip()

        return score, feedback, issues

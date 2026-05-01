"""
translator/scanner.py — Pre-translation book scanner.

Scans an EPUB and calls Gemini to auto-generate draft glossary and
relationship files.  The user can then review/edit these files before
the main translation run begins.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Tuple

import yaml

from .epub_handler import Chapter, EpubHandler
from .gemini_client import GeminiClient
from .prompts import SCAN_SYSTEM_INSTRUCTION, SCAN_EXTRACTION_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# How many chapters to sample when scanning (spread evenly across the book)
_DEFAULT_SCAN_CHAPTERS = 6
# Max characters taken from each sampled chapter (keeps token count reasonable)
_MAX_CHARS_PER_CHAPTER = 3_000


class BookScanner:
    """
    Scans an EPUB and produces draft glossary + relationship YAML files.

    Workflow
    --------
    1. Load the EPUB and sample a few chapters evenly across the book.
    2. Send the samples to Gemini with a structured extraction prompt.
    3. Parse the response into two YAML dicts (glossary / relationships).
    4. Write them to disk so the user can edit before translating.
    """

    def __init__(self, gemini_client: GeminiClient, source_language: str = "en") -> None:
        self.client = gemini_client
        self.source_language = source_language.lower()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_epub(
        self,
        epub_path: str,
        num_chapters: int = _DEFAULT_SCAN_CHAPTERS,
    ) -> Tuple[dict, dict]:
        """
        Analyse ``epub_path`` and return ``(glossary_data, relationships_data)``.

        Both dicts are ready to be passed to :meth:`save_glossary` /
        :meth:`save_relationships`.
        """
        handler = EpubHandler()
        chapters = handler.load(epub_path)

        sampled = _sample_chapters(chapters, num_chapters)
        logger.info(
            "Scanner: sampling %d of %d chapters from '%s'",
            len(sampled), len(chapters), epub_path,
        )

        chapters_text = _format_chapters_for_scan(sampled)
        lang_name = _language_display_name(self.source_language)

        prompt = SCAN_EXTRACTION_PROMPT_TEMPLATE.format(
            source_language_name=lang_name,
            chapters_text=chapters_text,
        )

        logger.info("Scanner: calling Gemini for extraction…")
        response = self.client.generate(
            prompt=prompt,
            system_instruction=SCAN_SYSTEM_INSTRUCTION,
            temperature=0.2,
            max_output_tokens=8192,
        )

        glossary_data, relationships_data = _parse_scan_response(response)
        logger.info(
            "Scanner: extracted %d glossary entries, %d relationships",
            len(glossary_data.get("entries", [])),
            len(relationships_data.get("relationships", [])),
        )
        return glossary_data, relationships_data

    def save_glossary(self, data: dict, filepath: str) -> None:
        """Write glossary data to a YAML file with a human-friendly header comment."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Auto-generated glossary — PLEASE REVIEW AND EDIT before translating.\n"
            "# Add, remove, or correct entries as needed.\n"
            "# Format:\n"
            "#   source: original term\n"
            "#   target: Vietnamese translation\n"
            "#   context: type (nhân vật / địa danh / kỹ năng / chức vị / ...)\n"
            "#   notes: optional notes\n\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def save_relationships(self, data: dict, filepath: str) -> None:
        """Write relationships data to a YAML file with a human-friendly header comment."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Auto-generated relationship matrix — PLEASE REVIEW AND EDIT before translating.\n"
            "# Each entry defines how character A addresses themselves and B when speaking to B.\n"
            "# Format:\n"
            "#   char_a / char_b: character names\n"
            "#   a_calls_self: pronoun A uses for themselves (e.g. anh, tôi, ta, tao)\n"
            "#   a_calls_b: pronoun A uses for B (e.g. em, bạn, cậu, ngươi, mày)\n"
            "#   context: relationship type (e.g. Anh-Em, Bạn bè, Senpai-Kohai)\n\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _language_display_name(lang: str) -> str:
    if lang in ("jp", "ja", "japanese"):
        return "Tiếng Nhật (Japanese)"
    return "Tiếng Anh (English)"


def _sample_chapters(chapters: List[Chapter], n: int) -> List[Chapter]:
    """Return at most *n* chapters spread evenly across the book."""
    if not chapters:
        return []
    if len(chapters) <= n:
        return chapters
    step = len(chapters) / n
    return [chapters[int(i * step)] for i in range(n)]


def _format_chapters_for_scan(chapters: List[Chapter]) -> str:
    parts: List[str] = []
    for i, ch in enumerate(chapters, 1):
        content = ch.content[:_MAX_CHARS_PER_CHAPTER]
        if len(ch.content) > _MAX_CHARS_PER_CHAPTER:
            content += "\n[... nội dung còn lại được rút gọn để tiết kiệm token ...]"
        parts.append(f"═══ ĐOẠN TRÍCH {i}: {ch.title} ═══\n{content}")
    return "\n\n".join(parts)


def _parse_scan_response(response: str) -> Tuple[dict, dict]:
    """
    Parse the ###GLOSSARY### and ###RELATIONSHIPS### sections from the
    Gemini response.  Returns safe defaults if parsing fails.
    """
    glossary_data: dict = {"entries": []}
    relationships_data: dict = {"relationships": []}

    # ── Glossary section ──────────────────────────────────────────────
    gloss_match = re.search(
        r"###GLOSSARY###\s*\n(.*?)(?=###RELATIONSHIPS###|$)",
        response,
        re.DOTALL,
    )
    if gloss_match:
        gloss_yaml = _strip_comments(gloss_match.group(1).strip())
        try:
            parsed = yaml.safe_load(gloss_yaml)
            if isinstance(parsed, dict) and "entries" in parsed and isinstance(parsed["entries"], list):
                glossary_data = parsed
            else:
                logger.warning("Scanner: glossary YAML parsed but has unexpected shape")
        except yaml.YAMLError as exc:
            logger.warning("Scanner: failed to parse glossary YAML: %s", exc)

    # ── Relationships section ─────────────────────────────────────────
    rel_match = re.search(
        r"###RELATIONSHIPS###\s*\n(.*?)$",
        response,
        re.DOTALL,
    )
    if rel_match:
        rel_yaml = _strip_comments(rel_match.group(1).strip())
        try:
            parsed = yaml.safe_load(rel_yaml)
            if isinstance(parsed, dict) and "relationships" in parsed and isinstance(parsed["relationships"], list):
                relationships_data = parsed
            else:
                logger.warning("Scanner: relationships YAML parsed but has unexpected shape")
        except yaml.YAMLError as exc:
            logger.warning("Scanner: failed to parse relationships YAML: %s", exc)

    return glossary_data, relationships_data


def _strip_comments(text: str) -> str:
    """Remove YAML comment lines so yaml.safe_load doesn't trip on them."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    return "\n".join(lines)

"""
translator/style_reference.py — Writing-style reference feature.

Workflow
--------
1. Place one or more EPUB (or .txt) files in ``data/style_references/``.
2. On the first run, BookStyleAnalyzer samples chapters from each file,
   calls Gemini to extract a detailed style profile, and caches the result
   as ``<stem>.style.yaml`` in the same directory.
3. The cached profile is loaded on subsequent runs (no extra API call).
4. StyleReference.to_prompt_text() produces a section that is injected into
   every translation prompt, instructing the model to mimic that writing style.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml

from .epub_handler import EpubHandler
from .gemini_client import GeminiClient
from .prompts import STYLE_ANALYSIS_SYSTEM_INSTRUCTION, STYLE_ANALYSIS_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# How many chapters to sample when analysing a style reference
_DEFAULT_SAMPLE_CHAPTERS = 5
# Max characters taken from each sampled chapter
_MAX_CHARS_PER_CHAPTER = 3_000


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StyleProfile:
    source_name: str          # Display name (file stem)
    source_path: str          # Absolute path to the original file
    tone: str = ""
    sentence_structure: str = ""
    vocabulary: str = ""
    narrative_perspective: str = ""
    dialogue_style: str = ""
    pacing: str = ""
    distinctive_features: str = ""
    style_guide: str = ""
    example_sentences: str = ""

    def to_prompt_text(self) -> str:
        """Render the profile as a concise style guide for injection into translation prompts."""
        lines = [
            f"=== VĂN PHONG THAM KHẢO: «{self.source_name}» ===",
            "Hãy dịch sao cho văn phong tiếng Việt phản ánh đặc trưng của tác phẩm tham khảo dưới đây.\n",
        ]
        if self.tone:
            lines.append(f"Giọng điệu    : {self.tone}")
        if self.sentence_structure:
            lines.append(f"Cấu trúc câu  : {self.sentence_structure}")
        if self.vocabulary:
            lines.append(f"Từ vựng       : {self.vocabulary}")
        if self.narrative_perspective:
            lines.append(f"Ngôi kể       : {self.narrative_perspective}")
        if self.dialogue_style:
            lines.append(f"Hội thoại     : {self.dialogue_style}")
        if self.pacing:
            lines.append(f"Nhịp điệu     : {self.pacing}")
        if self.distinctive_features:
            lines.append("\nĐặc điểm nổi bật:")
            lines.append(self.distinctive_features.strip())
        if self.style_guide:
            lines.append("\nHướng dẫn dịch thuật:")
            lines.append(self.style_guide.strip())
        if self.example_sentences:
            lines.append("\nCâu ví dụ thể hiện văn phong:")
            lines.append(self.example_sentences.strip())
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Style analyser (calls Gemini once, then caches)
# ─────────────────────────────────────────────────────────────────────────────

class BookStyleAnalyzer:
    """Analyse a book file and produce/cache a StyleProfile."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self.client = gemini_client

    def analyze(
        self,
        book_path: str,
        cache_path: str,
        num_chapters: int = _DEFAULT_SAMPLE_CHAPTERS,
    ) -> StyleProfile:
        """
        Return a StyleProfile for ``book_path``.

        If ``cache_path`` already exists, load from cache (no API call).
        Otherwise, sample the book, call Gemini, save cache, and return.
        """
        cache = Path(cache_path)
        stem = Path(book_path).stem

        if cache.exists():
            logger.info("Style cache found: %s — skipping analysis.", cache)
            return self._load_cache(cache, stem, book_path)

        logger.info("Analysing writing style of '%s'…", Path(book_path).name)
        profile = self._run_analysis(book_path, stem, num_chapters)
        self._save_cache(profile, cache)
        return profile

    # ------------------------------------------------------------------

    def _run_analysis(self, book_path: str, stem: str, num_chapters: int) -> StyleProfile:
        chapters_text = self._sample_book(book_path, num_chapters)
        prompt = STYLE_ANALYSIS_PROMPT_TEMPLATE.format(
            reference_name=stem,
            chapters_text=chapters_text,
        )
        raw = self.client.generate(
            prompt=prompt,
            system_instruction=STYLE_ANALYSIS_SYSTEM_INSTRUCTION,
            temperature=0.2,
            max_output_tokens=4096,
        )
        return self._parse_response(raw, stem, book_path)

    def _sample_book(self, book_path: str, num_chapters: int) -> str:
        """Load the book and return formatted excerpt text."""
        path = Path(book_path)
        if path.suffix.lower() in (".epub",):
            return self._sample_epub(book_path, num_chapters)
        elif path.suffix.lower() in (".txt",):
            return self._sample_txt(book_path, num_chapters)
        else:
            raise ValueError(
                f"Unsupported style reference format: '{path.suffix}'. "
                "Use .epub or .txt files."
            )

    def _sample_epub(self, epub_path: str, num_chapters: int) -> str:
        handler = EpubHandler()
        chapters = handler.load(epub_path)
        sampled = _sample_evenly(chapters, num_chapters)
        parts = []
        for i, ch in enumerate(sampled, 1):
            excerpt = ch.content[:_MAX_CHARS_PER_CHAPTER]
            parts.append(f"---[ ĐOẠN TRÍCH {i}: {ch.title} ]---\n{excerpt}")
        return "\n\n".join(parts)

    def _sample_txt(self, txt_path: str, num_chapters: int) -> str:
        text = Path(txt_path).read_text(encoding="utf-8", errors="replace")
        # Split on blank lines into paragraphs, then bucket into chunks
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        total = len(paragraphs)
        if total == 0:
            return text[:_MAX_CHARS_PER_CHAPTER * num_chapters]

        step = max(1, total // num_chapters)
        indices = list(range(0, total, step))[:num_chapters]
        parts = []
        for i, idx in enumerate(indices, 1):
            chunk = "\n\n".join(paragraphs[idx: idx + 10])  # ~10 paragraphs per sample
            parts.append(f"---[ ĐOẠN TRÍCH {i} ]---\n{chunk[:_MAX_CHARS_PER_CHAPTER]}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(raw: str, stem: str, source_path: str) -> StyleProfile:
        """Parse Gemini's ###STYLE_PROFILE### YAML block into a StyleProfile."""
        profile = StyleProfile(source_name=stem, source_path=source_path)

        match = re.search(r"###STYLE_PROFILE###\s*(.*)", raw, re.DOTALL)
        if not match:
            logger.warning("Could not locate ###STYLE_PROFILE### block in response; using raw text.")
            profile.style_guide = raw.strip()
            return profile

        yaml_text = match.group(1).strip()
        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError as exc:
            logger.warning("YAML parse error in style analysis response: %s", exc)
            profile.style_guide = yaml_text
            return profile

        profile.tone                 = data.get("tone", "")
        profile.sentence_structure   = data.get("sentence_structure", "")
        profile.vocabulary           = data.get("vocabulary", "")
        profile.narrative_perspective = data.get("narrative_perspective", "")
        profile.dialogue_style       = data.get("dialogue_style", "")
        profile.pacing               = data.get("pacing", "")
        profile.distinctive_features = str(data.get("distinctive_features", "")).strip()
        profile.style_guide          = str(data.get("style_guide", "")).strip()
        profile.example_sentences    = str(data.get("example_sentences", "")).strip()
        return profile

    # ------------------------------------------------------------------

    @staticmethod
    def _save_cache(profile: StyleProfile, cache_path: Path) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "source_name": profile.source_name,
            "source_path": profile.source_path,
            "tone": profile.tone,
            "sentence_structure": profile.sentence_structure,
            "vocabulary": profile.vocabulary,
            "narrative_perspective": profile.narrative_perspective,
            "dialogue_style": profile.dialogue_style,
            "pacing": profile.pacing,
            "distinctive_features": profile.distinctive_features,
            "style_guide": profile.style_guide,
            "example_sentences": profile.example_sentences,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            header = (
                "# Auto-generated style profile — you may edit this file to fine-tune the style guide.\n"
                "# Delete this file to force re-analysis from the source book.\n"
            )
            f.write(header)
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        logger.info("Style profile cached → %s", cache_path)

    @staticmethod
    def _load_cache(cache_path: Path, stem: str, source_path: str) -> StyleProfile:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        profile = StyleProfile(
            source_name=data.get("source_name", stem),
            source_path=data.get("source_path", source_path),
            tone=data.get("tone", ""),
            sentence_structure=data.get("sentence_structure", ""),
            vocabulary=data.get("vocabulary", ""),
            narrative_perspective=data.get("narrative_perspective", ""),
            dialogue_style=data.get("dialogue_style", ""),
            pacing=data.get("pacing", ""),
            distinctive_features=str(data.get("distinctive_features", "")).strip(),
            style_guide=str(data.get("style_guide", "")).strip(),
            example_sentences=str(data.get("example_sentences", "")).strip(),
        )
        return profile


# ─────────────────────────────────────────────────────────────────────────────
# StyleReference — aggregates one or more profiles
# ─────────────────────────────────────────────────────────────────────────────

class StyleReference:
    """
    Holds one or more StyleProfiles and provides a single prompt section
    that is injected into every translation request.
    """

    def __init__(self) -> None:
        self.profiles: List[StyleProfile] = []

    def add_profile(self, profile: StyleProfile) -> None:
        self.profiles.append(profile)

    def is_empty(self) -> bool:
        return len(self.profiles) == 0

    def to_prompt_text(self) -> str:
        if not self.profiles:
            return ""
        sections = [p.to_prompt_text() for p in self.profiles]
        return "\n\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sample_evenly(items: list, n: int) -> list:
    """Return up to n items sampled evenly across the list."""
    if not items:
        return []
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]

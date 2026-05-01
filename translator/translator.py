from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .checkpoint import CheckpointManager, restore_results
from .epub_handler import Chapter, EpubHandler
from .evaluator import Evaluator
from .gemini_client import GeminiClient, DailyQuotaExhaustedError
from .glossary import Glossary
from .pronoun_system import RelationshipMatrix
from .prompts import get_system_instruction, TRANSLATION_PROMPT_TEMPLATE, BATCH_TRANSLATION_PROMPT_TEMPLATE, BATCH_CHAPTER_ENTRY

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    chapter: Chapter
    translated_title: str
    translated_content: str
    score: Optional[float] = None
    feedback: Optional[str] = None
    issues: Optional[str] = None
    needs_review: bool = False
    parse_failed: bool = False  # True when batch parse fell back to raw text


class Translator:
    """
    Orchestrates the full EN → VI translation pipeline:
      Glossary → Context (past chapters) → Translation → AI Evaluation
    """

    def __init__(
        self,
        gemini_client: GeminiClient,
        glossary: Optional[Glossary] = None,
        relationship_matrix: Optional[RelationshipMatrix] = None,
        context_window: int = 3,
        review_threshold: float = 75.0,
        max_output_tokens: int = 65536,
        batch_chunk_size: int = 5,
        source_language: str = "en",
    ) -> None:
        self.client = gemini_client
        self.glossary = glossary or Glossary()
        self.relationships = relationship_matrix or RelationshipMatrix()
        self.context_window = max(0, context_window)
        self.review_threshold = review_threshold
        self.max_output_tokens = max_output_tokens
        self.batch_chunk_size = max(1, batch_chunk_size)
        self.source_language = source_language
        self._system_instruction = get_system_instruction(source_language)
        self.evaluator = Evaluator(gemini_client)
        # Seed chapters from previously translated volumes (loaded via load_prior_volumes)
        self._seed_results: List[TranslationResult] = []

    # ------------------------------------------------------------------
    # Prior-volume context seeding
    # ------------------------------------------------------------------

    def load_prior_volumes(self, epub_paths: List[str]) -> int:
        """
        Load already-translated EPUB files so their final chapters can be
        used as context when translating the first chapters of a new volume.

        EPUBs are processed in the order given, so pass them sorted by
        volume number (vol1.epub, vol2.epub, …).

        Returns the total number of chapters loaded.
        """
        total = 0
        for path in epub_paths:
            handler = EpubHandler()
            try:
                chapters = handler.load(path)
            except Exception as exc:
                logger.warning("Could not load prior volume '%s': %s", path, exc)
                continue
            for ch in chapters:
                # Treat the chapter content as already-translated Vietnamese text
                self._seed_results.append(
                    TranslationResult(
                        chapter=ch,
                        translated_title=ch.title,
                        translated_content=ch.content,
                    )
                )
            logger.info("Seeded %d chapters from prior volume: %s", len(chapters), path)
            logger.debug(
                "  (context_window=%d → at most %d chapter(s) will be used per prompt)",
                self.context_window, self.context_window,
            )
            total += len(chapters)
        return total

    # ------------------------------------------------------------------
    # Batch translation (entire volume = 1 API request)
    # ------------------------------------------------------------------

    def translate_chapters_batch(
        self,
        chapters: List[Chapter],
        seed_results: List[TranslationResult],
    ) -> List[TranslationResult]:
        """
        Translate all chapters in a single API call.
        Returns one TranslationResult per chapter (no evaluation scores).
        """
        glossary_section = self.glossary.to_prompt_text()
        pronoun_section = self.relationships.to_prompt_text()
        context_section = self._build_context_section(seed_results)

        chapters_block = "\n\n".join(
            BATCH_CHAPTER_ENTRY.format(
                index=i + 1,
                title=ch.title,
                content=ch.content,
            )
            for i, ch in enumerate(chapters)
        )

        prompt = BATCH_TRANSLATION_PROMPT_TEMPLATE.format(
            glossary_section=glossary_section,
            pronoun_section=pronoun_section,
            context_section=context_section,
            chapter_count=len(chapters),
            chapters_block=chapters_block,
        )

        logger.info("Batch-translating %d chapters in 1 request…", len(chapters))
        raw = self.client.generate(
            prompt=prompt,
            system_instruction=self._system_instruction,
            temperature=0.4,
            max_output_tokens=self.max_output_tokens,
        )

        return self._parse_batch_response(raw, chapters)

    @staticmethod
    def _parse_batch_response(
        response: str, chapters: List[Chapter]
    ) -> List[TranslationResult]:
        """Parse a multi-chapter response into individual TranslationResults."""
        import re

        results: List[TranslationResult] = []

        # Split on ###CHAPTER[N]### markers
        parts = re.split(r"###CHAPTER\[(\d+)\]###", response)
        # parts = ['preamble', '1', 'body1', '2', 'body2', ...]
        chapter_bodies: dict[int, str] = {}
        for i in range(1, len(parts) - 1, 2):
            idx = int(parts[i])
            body = parts[i + 1]
            chapter_bodies[idx] = body

        for i, chapter in enumerate(chapters):
            body = chapter_bodies.get(i + 1, "")
            if body and "###TITLE###" in body and "###CONTENT###" in body:
                after_title = body.split("###TITLE###", 1)[1]
                title_part, content_part = after_title.split("###CONTENT###", 1)
                title = title_part.strip() or chapter.title
                content = content_part.strip()
            else:
                # Fallback: use original title and whatever text was returned
                logger.warning(
                    "Could not parse batch response for chapter %d (%s) — will retry individually",
                    i + 1, chapter.title,
                )
                title = chapter.title
                content = body.strip() if body.strip() else chapter.content

            results.append(
                TranslationResult(
                    chapter=chapter,
                    translated_title=title,
                    translated_content=content,
                    parse_failed=not (body and "###TITLE###" in body and "###CONTENT###" in body),
                )
            )

        # If fewer chapters came back than expected, pad — also mark as failed
        for i in range(len(results), len(chapters)):
            logger.warning(
                "Batch response missing chapter %d (%s) — will retry individually",
                i + 1, chapters[i].title,
            )
            results.append(
                TranslationResult(
                    chapter=chapters[i],
                    translated_title=chapters[i].title,
                    translated_content=chapters[i].content,
                    parse_failed=True,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Chapter-level translation
    # ------------------------------------------------------------------

    def translate_chapter(
        self,
        chapter: Chapter,
        past_results: List[TranslationResult],
    ) -> TranslationResult:
        """Translate a single chapter, using past results as context."""
        glossary_section = self.glossary.to_prompt_text()
        pronoun_section = self.relationships.to_prompt_text()
        context_section = self._build_context_section(past_results)

        prompt = TRANSLATION_PROMPT_TEMPLATE.format(
            glossary_section=glossary_section,
            pronoun_section=pronoun_section,
            context_section=context_section,
            chapter_title=chapter.title,
            chapter_content=chapter.content,
        )

        logger.info("Translating: %s", chapter.title)
        raw = self.client.generate(
            prompt=prompt,
            system_instruction=self._system_instruction,
            temperature=0.4,
            max_output_tokens=self.max_output_tokens,
        )

        title, content = self._parse_response(raw, chapter)
        return TranslationResult(
            chapter=chapter,
            translated_title=title,
            translated_content=content,
        )

    # ------------------------------------------------------------------
    # Full EPUB translation
    # ------------------------------------------------------------------

    def translate_epub(
        self,
        input_path: str,
        output_path: str,
        start_chapter: int = 0,
        end_chapter: Optional[int] = None,
        evaluate: bool = True,
        batch_mode: bool = False,
        resume: bool = True,
    ) -> List[TranslationResult]:
        """
        Translate an entire EPUB and write the output file.

        batch_mode=True  → chapters sent in chunks (saves RPD).
        batch_mode=False → one request per chapter (default).
        resume=True      → load prior progress from checkpoint and skip done chapters.

        Returns a list of TranslationResult (one per translated chapter).
        """
        handler = EpubHandler()
        all_chapters = handler.load(input_path)

        end = end_chapter if end_chapter is not None else len(all_chapters)
        chapters_to_translate = all_chapters[start_chapter:end]

        logger.info(
            "%s %d/%d chapters  [%d → %d)",
            "Batch-translating" if batch_mode else "Translating",
            len(chapters_to_translate), len(all_chapters), start_chapter, end,
        )

        # ── Checkpoint: load prior progress ──────────────────────────────
        ckpt = CheckpointManager(output_path)
        saved_map: dict = ckpt.load() if resume else {}
        already_done: List[TranslationResult] = restore_results(saved_map, all_chapters)
        done_ids = {r.chapter.id for r in already_done}
        pending = [ch for ch in chapters_to_translate if ch.id not in done_ids]

        if already_done:
            logger.info(
                "Resuming: %d/%d chapter(s) already translated, %d remaining.",
                len(already_done), len(chapters_to_translate), len(pending),
            )

        # Seed with prior-volume chapters so context window reaches across volumes
        seed_results: List[TranslationResult] = list(self._seed_results)

        if batch_mode:
            chunk_size = self.batch_chunk_size
            total = len(pending)
            num_chunks = (total + chunk_size - 1) // chunk_size
            if total:
                logger.info(
                    "Batch-translating %d chapters in %d chunk(s) of ≤%d chapters each…",
                    total, num_chunks, chunk_size,
                )
            chapter_results: List[TranslationResult] = list(already_done)
            for chunk_idx in range(num_chunks):
                chunk = pending[chunk_idx * chunk_size:(chunk_idx + 1) * chunk_size]
                logger.info(
                    "  Chunk %d/%d: chapters %d–%d (%s … %s)",
                    chunk_idx + 1, num_chunks,
                    chunk_idx * chunk_size + 1, chunk_idx * chunk_size + len(chunk),
                    chunk[0].title, chunk[-1].title,
                )
                try:
                    chunk_results = self.translate_chapters_batch(
                        chunk, seed_results + chapter_results
                    )
                except DailyQuotaExhaustedError:
                    # Checkpoint already has everything completed so far — just propagate
                    logger.error(
                        "Daily RPD quota exhausted after chunk %d/%d. "
                        "Progress has been saved. Re-run tomorrow to resume.",
                        chunk_idx + 1, num_chunks,
                    )
                    raise
                # Auto-retry chapters where batch parse failed — translate one by one
                failed = [r for r in chunk_results if r.parse_failed]
                if failed:
                    logger.warning(
                        "  Retrying %d chapter(s) that failed to parse from batch…",
                        len(failed),
                    )
                    retry_ctx = seed_results + chapter_results
                    for fail_result in failed:
                        logger.info("  Retrying: %s", fail_result.chapter.title)
                        retried = self.translate_chapter(fail_result.chapter, retry_ctx)
                        retry_ctx = retry_ctx + [retried]
                        # Replace in chunk_results
                        for j, cr in enumerate(chunk_results):
                            if cr.chapter.id == fail_result.chapter.id:
                                chunk_results[j] = retried
                                break
                chapter_results.extend(chunk_results)
                # Save checkpoint after every chunk (only successfully parsed results)
                for r in chunk_results:
                    ckpt.save_result(r, input_path, output_path)
            # Evaluation costs additional requests — skip in batch mode unless explicitly wanted
            if evaluate:
                logger.info(
                    "Note: evaluation skipped in batch mode to preserve RPD quota. "
                    "Use --no-evaluate to suppress this message."
                )
        else:
            chapter_results = list(already_done)
            for idx, chapter in enumerate(pending, start=1):
                logger.info(
                    "[%d/%d] %s",
                    len(already_done) + idx, len(chapters_to_translate), chapter.title,
                )

                result = self.translate_chapter(chapter, seed_results + chapter_results)

                if evaluate:
                    score, feedback, issues = self.evaluator.evaluate(
                        original=chapter,
                        translated_title=result.translated_title,
                        translated_content=result.translated_content,
                        glossary=self.glossary,
                    )
                    result.score = score
                    result.feedback = feedback
                    result.issues = issues
                    result.needs_review = score < self.review_threshold

                    if result.needs_review:
                        logger.warning(
                            "  [REVIEW NEEDED] Score: %.0f/100  — %s",
                            score, feedback[:120] if feedback else "",
                        )
                    else:
                        logger.info("  Score: %.0f/100", score)

                chapter_results.append(result)
                # Save checkpoint after every chapter
                ckpt.save_result(result, input_path, output_path)

        # Re-order results to match original chapter order
        order = {ch.id: i for i, ch in enumerate(all_chapters)}
        chapter_results.sort(key=lambda r: order.get(r.chapter.id, 99999))

        # Build translated chapter list and save EPUB
        translated = [
            (r.chapter, r.translated_title, _text_to_html(r.translated_content))
            for r in chapter_results
        ]
        handler.save(output_path, translated)

        # Clean up checkpoint on success
        ckpt.delete()

        return chapter_results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_context_section(self, past_results: List[TranslationResult]) -> str:
        window = past_results[-self.context_window:] if self.context_window else []
        if not window:
            return ""
        logger.info(
            "Context window: using %d/%d available chapter(s) as context",
            len(window), len(past_results),
        )
        lines = [f"=== NGỮ CẢNH — {len(window)} CHƯƠNG TRƯỚC ==="]
        for prev in window:
            lines.append(f"\n[{prev.translated_title}]")
            excerpt = prev.translated_content[:600]
            if len(prev.translated_content) > 600:
                excerpt += "\n...[còn tiếp]"
            lines.append(excerpt)
        return "\n".join(lines)

    @staticmethod
    def _parse_response(response: str, chapter: Chapter) -> Tuple[str, str]:
        """Extract ###TITLE### and ###CONTENT### blocks from the model's reply."""
        title = chapter.title
        content = response

        if "###TITLE###" in response and "###CONTENT###" in response:
            after_title_tag = response.split("###TITLE###", 1)[1]
            title_part, rest = after_title_tag.split("###CONTENT###", 1)
            title = title_part.strip() or title
            content = rest.strip()

        return title, content


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────

def _text_to_html(text: str) -> str:
    """Convert plain translated text (possibly with markdown headings) to XHTML."""
    paragraphs = [line for line in text.splitlines() if line.strip()]
    parts: List[str] = []
    for para in paragraphs:
        stripped = para.strip()
        # Markdown-style headings (#, ##, ###)
        m = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            heading_text = _escape_xml(m.group(2).strip())
            parts.append(f"<h{level}>{heading_text}</h{level}>")
        else:
            parts.append(f"<p>{_escape_xml(stripped)}</p>")
    return "\n".join(parts)


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )

"""
Checkpoint manager — persist translation progress to disk so runs can be
resumed after interruption (rate-limit, Ctrl-C, crash, etc.).

Checkpoint file: <output_path>.checkpoint.json
Format:
  {
    "input_path": "...",
    "output_path": "...",
    "results": {
      "<chapter_id>": {
        "translated_title": "...",
        "translated_content": "...",
        "score": 85.0 | null,
        "feedback": "..." | null,
        "issues": "..." | null,
        "needs_review": false
      },
      ...
    }
  }
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .translator import TranslationResult

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Save and restore per-chapter translation progress."""

    def __init__(self, output_path: str) -> None:
        self.checkpoint_path = Path(output_path).with_suffix(
            Path(output_path).suffix + ".checkpoint.json"
        )
        self._data: dict = {}

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, dict]:
        """
        Return previously saved results keyed by chapter id, or {} if none.
        Silently ignores corrupt/missing files.
        """
        if not self.checkpoint_path.exists():
            return {}
        try:
            with open(self.checkpoint_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            results = raw.get("results", {})
            logger.info(
                "Resuming from checkpoint: %d chapter(s) already done (%s)",
                len(results), self.checkpoint_path,
            )
            self._data = raw
            return results
        except Exception as exc:
            logger.warning("Could not read checkpoint file (%s): %s — starting fresh", self.checkpoint_path, exc)
            return {}

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_result(self, result: "TranslationResult", input_path: str, output_path: str) -> None:
        """Append/update one result and flush to disk.
        Results with parse_failed=True are NOT saved so they are retried on the next run.
        """
        if result.parse_failed:
            return  # don't persist a failed result — it will be retried
        if "results" not in self._data:
            self._data = {
                "input_path": str(input_path),
                "output_path": str(output_path),
                "results": {},
            }
        self._data["results"][result.chapter.id] = {
            "translated_title": result.translated_title,
            "translated_content": result.translated_content,
            "score": result.score,
            "feedback": result.feedback,
            "issues": result.issues,
            "needs_review": result.needs_review,
        }
        try:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.checkpoint_path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Could not write checkpoint: %s", exc)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def delete(self) -> None:
        """Remove the checkpoint file after a successful run."""
        try:
            if self.checkpoint_path.exists():
                os.remove(self.checkpoint_path)
                logger.info("Checkpoint removed: %s", self.checkpoint_path)
        except Exception as exc:
            logger.warning("Could not remove checkpoint file: %s", exc)


def restore_results(
    saved: Dict[str, dict],
    all_chapters: list,
) -> "list[TranslationResult]":
    """
    Reconstruct TranslationResult objects from saved checkpoint data,
    preserving original chapter objects from the loaded EPUB.
    Returns results in the same order as all_chapters.
    """
    from .translator import TranslationResult  # local import to avoid circular

    restored = []
    id_map = {ch.id: ch for ch in all_chapters}
    for ch_id, entry in saved.items():
        chapter = id_map.get(ch_id)
        if chapter is None:
            logger.warning("Checkpoint references unknown chapter id '%s' — skipping", ch_id)
            continue
        restored.append(
            TranslationResult(
                chapter=chapter,
                translated_title=entry["translated_title"],
                translated_content=entry["translated_content"],
                score=entry.get("score"),
                feedback=entry.get("feedback"),
                issues=entry.get("issues"),
                needs_review=entry.get("needs_review", False),
            )
        )
    # Sort by chapter order in the EPUB
    order = {ch.id: i for i, ch in enumerate(all_chapters)}
    restored.sort(key=lambda r: order.get(r.chapter.id, 99999))
    return restored

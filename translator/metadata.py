"""
translator/metadata.py — Book-level metadata: title and chapter titles.

During auto-scan, the scanner generates a ``{stem}_metadata.yaml`` draft
with Gemini-translated book title and chapter titles.  The user can review
and edit the file before translation.  During the translation run, these
pre-approved translations take precedence over what Gemini produces for each
chapter.

File format (YAML):
    book_title:
      source: "魔女と傭兵 7"
      target: "Ma Nữ và Lính Đánh Thuê 7"
    chapters:
      - source: "一話　双刃の故"
        target: "Chương 1: Lưỡi Đôi"
      - source: "あとがき"
        target: "Lời kết"
"""

from __future__ import annotations

import logging
import os
from typing import Dict

import yaml

logger = logging.getLogger(__name__)

# Placeholder inserted by the scanner when Gemini couldn't translate something
_PLACEHOLDER_PREFIX = "["


class BookMetadata:
    """
    Stores and looks up pre-translated book title and chapter titles.
    """

    def __init__(self) -> None:
        self.book_title_source: str = ""
        self.book_title_target: str = ""
        # source title → translated title (exact-match keys)
        self._chapter_map: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def load(self, filepath: str) -> None:
        with open(filepath, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        bt = data.get("book_title") or {}
        self.book_title_source = bt.get("source", "")
        self.book_title_target = bt.get("target", "")

        for entry in data.get("chapters", []):
            src = (entry.get("source") or "").strip()
            tgt = (entry.get("target") or "").strip()
            if src and tgt:
                self._chapter_map[src] = tgt

        logger.info(
            "Loaded metadata from %s: book_title=%r, %d chapter title(s)",
            filepath,
            self.book_title_target,
            len(self._chapter_map),
        )

    def save(self, filepath: str) -> None:
        data = {
            "book_title": {
                "source": self.book_title_source,
                "target": self.book_title_target,
            },
            "chapters": [
                {"source": src, "target": tgt}
                for src, tgt in self._chapter_map.items()
            ],
        }
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_book_title(self) -> str:
        """Return the user-approved Vietnamese book title, or '' if not set."""
        t = self.book_title_target.strip()
        return "" if (not t or t.startswith(_PLACEHOLDER_PREFIX)) else t

    def get_chapter_title(self, source_title: str) -> str:
        """Return the pre-translated chapter title, or '' if not available."""
        t = self._chapter_map.get(source_title.strip(), "").strip()
        return "" if (not t or t.startswith(_PLACEHOLDER_PREFIX)) else t

    def is_empty(self) -> bool:
        return not self.book_title_source and not self._chapter_map

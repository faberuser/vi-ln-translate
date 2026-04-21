from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

# EPUB files are XHTML — suppress the spurious HTML-parser warning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """Represents a single chapter extracted from an EPUB."""
    id: str                  # item name / file path inside EPUB
    title: str
    content: str             # plain text (for prompting)
    html_content: str        # original HTML (for reconstruction)

    def __repr__(self) -> str:
        return f"Chapter(id={self.id!r}, title={self.title!r}, chars={len(self.content):,})"


class EpubHandler:
    """Reads and writes EPUB files, extracting chapters as plain text."""

    # Minimum characters to consider an item a real chapter
    MIN_CHAPTER_CHARS = 100

    def __init__(self) -> None:
        self.book: Optional[epub.EpubBook] = None
        self.chapters: List[Chapter] = []

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def load(self, filepath: str) -> List[Chapter]:
        """Load an EPUB and return a list of Chapter objects."""
        self.book = epub.read_epub(filepath)
        self.chapters = []

        toc_titles = _build_toc_map(self.book)

        for item in self.book.get_items_of_type(ITEM_DOCUMENT):
            raw = item.content
            html_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw

            # Use the XML parser for XHTML, HTML parser for plain HTML
            parser = "lxml-xml" if item.get_name().endswith(".xhtml") else "lxml"
            soup = BeautifulSoup(html_str, parser)

            # Title resolution order:
            #   1. EPUB TOC (NCX / nav) — most reliable
            #   2. First heading tag inside the document
            #   3. <title> element
            #   4. File name (last resort)
            item_name = item.get_name()
            title = toc_titles.get(item_name, "")

            if not title:
                for tag in soup.find_all(["h1", "h2", "h3"]):
                    text = tag.get_text(strip=True)
                    if text:
                        title = text
                        break

            if not title:
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)

            if not title:
                title = item_name

            text_content = soup.get_text(separator="\n", strip=True)

            # Skip navigation / TOC items
            if len(text_content.strip()) < self.MIN_CHAPTER_CHARS:
                continue

            self.chapters.append(
                Chapter(
                    id=item_name,
                    title=title,
                    content=text_content,
                    html_content=html_str,
                )
            )

        # Propagate titles: continuation sections that share a chapter in the
        # EPUB but aren't listed individually in the TOC get file-path titles.
        # Inherit the nearest preceding section's proper title so the translator
        # receives meaningful context and the output EPUB shows correct names.
        last_proper_title = ""
        for ch in self.chapters:
            if ch.title == ch.id:
                # Fell back to file path — inherit from previous section
                if last_proper_title:
                    ch.title = last_proper_title
            else:
                last_proper_title = ch.title

        logger.info("Loaded %d chapters from %s", len(self.chapters), filepath)
        return self.chapters

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def save(
        self,
        output_path: str,
        translated_chapters: List[tuple],  # (Chapter, new_title: str, new_html_body: str)
    ) -> None:
        """
        Save a modified copy of the loaded EPUB with translated content.

        ``translated_chapters`` is a list of 3-tuples:
            (original Chapter, translated_title, translated_html_body)
        Only chapters present in this list are replaced; all others are kept as-is.
        """
        if self.book is None:
            raise RuntimeError("No book loaded. Call load() first.")

        # Build lookup: chapter id → (title, html body)
        replacements = {ch.id: (title, body) for ch, title, body in translated_chapters}
        # Separate map for TOC title updates
        title_map = {ch.id: title for ch, title, body in translated_chapters}

        for item in self.book.get_items_of_type(ITEM_DOCUMENT):
            item_name = item.get_name()
            if item_name not in replacements:
                continue

            new_title, new_body = replacements[item_name]

            # Set item.title — ebooklib's get_content() builds <head><title> from this,
            # NOT from the raw item.content bytes.
            item.title = new_title

            # Detect the heading level used in the original HTML (h1/h2/h3 → default h2)
            raw = item.content
            orig_html = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            orig_soup = BeautifulSoup(orig_html, "lxml")
            orig_heading = orig_soup.find(["h1", "h2", "h3"])
            heading_level = orig_heading.name if orig_heading else "h2"

            # Inject translated title as a heading if the body doesn't already start with one
            if not new_body.lstrip().startswith("<h"):
                new_body = f"<{heading_level}>{_escape_xml(new_title)}</{heading_level}>\n{new_body}"

            new_html = (
                "<?xml version='1.0' encoding='utf-8'?>\n"
                "<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.1//EN' "
                "'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'>\n"
                "<html xmlns='http://www.w3.org/1999/xhtml'>\n"
                f"<head><title>{_escape_xml(new_title)}</title></head>\n"
                f"<body>\n{new_body}\n</body>\n</html>"
            )
            item.content = new_html.encode("utf-8")

        # Update EPUB TOC (NCX/NAV) link titles with translated titles
        _update_toc_titles(self.book.toc, title_map)

        # ebooklib crashes writing NCX when any TOC Link has uid=None
        _fix_toc_uids(self.book.toc)

        epub.write_epub(output_path, self.book)
        logger.info("Saved translated EPUB to %s", output_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fix_toc_uids(toc_items, _counter: list = None) -> None:
    """Recursively ensure every TOC Link has a non-None uid."""
    if _counter is None:
        _counter = [0]
    for item in toc_items:
        if isinstance(item, epub.Link):
            if not item.uid:
                _counter[0] += 1
                item.uid = f"navpoint-{_counter[0]}"
        elif isinstance(item, tuple):
            section, children = item
            if isinstance(section, epub.Link) and not section.uid:
                _counter[0] += 1
                section.uid = f"navpoint-{_counter[0]}"
            _fix_toc_uids(children, _counter)


def _update_toc_titles(toc_items, title_map: Dict[str, str]) -> None:
    """Recursively update TOC Link titles from a file-path → translated-title map."""
    for item in toc_items:
        if isinstance(item, epub.Link):
            href = item.href.split("#")[0]
            if href in title_map:
                item.title = title_map[href]
        elif isinstance(item, tuple):
            section, children = item
            if isinstance(section, epub.Link):
                href = section.href.split("#")[0]
                if href in title_map:
                    section.title = title_map[href]
            _update_toc_titles(children, title_map)


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def _build_toc_map(book: epub.EpubBook) -> Dict[str, str]:
    """
    Walk the EPUB table of contents and return a mapping of
    document file path → chapter title.

    Handles nested TOC sections recursively.
    """
    mapping: Dict[str, str] = {}

    def _walk(items) -> None:
        for item in items:
            if isinstance(item, epub.Link):
                # href may contain a fragment: "Text/section-0003.html#ch1"
                href = item.href.split("#")[0]
                if href and item.title and href not in mapping:
                    mapping[href] = item.title
            elif isinstance(item, tuple):
                # (Section, [children])
                section, children = item
                if isinstance(section, epub.Link) and section.href and section.title:
                    href = section.href.split("#")[0]
                    if href not in mapping:
                        mapping[href] = section.title
                _walk(children)
            elif isinstance(item, list):
                _walk(item)

    _walk(book.toc)
    return mapping

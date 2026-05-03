from __future__ import annotations

import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional

from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .gemini_client import GeminiClient

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
        # (Chapter, new_title: str, new_html_body: str)
        translated_chapters: List[tuple],
        gemini_client: "Optional[GeminiClient]" = None,
    ) -> None:
        """
        Build a clean LTR EPUB from scratch using the translated content.

        Copies the cover, inline images, and standalone illustration pages
        from the source book at their original spine positions; all Japanese
        CSS, RTL settings, and structural metadata are left behind.

        ``translated_chapters`` is a list of 3-tuples:
            (original Chapter, translated_title, translated_html_body)
        """
        if self.book is None:
            raise RuntimeError("No book loaded. Call load() first.")

        # ── Build a brand-new ebooklib book ───────────────────────────────
        new_book = epub.EpubBook()

        dc_ns = "http://purl.org/dc/elements/1.1/"
        raw_meta = self.book.metadata.get(dc_ns, {})

        # Identifier — use original ISBN/UUID if present
        id_entries = raw_meta.get("identifier", [])
        identifier = (id_entries[0][0] if id_entries and id_entries[0][0]
                      else str(id(new_book)))
        new_book.set_identifier(identifier)
        new_book.set_language("vi")

        # Book title: prefer the translated title of the chapter whose original
        # title matches the book's DC title (e.g. the title-page chapter).
        # Fall back to the output filename, stripping any remaining CJK.
        title_entries = raw_meta.get("title", [])
        orig_dc_title = (title_entries[0][0]
                         if title_entries and title_entries[0][0] else "")
        out_basename = os.path.splitext(os.path.basename(output_path))[0]

        book_title = out_basename
        for ch, new_title, _ in translated_chapters:
            if (ch.title.strip() == orig_dc_title.strip()
                    and new_title and not _JP_CHAR_RE.search(new_title)):
                book_title = new_title
                break
        if _JP_CHAR_RE.search(book_title):
            book_title = _JP_CHAR_RE.sub("", book_title).strip() or "Untitled"
        if book_title:
            new_book.set_title(book_title)

        # Copy authors/illustrators (skip blank or CJK-only entries)
        creator_entries = raw_meta.get("creator", [])
        for value, _attrs in creator_entries:
            if value and not _JP_CHAR_RE.search(value):
                new_book.add_author(value)

        # ── Cover image ────────────────────────────────────────────────────
        cover_item = None
        for item in self.book.get_items():
            if ("cover" in item.get_name().lower()
                    and item.media_type.startswith("image/")):
                cover_item = item
                break
        for item in self.book.get_items():
            props = getattr(item, "properties", "") or ""
            if "cover-image" in props:
                cover_item = item
                break

        cover_filename = (cover_item.get_name().rsplit("/", 1)[-1]
                          if cover_item is not None else None)
        if cover_item is not None:
            ext = cover_filename.rsplit(".", 1)[-1].lower()
            new_book.set_cover(f"cover.{ext}", cover_item.content)

        # ── Non-cover images from source ──────────────────────────────────
        # Maps bare filename → path relative to EPUB/ dir.
        # Cover image: at root as "cover.ext" (placed there by set_cover).
        # All other images: under "image/".
        _img_name_map: dict[str, str] = {}
        if cover_filename:
            ext = cover_filename.rsplit(".", 1)[-1].lower()
            _img_name_map[cover_filename] = f"cover.{ext}"
        for item in self.book.get_items():
            if not item.media_type.startswith("image/"):
                continue
            if cover_item and item.get_name() == cover_item.get_name():
                continue  # already in map above; set_cover() handles the file
            orig_filename = item.get_name().rsplit("/", 1)[-1]
            new_file_name = f"image/{orig_filename}"
            _img_name_map[orig_filename] = new_file_name
            new_book.add_item(epub.EpubItem(
                uid=f"img_{orig_filename}",
                file_name=new_file_name,
                media_type=item.media_type,
                content=item.content,
            ))

        # ── Standalone illustration pages from the original spine ─────────
        # Walk the spine in order. For each non-chapter XHTML that contains
        # only images (SVG xlink:href or <img src>), record its image files
        # and the index of the last chapter that preceded it (-1 = before all).
        chapter_name_set = {ch.id for ch in self.chapters}
        chapter_id_map = {ch.id: i for i, ch in enumerate(self.chapters)}
        # insert_after_orig_chapter_idx → [image filenames]
        illus_by_pos: dict[int, list[str]] = {}

        last_orig_ch_idx = -1
        for spine_id, _ in self.book.spine:
            item = self.book.get_item_with_id(spine_id)
            if item is None:
                continue
            item_name = item.get_name()
            if item_name in chapter_name_set:
                last_orig_ch_idx = chapter_id_map[item_name]
                continue
            raw = item.content
            html = (raw.decode("utf-8", errors="replace")
                    if isinstance(raw, bytes) else raw)
            imgs = re.findall(r'xlink:href="\.\.\/image\/([^"]+)"', html)
            imgs += re.findall(r'src="\.\.\/image\/([^"]+)"', html)
            # Only include images present in the image map
            imgs = [f for f in imgs if f in _img_name_map]
            for fname in imgs:
                illus_by_pos.setdefault(last_orig_ch_idx, []).append(fname)

        illus_counter = 0

        def _make_illus_page(filename: str) -> epub.EpubHtml:
            nonlocal illus_counter
            illus_counter += 1
            src_path = _img_name_map.get(filename, f"image/{filename}")
            page = epub.EpubHtml(
                uid=f"illus_{illus_counter}",
                file_name=f"illus_{illus_counter}.xhtml",
                title="",
                lang="vi",
            )
            page.content = (
                "<?xml version='1.0' encoding='utf-8'?>\n"
                "<!DOCTYPE html>\n"
                "<html xmlns='http://www.w3.org/1999/xhtml' lang='vi' xml:lang='vi'>\n"
                "<head><title></title>"
                "<style>body{margin:0;padding:0;text-align:center;}"
                "img{max-width:100%;height:auto;display:block;margin:auto;}</style>"
                "</head>\n"
                "<body>"
                f"<img src='{src_path}' alt=''/>"
                "</body>\n</html>"
            ).encode("utf-8")
            new_book.add_item(page)
            return page

        # ── Build the spine list ───────────────────────────────────────────
        all_spine_items: List[epub.EpubHtml] = []

        # Illustration pages that precede all chapters
        for fname in illus_by_pos.get(-1, []):
            all_spine_items.append(_make_illus_page(fname))

        # Chapters + illustration pages that follow each chapter
        epub_chapters: List[epub.EpubHtml] = []
        for ch_idx, (ch, new_title, new_body) in enumerate(translated_chapters, start=1):
            if not new_body.lstrip().startswith("<h"):
                new_body = f"<h2>{_escape_xml(new_title)}</h2>\n{new_body}"

            # Re-insert inline images at approximately their original positions
            img_positions = _get_inline_image_positions(
                ch.html_content, _img_name_map)
            if img_positions:
                lines = new_body.split("\n")
                block_idxs = [
                    i for i, l in enumerate(lines)
                    if re.match(r"\s*<(?:p|h[1-6])\b", l)
                ]
                n_blocks = len(block_idxs)
                if n_blocks:
                    insertions: dict[int, list] = {}
                    for frac, fname in img_positions:
                        target = min(int(frac * n_blocks), n_blocks - 1)
                        line_idx = block_idxs[target]
                        insertions.setdefault(line_idx, []).append(
                            f'<p><img src="image/{fname}" alt=""/></p>'
                        )
                    for line_idx in sorted(insertions.keys(), reverse=True):
                        for img_html in reversed(insertions[line_idx]):
                            lines.insert(line_idx + 1, img_html)
                    new_body = "\n".join(lines)
                else:
                    for _, fname in img_positions:
                        new_body += f'\n<p><img src="image/{fname}" alt=""/></p>'

            xhtml = epub.EpubHtml(
                uid=str(ch_idx),
                file_name=f"chap_{ch_idx}.xhtml",
                title=new_title,
                lang="vi",
            )
            xhtml.content = (
                "<?xml version='1.0' encoding='utf-8'?>\n"
                "<!DOCTYPE html>\n"
                "<html xmlns='http://www.w3.org/1999/xhtml' "
                "xmlns:epub='http://www.idpf.org/2007/ops' "
                "lang='vi' xml:lang='vi'>\n"
                f"<head><title>{_escape_xml(new_title)}</title></head>\n"
                f"<body>\n{new_body}\n</body>\n</html>"
            ).encode("utf-8")
            new_book.add_item(xhtml)
            epub_chapters.append(xhtml)
            all_spine_items.append(xhtml)

            # Illustration pages that follow this chapter in the original spine
            orig_ch_idx = chapter_id_map.get(ch.id, ch_idx - 1)
            for fname in illus_by_pos.get(orig_ch_idx, []):
                all_spine_items.append(_make_illus_page(fname))

        # ── Navigation / spine ────────────────────────────────────────────
        new_book.toc = tuple(
            epub.Link(ch.file_name, ch.title, ch.id)
            for ch in epub_chapters
        )
        new_book.add_item(epub.EpubNcx())
        new_book.add_item(epub.EpubNav())
        new_book.spine = ["nav"] + all_spine_items

        epub.write_epub(output_path, new_book)
        logger.info("Saved translated EPUB to %s", output_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Matches any CJK / Japanese character block
_JP_CHAR_RE = re.compile(
    r"[\u3000-\u9fff\uff00-\uffef\u3040-\u30ff\u4e00-\u9fff]+"
)


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


def _get_inline_image_positions(html_content: str, img_name_map: dict) -> list:
    """Return [(frac, filename), ...] for each inline image in a chapter.

    ``frac`` is the fraction of plain text that appears *before* the image
    in the original HTML (0.0 = very start, 1.0 = very end).  Standalone
    image-only pages (no surrounding text) return frac=0.0.
    """
    result = []
    total_text = len(re.sub(r"<[^>]+>", "", html_content))
    if not total_text:
        return result

    pos = 0
    text_so_far = 0
    html = html_content
    length = len(html)
    while pos < length:
        tag_start = html.find("<", pos)
        if tag_start == -1:
            break
        # Accumulate plain text before this tag
        text_so_far += tag_start - pos
        tag_end = html.find(">", tag_start)
        if tag_end == -1:
            break
        tag = html[tag_start: tag_end + 1]
        pos = tag_end + 1

        # Detect <img> or SVG <image> tags
        src = None
        if re.match(r"<img\b", tag, re.I):
            m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag)
            if m:
                src = m.group(1)
        elif re.match(r"<image\b", tag, re.I):
            m = re.search(r'\bxlink:href=["\']([^"\']+)["\']', tag)
            if m:
                src = m.group(1)

        if src:
            fname = src.rsplit("/", 1)[-1]
            if fname in img_name_map:
                frac = text_so_far / total_text
                result.append((frac, fname))

    return result


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

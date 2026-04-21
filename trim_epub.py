"""
trim_epub.py — interactively remove unwanted chapters from an EPUB file.

Usage:
    python trim_epub.py input.epub
    python trim_epub.py input.epub -o output.epub
    python trim_epub.py input.epub --remove 0,1,17         # remove by index
    python trim_epub.py input.epub --keep 2-16             # keep a range
    python trim_epub.py input.epub --list                  # just list chapters

Ranges accept:
  3        single index
  3,5,7    comma-separated list
  2-16     inclusive range
  2-       from index 2 to last
  -5       last 5 chapters (0 to 5)

Run without --remove / --keep to enter interactive mode.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Set

import warnings
from bs4 import XMLParsedAsHTMLWarning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from ebooklib import epub, ITEM_DOCUMENT
from rich.console import Console
from rich.table import Table
from rich import prompt as rich_prompt

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# EPUB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_toc_map(book: epub.EpubBook) -> dict:
    """Map item file path → title from TOC."""
    mapping: dict = {}

    def _walk(items):
        for item in items:
            if isinstance(item, epub.Link):
                href = item.href.split("#")[0]
                mapping[href] = item.title
            elif isinstance(item, tuple):
                section, children = item
                if isinstance(section, epub.Link):
                    href = section.href.split("#")[0]
                    mapping[href] = section.title
                _walk(children)

    _walk(book.toc)
    return mapping


def _get_chapters(book: epub.EpubBook) -> List[dict]:
    """Return [{index, id, name, title, chars}] for all document items."""
    from bs4 import BeautifulSoup
    toc_map = _build_toc_map(book)
    chapters = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        raw = item.content
        html = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        parser = "lxml-xml" if item.get_name().endswith(".xhtml") else "lxml"
        soup = BeautifulSoup(html, parser)

        name = item.get_name()
        heading = soup.find(re.compile(r"^h[1-3]$"))
        title = (
            toc_map.get(name)
            or toc_map.get(Path(name).name)
            or (heading.get_text(strip=True) if heading else None)
            or (soup.title.get_text(strip=True) if soup.title else None)
            or name
        )
        text = soup.get_text(" ", strip=True)
        chapters.append({"id": name, "title": title, "chars": len(text), "item": item})

    for i, ch in enumerate(chapters):
        ch["index"] = i

    # Propagate titles: continuation sections with no TOC entry fall back to
    # their file path. Inherit the nearest preceding section's proper title.
    last_proper = ""
    for ch in chapters:
        if ch["title"] == ch["id"]:
            if last_proper:
                ch["title"] = last_proper
        else:
            last_proper = ch["title"]

    return chapters


def _parse_indices(spec: str, max_index: int) -> Set[int]:
    """Parse a range/list spec into a set of 0-based indices."""
    indices: Set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m_range = re.fullmatch(r"(\d*)-(\d*)", part)
        if m_range:
            lo_s, hi_s = m_range.group(1), m_range.group(2)
            lo = int(lo_s) if lo_s else 0
            hi = int(hi_s) if hi_s else max_index
            for i in range(lo, hi + 1):
                if 0 <= i <= max_index:
                    indices.add(i)
        elif re.fullmatch(r"\d+", part):
            i = int(part)
            if 0 <= i <= max_index:
                indices.add(i)
        else:
            console.print(f"[yellow]Warning: unrecognised range token '{part}', skipping.[/yellow]")
    return indices


def _print_chapter_table(chapters: List[dict], remove_set: Optional[Set[int]] = None) -> None:
    table = Table(show_lines=True)
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Title", style="white")
    table.add_column("Chars", style="cyan", justify="right", width=8)
    table.add_column("Action", justify="center", width=10)

    for ch in chapters:
        if remove_set is not None:
            action = "[bold red]REMOVE[/bold red]" if ch["index"] in remove_set else "[green]keep[/green]"
        else:
            action = ""
        table.add_row(str(ch["index"]), ch["title"][:60], f"{ch['chars']:,}", action)

    console.print(table)


def _fix_toc_uids(toc_items, _counter: list = None) -> None:
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


def _remove_toc_entries(toc, item_ids: Set[str]):
    """Recursively strip TOC entries whose href points to a removed item."""
    result = []
    for entry in toc:
        if isinstance(entry, epub.Link):
            href_base = entry.href.split("#")[0]
            if href_base not in item_ids and Path(href_base).name not in item_ids:
                result.append(entry)
        elif isinstance(entry, tuple):
            section, children = entry
            filtered_children = _remove_toc_entries(children, item_ids)
            # Keep the section even if empty (it may be a part header)
            result.append((section, filtered_children))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Core trim function
# ─────────────────────────────────────────────────────────────────────────────

def trim_epub(input_path: str, output_path: str, remove_indices: Set[int]) -> None:
    """Remove chapters at the given 0-based indices and write a new EPUB."""
    book = epub.read_epub(input_path)
    chapters = _get_chapters(book)

    to_remove_ids: Set[str] = {ch["id"] for ch in chapters if ch["index"] in remove_indices}
    to_remove_names: Set[str] = {Path(i).name for i in to_remove_ids}

    # Remove document items from the book's manifest
    items_to_keep = [
        item for item in book.items
        if not (
            hasattr(item, "get_name")
            and item.get_name() in to_remove_ids
        )
    ]
    book.items = items_to_keep

    # Remove from spine
    book.spine = [
        (s if isinstance(s, str) else s[0], *((s[1],) if isinstance(s, tuple) and len(s) > 1 else ()))
        for s in book.spine
    ]
    # ebooklib spine is a list of (id_or_item, 'yes'/'no') tuples or strings
    def _spine_id(entry):
        if isinstance(entry, tuple):
            return entry[0]
        return entry

    book.spine = [
        s for s in book.spine
        if _spine_id(s) not in to_remove_ids and _spine_id(s) not in to_remove_names
    ]

    # Clean up TOC
    book.toc = _remove_toc_entries(book.toc, to_remove_ids | to_remove_names)

    # Fix any None uids before writing
    _fix_toc_uids(book.toc)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(output_path, book)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Remove unwanted chapters from an EPUB file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", metavar="INPUT.epub", help="Source EPUB file")
    parser.add_argument("-o", "--output", default=None, metavar="OUTPUT.epub",
                        help="Output path [default: <input>_trimmed.epub]")
    parser.add_argument("--list", action="store_true",
                        help="List chapters and exit without modifying anything")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", metavar="SPEC",
                       help="Indices to remove, e.g. 0,1,17 or 14-18")
    group.add_argument("--keep", metavar="SPEC",
                       help="Indices to keep (all others are removed), e.g. 2-16")
    args = parser.parse_args()

    input_path = args.input
    if not Path(input_path).exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {input_path}")
        sys.exit(1)

    book = epub.read_epub(input_path)
    chapters = _get_chapters(book)
    max_idx = len(chapters) - 1

    # ── --list mode ───────────────────────────────────────────────────────
    if args.list:
        _print_chapter_table(chapters)
        sys.exit(0)

    # ── Determine which indices to remove ─────────────────────────────────
    remove_set: Set[int] = set()

    if args.remove:
        remove_set = _parse_indices(args.remove, max_idx)
    elif args.keep:
        keep_set = _parse_indices(args.keep, max_idx)
        remove_set = {ch["index"] for ch in chapters if ch["index"] not in keep_set}
    else:
        # Interactive mode
        console.rule("[bold blue]EPUB Chapter Trimmer[/bold blue]")
        _print_chapter_table(chapters)
        console.print()
        console.print("Enter the chapter indices to [bold red]remove[/bold red].")
        console.print("  Examples:  [cyan]0,1,17[/cyan]   [cyan]14-18[/cyan]   [cyan]0,14-18[/cyan]")
        console.print("  Press Enter with nothing to cancel.\n")

        raw = rich_prompt.Prompt.ask("Indices to remove")
        if not raw.strip():
            console.print("[yellow]No indices entered — nothing changed.[/yellow]")
            sys.exit(0)
        remove_set = _parse_indices(raw, max_idx)

    if not remove_set:
        console.print("[yellow]No valid indices selected — nothing to do.[/yellow]")
        sys.exit(0)

    # ── Preview ───────────────────────────────────────────────────────────
    console.rule("[bold blue]Preview[/bold blue]")
    _print_chapter_table(chapters, remove_set)

    keeping = len(chapters) - len(remove_set)
    console.print(
        f"\nRemoving [bold red]{len(remove_set)}[/bold red] chapter(s), "
        f"keeping [bold green]{keeping}[/bold green]."
    )

    # ── Confirm (skip in non-interactive / --remove mode) ─────────────────
    if not args.remove and not args.keep:
        if not rich_prompt.Confirm.ask("Proceed?", default=True):
            console.print("[yellow]Aborted.[/yellow]")
            sys.exit(0)

    # ── Output path ───────────────────────────────────────────────────────
    if args.output:
        output_path = args.output
    else:
        p = Path(input_path)
        output_path = str(p.with_stem(p.stem + "_trimmed"))

    trim_epub(input_path, output_path, remove_set)
    console.print(f"\n[bold green]Done![/bold green]  Saved → [bold]{output_path}[/bold]")


if __name__ == "__main__":
    main()

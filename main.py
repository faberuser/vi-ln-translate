"""
main.py — EN→VI / JP→VI Light Novel Translator

Just run:  python main.py

All settings are read from config.yaml (see that file for documentation).
Input EPUBs are auto-discovered from data/input/*.epub.
Translated EPUBs are written to data/output/.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

# Load .env file if present (GEMINI_API_KEY, etc.)
load_dotenv()

console = Console()

_GLOB_DATA = ("*.yaml", "*.yml", "*.json")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _find_data_files(directory: Path, globs: tuple) -> List[Path]:
    found: List[Path] = []
    if not directory.exists():
        return found
    for pattern in globs:
        found.extend(directory.glob(pattern))
    # Skip example template files (prefixed with "example_")
    return sorted(p for p in set(found) if not p.name.startswith("example_"))


def _find_epubs(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.epub"))


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    from translator.config import TranslatorConfig
    from translator.gemini_client import DailyQuotaExhaustedError
    from translator.gemini_client import GeminiClient
    from translator.glossary import Glossary
    from translator.pronoun_system import RelationshipMatrix
    from translator.scanner import BookScanner
    from translator.style_reference import BookStyleAnalyzer, StyleReference
    from translator.translator import Translator

    cfg = TranslatorConfig.load()
    _setup_logging(cfg.verbose)

    if not cfg.api_key:
        console.print(
            "[bold red]Error:[/bold red] No API key found. "
            "Set [bold]api_key[/bold] in config.yaml or [bold]GEMINI_API_KEY[/bold] in your .env file."
        )
        sys.exit(1)

    # ── Discover input EPUBs ───────────────────────────────────────────────
    input_dir = Path(cfg.input_dir)
    input_epubs = _find_epubs(input_dir)
    if not input_epubs:
        console.print(
            f"[bold red]Error:[/bold red] No .epub files found in [bold]{input_dir}[/bold]. "
            "Place the volumes you want to translate there and re-run."
        )
        sys.exit(1)

    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    glossaries_dir = Path(cfg.glossaries_dir)
    relationships_dir = Path(cfg.relationships_dir)
    prior_dir = Path(cfg.prior_volumes_dir)

    style_references_dir = Path(cfg.style_references_dir)

    # Derive source language label for display
    _lang_label = "JP→VI" if cfg.source_language.lower() in ("jp", "ja") else "EN→VI"

    console.rule(
        f"[bold blue]Light Novel {_lang_label} Translator[/bold blue]")
    console.print(f"  Model      : {cfg.model}")
    console.print(f"  Language   : {_lang_label}")
    console.print(
        f"  Mode       : {'BATCH (%d chapters/request)' % cfg.batch_size if cfg.batch else 'per-chapter'}")
    console.print(
        f"  Evaluate   : {'no' if (not cfg.evaluate or cfg.batch) else 'yes'}")
    console.print(f"  Resume     : {'yes' if cfg.resume else 'no'}")
    console.print(f"  Auto-scan  : {'yes' if cfg.auto_scan else 'no'}")
    console.print(
        f"  Input dir  : {input_dir.resolve()}  ({len(input_epubs)} epub(s))")
    console.print(f"  Output dir : {output_dir.resolve()}")
    console.rule()
    # ── Style references ──────────────────────────────────────────────────
    style_ref = StyleReference()
    _STYLE_EXTS = ("*.epub", "*.txt")
    style_files: List[Path] = []
    if style_references_dir.exists():
        for pattern in _STYLE_EXTS:
            style_files.extend(style_references_dir.glob(pattern))
        style_files = sorted(style_files)

    if style_files:
        style_analyzer = BookStyleAnalyzer(GeminiClient(
            api_key=cfg.api_key, model_name=cfg.model))
        console.print(
            f"[dim]Style refs  : {len(style_files)} file(s) found in {style_references_dir}[/dim]")
        for sf in style_files:
            cache_path = style_references_dir / f"{sf.stem}.style.yaml"
            try:
                with console.status(f"[bold yellow]Analysing style: {sf.name}…[/bold yellow]"):
                    profile = style_analyzer.analyze(
                        book_path=str(sf),
                        cache_path=str(cache_path),
                    )
                style_ref.add_profile(profile)
                console.print(
                    f"  [green]✓[/green] Style profile loaded: [bold]{sf.name}[/bold]  "
                    f"(tone: {profile.tone or 'n/a'})"
                )
            except Exception as exc:
                console.print(
                    f"  [yellow]⚠  Could not analyse style reference '{sf.name}': {exc}[/yellow]")
    else:
        console.print(
            f"[dim]Style refs  : none found in {style_references_dir}[/dim]")

    # ── Glossary ──────────────────────────────────────────────────────────
    gloss = Glossary()
    gloss_files = _find_data_files(glossaries_dir, _GLOB_DATA)
    for gf in gloss_files:
        gloss.load(str(gf))
    if gloss_files:
        console.print(
            f"[dim]Glossary   : {len(gloss.entries)} entries from {len(gloss_files)} file(s)[/dim]")
    else:
        console.print(
            f"[dim]Glossary   : none found in {glossaries_dir}[/dim]")

    # ── Relationship matrix ───────────────────────────────────────────────
    matrix = RelationshipMatrix()
    rel_files = _find_data_files(relationships_dir, _GLOB_DATA)
    for rf in rel_files:
        matrix.load(str(rf))
    if rel_files:
        console.print(
            f"[dim]Relations  : {len(matrix.relationships)} pairs from {len(rel_files)} file(s)[/dim]")
    else:
        console.print(
            f"[dim]Relations  : none found in {relationships_dir}[/dim]")

    console.rule()

    # ── Auto-scan: generate draft glossary/relationships if requested ──────
    if cfg.auto_scan:
        client_for_scan = GeminiClient(
            api_key=cfg.api_key, model_name=cfg.model)
        scanner = BookScanner(
            client_for_scan, source_language=cfg.source_language)
        any_scanned = False

        for epub_path in input_epubs:
            stem = epub_path.stem
            gloss_out = glossaries_dir / f"{stem}_glossary.yaml"
            rel_out = relationships_dir / f"{stem}_relationships.yaml"

            need_gloss = not gloss_out.exists()
            need_rel = not rel_out.exists()

            if not need_gloss and not need_rel:
                continue  # draft files already exist — skip

            console.print(
                f"\n[bold yellow]Auto-scan[/bold yellow]: '{epub_path.name}' has no draft glossary/relationships yet."
            )
            console.print(
                "  Scanning the book to generate initial drafts… (this uses one API call)\n")

            try:
                with console.status("[bold yellow]Scanning…[/bold yellow]"):
                    gloss_data, rel_data = scanner.scan_epub(str(epub_path))
            except Exception as exc:
                console.print(f"[bold red]✗  Scan failed:[/bold red] {exc}")
                console.print(
                    "  Continuing without draft files. You can add them manually later.")
                continue

            if need_gloss:
                gloss_out.parent.mkdir(parents=True, exist_ok=True)
                scanner.save_glossary(gloss_data, str(gloss_out))
                console.print(
                    f"  [green]✓[/green] Glossary draft saved → [bold]{gloss_out}[/bold]"
                    f"  ({len(gloss_data.get('entries', []))} entries)"
                )
                # Load immediately so these entries are used in translation
                gloss.load(str(gloss_out))

            if need_rel:
                rel_out.parent.mkdir(parents=True, exist_ok=True)
                scanner.save_relationships(rel_data, str(rel_out))
                console.print(
                    f"  [green]✓[/green] Relationships draft saved → [bold]{rel_out}[/bold]"
                    f"  ({len(rel_data.get('relationships', []))} pairs)"
                )
                # Load immediately
                matrix.load(str(rel_out))

            any_scanned = True

        if any_scanned:
            console.print()
            console.print(
                "[bold yellow]⚠  Draft files have been generated.[/bold yellow] "
                "Please open and review them now."
            )
            console.print(
                "   Edit the files, then press [bold]Enter[/bold] to continue with translation, "
                "or [bold]Ctrl+C[/bold] to abort and re-run later."
            )
            try:
                input()
            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]Aborted. Re-run python main.py when ready.[/yellow]")
                sys.exit(0)

    # ── Translator instance (shared across all input volumes) ─────────────
    client = GeminiClient(api_key=cfg.api_key, model_name=cfg.model)
    translator = Translator(
        gemini_client=client,
        glossary=gloss,
        relationship_matrix=matrix,
        style_reference=style_ref,
        context_window=cfg.context_window,
        review_threshold=cfg.review_threshold,
        max_output_tokens=cfg.max_tokens,
        batch_chunk_size=cfg.batch_size,
        source_language=cfg.source_language,
    )
    translator.illustration_chapter = cfg.illustration_chapter

    # ── Seed prior-volume context ─────────────────────────────────────────
    prior_epubs = _find_epubs(prior_dir)
    if prior_epubs:
        seeded = translator.load_prior_volumes([str(p) for p in prior_epubs])
        console.print(
            f"[dim]Prior ctx  : {len(prior_epubs)} volume(s) ({seeded} chapters)[/dim]")
    else:
        console.print(f"[dim]Prior ctx  : none found in {prior_dir}[/dim]")

    console.rule()

    # ── Translate each input EPUB ─────────────────────────────────────────
    for epub_path in input_epubs:
        output_path = output_dir / f"{epub_path.stem}.epub"
        console.print(
            f"\n[bold cyan]▶  {epub_path.name}[/bold cyan]  →  [dim]{output_path.name}[/dim]")

        status_msg = "[bold green]Translating…[/bold green]\n"
        try:
            with console.status(status_msg):
                results = translator.translate_epub(
                    input_path=str(epub_path),
                    output_path=str(output_path),
                    start_chapter=cfg.start_chapter,
                    end_chapter=cfg.end_chapter,
                    evaluate=cfg.evaluate and not cfg.batch,
                    batch_mode=cfg.batch,
                    resume=cfg.resume,
                )
        except DailyQuotaExhaustedError as exc:
            console.print()
            console.print(
                "[bold red]✗  Daily API quota (RPD) exhausted.[/bold red]")
            console.print(
                "[yellow]   Progress has been saved to the checkpoint file.[/yellow]")
            console.print(
                "[yellow]   Re-run [bold]python main.py[/bold] tomorrow to resume from where it stopped.[/yellow]")
            console.print(f"[dim]   {exc}[/dim]")
            raise SystemExit(1)

        # ── Summary table ──────────────────────────────────────────────
        table = Table(title=f"Summary — {epub_path.stem}", show_lines=True)
        table.add_column("#", style="dim", justify="right", width=4)
        table.add_column("Translated Title", style="white")
        table.add_column("Score", style="green", justify="center", width=8)
        table.add_column("Review?", justify="center", width=9)

        for i, r in enumerate(results):
            score_str = f"{r.score:.0f}/100" if r.score is not None else "N/A"
            review_str = "[bold red]YES[/bold red]" if r.needs_review else "[green]No[/green]"
            table.add_row(str(cfg.start_chapter + i + 1),
                          r.translated_title[:55], score_str, review_str)

        console.print(table)

        needs_review = [r for r in results if r.needs_review]
        if needs_review:
            console.print(
                f"[yellow]⚠  {len(needs_review)} chapter(s) need human review:[/yellow]")
            for r in needs_review:
                console.print(f"  • [cyan]{r.translated_title}[/cyan]")
                if r.issues:
                    for line in r.issues.splitlines()[:5]:
                        console.print(f"    [dim]{line}[/dim]")

        console.print(
            f"[bold green]✓[/bold green]  Saved → [bold]{output_path}[/bold]")

    console.rule()
    console.print("[bold green]All done![/bold green]")


if __name__ == "__main__":
    main()

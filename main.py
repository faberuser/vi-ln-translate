"""
main.py — EN→VI Light Novel Translator

Just run:  python main.py

All settings are read from config.yaml (see that file for documentation).
Input EPUBs are auto-discovered from data/input/*.epub.
Translated EPUBs are written to data/output/.
"""

from __future__ import annotations

import logging
import os
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
    return sorted(set(found))


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

    glossaries_dir   = Path(cfg.glossaries_dir)
    relationships_dir = Path(cfg.relationships_dir)
    prior_dir        = Path(cfg.prior_volumes_dir)

    console.rule("[bold blue]Light Novel EN→VI Translator[/bold blue]")
    console.print(f"  Model      : {cfg.model}")
    console.print(f"  Mode       : {'BATCH (%d chapters/request)' % cfg.batch_size if cfg.batch else 'per-chapter'}")
    console.print(f"  Evaluate   : {'no' if (not cfg.evaluate or cfg.batch) else 'yes'}")
    console.print(f"  Resume     : {'yes' if cfg.resume else 'no'}")
    console.print(f"  Input dir  : {input_dir.resolve()}  ({len(input_epubs)} epub(s))")
    console.print(f"  Output dir : {output_dir.resolve()}")
    console.rule()

    # ── Glossary ──────────────────────────────────────────────────────────
    gloss = Glossary()
    gloss_files = _find_data_files(glossaries_dir, _GLOB_DATA)
    for gf in gloss_files:
        gloss.load(str(gf))
    if gloss_files:
        console.print(f"[dim]Glossary   : {len(gloss.entries)} entries from {len(gloss_files)} file(s)[/dim]")
    else:
        console.print(f"[dim]Glossary   : none found in {glossaries_dir}[/dim]")

    # ── Relationship matrix ───────────────────────────────────────────────
    matrix = RelationshipMatrix()
    rel_files = _find_data_files(relationships_dir, _GLOB_DATA)
    for rf in rel_files:
        matrix.load(str(rf))
    if rel_files:
        console.print(f"[dim]Relations  : {len(matrix.relationships)} pairs from {len(rel_files)} file(s)[/dim]")
    else:
        console.print(f"[dim]Relations  : none found in {relationships_dir}[/dim]")

    # ── Translator instance (shared across all input volumes) ─────────────
    client = GeminiClient(api_key=cfg.api_key, model_name=cfg.model)
    translator = Translator(
        gemini_client=client,
        glossary=gloss,
        relationship_matrix=matrix,
        context_window=cfg.context_window,
        review_threshold=cfg.review_threshold,
        max_output_tokens=cfg.max_tokens,
        batch_chunk_size=cfg.batch_size,
    )

    # ── Seed prior-volume context ─────────────────────────────────────────
    prior_epubs = _find_epubs(prior_dir)
    if prior_epubs:
        seeded = translator.load_prior_volumes([str(p) for p in prior_epubs])
        console.print(f"[dim]Prior ctx  : {len(prior_epubs)} volume(s) ({seeded} chapters)[/dim]")
    else:
        console.print(f"[dim]Prior ctx  : none found in {prior_dir}[/dim]")

    console.rule()

    # ── Translate each input EPUB ─────────────────────────────────────────
    for epub_path in input_epubs:
        output_path = output_dir / f"{epub_path.stem}.epub"
        console.print(f"\n[bold cyan]▶  {epub_path.name}[/bold cyan]  →  [dim]{output_path.name}[/dim]")

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
            console.print("[bold red]✗  Daily API quota (RPD) exhausted.[/bold red]")
            console.print("[yellow]   Progress has been saved to the checkpoint file.[/yellow]")
            console.print("[yellow]   Re-run [bold]python main.py[/bold] tomorrow to resume from where it stopped.[/yellow]")
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
            table.add_row(str(cfg.start_chapter + i + 1), r.translated_title[:55], score_str, review_str)

        console.print(table)

        needs_review = [r for r in results if r.needs_review]
        if needs_review:
            console.print(f"[yellow]⚠  {len(needs_review)} chapter(s) need human review:[/yellow]")
            for r in needs_review:
                console.print(f"  • [cyan]{r.translated_title}[/cyan]")
                if r.issues:
                    for line in r.issues.splitlines()[:5]:
                        console.print(f"    [dim]{line}[/dim]")

        console.print(f"[bold green]✓[/bold green]  Saved → [bold]{output_path}[/bold]")

    console.rule()
    console.print("[bold green]All done![/bold green]")


if __name__ == "__main__":
    main()
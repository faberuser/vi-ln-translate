from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class GlossaryEntry:
    source: str
    target: str
    context: str = ""
    notes: str = ""


class Glossary:
    """
    Manages a bilingual terminology list (EN → VI).

    File format (YAML or JSON):
        entries:
          - source: "Hero"
            target: "Dũng sĩ"
            context: "Chức danh"
            notes: ""
    """

    def __init__(self) -> None:
        self.entries: Dict[str, GlossaryEntry] = {}  # lower-cased source → entry

    # ------------------------------------------------------------------

    def load(self, filepath: str) -> None:
        data = _load_yaml_or_json(filepath)
        for item in data.get("entries", []):
            entry = GlossaryEntry(
                source=item["source"],
                target=item["target"],
                context=item.get("context", ""),
                notes=item.get("notes", ""),
            )
            self.entries[entry.source.lower()] = entry
        logger.info("Loaded %d glossary entries from %s", len(self.entries), filepath)

    def add(self, source: str, target: str, context: str = "", notes: str = "") -> None:
        self.entries[source.lower()] = GlossaryEntry(source, target, context, notes)

    def save(self, filepath: str) -> None:
        data = {
            "entries": [
                {
                    "source": e.source,
                    "target": e.target,
                    "context": e.context,
                    "notes": e.notes,
                }
                for e in self.entries.values()
            ]
        }
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def to_prompt_text(self) -> str:
        if not self.entries:
            return ""
        lines = ["=== BẢNG THUẬT NGỮ / GLOSSARY ==="]
        for e in self.entries.values():
            line = f"- {e.source} → {e.target}"
            if e.context:
                line += f"  [{e.context}]"
            if e.notes:
                line += f"  ({e.notes})"
            lines.append(line)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml_or_json(filepath: str) -> dict:
    ext = os.path.splitext(filepath)[1].lower()
    with open(filepath, "r", encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            return yaml.safe_load(f) or {}
        elif ext == ".json":
            return json.load(f)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

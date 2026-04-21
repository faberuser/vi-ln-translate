from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    """
    Describes how Character A addresses themselves and Character B
    when they are speaking to each other.

    Example:
        char_a       = "Arata"
        char_b       = "Yuki"
        a_calls_self = "anh"   (Arata says "anh" for himself)
        a_calls_b    = "em"    (Arata calls Yuki "em")
    """
    char_a: str
    char_b: str
    a_calls_self: str
    a_calls_b: str
    context: str = ""
    notes: str = ""


class RelationshipMatrix:
    """
    Stores bidirectional pronoun relationships between characters.

    File format (YAML or JSON):
        relationships:
          - char_a: "Arata"
            char_b: "Yuki"
            a_calls_self: "anh"
            a_calls_b: "em"
            context: "Romantic"
            notes: ""
    """

    def __init__(self) -> None:
        self._data: Dict[str, Relationship] = {}

    # ------------------------------------------------------------------

    @staticmethod
    def _key(char_a: str, char_b: str) -> str:
        return f"{char_a.lower()}→{char_b.lower()}"

    def add(
        self,
        char_a: str,
        char_b: str,
        a_calls_self: str,
        a_calls_b: str,
        context: str = "",
        notes: str = "",
    ) -> None:
        self._data[self._key(char_a, char_b)] = Relationship(
            char_a, char_b, a_calls_self, a_calls_b, context, notes
        )

    def get(self, char_a: str, char_b: str) -> Optional[Relationship]:
        return self._data.get(self._key(char_a, char_b))

    def load(self, filepath: str) -> None:
        ext = os.path.splitext(filepath)[1].lower()
        with open(filepath, "r", encoding="utf-8") as f:
            if ext in (".yaml", ".yml"):
                import yaml as _yaml
                data = _yaml.safe_load(f) or {}
            elif ext == ".json":
                import json as _json
                data = _json.load(f)
            else:
                raise ValueError(f"Unsupported format: {ext}")

        for item in data.get("relationships", []):
            self.add(
                char_a=item["char_a"],
                char_b=item["char_b"],
                a_calls_self=item["a_calls_self"],
                a_calls_b=item["a_calls_b"],
                context=item.get("context", ""),
                notes=item.get("notes", ""),
            )
        logger.info(
            "Loaded %d relationships from %s", len(self._data), filepath
        )

    def save(self, filepath: str) -> None:
        data = {
            "relationships": [
                {
                    "char_a": r.char_a,
                    "char_b": r.char_b,
                    "a_calls_self": r.a_calls_self,
                    "a_calls_b": r.a_calls_b,
                    "context": r.context,
                    "notes": r.notes,
                }
                for r in self._data.values()
            ]
        }
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def to_prompt_text(self) -> str:
        if not self._data:
            return ""
        lines = ["=== MA TRẬN ĐẠI TỪ NHÂN XƯNG / PRONOUN MATRIX ==="]
        lines.append(
            "Quy tắc: khi nhân vật A nói chuyện với nhân vật B, "
            "A xưng hô theo bảng dưới đây."
        )
        for r in self._data.values():
            line = (
                f"- {r.char_a} → {r.char_b}: "
                f"{r.char_a} tự xưng '{r.a_calls_self}', "
                f"gọi {r.char_b} là '{r.a_calls_b}'"
            )
            if r.context:
                line += f"  [{r.context}]"
            if r.notes:
                line += f"  ({r.notes})"
            lines.append(line)
        return "\n".join(lines)

    @property
    def relationships(self) -> Dict[str, Relationship]:
        return self._data

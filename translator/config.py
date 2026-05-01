from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path("config.yaml")
_UNLIMITED_CONTEXT = 999999  # Use all available chapters when context_window is ~


@dataclass
class TranslatorConfig:
    # API
    api_key: str = ""
    model: str = "gemini-3-flash-preview"

    # Paths
    data_dir: str = "data"
    input_dir: str = "data/input"
    output_dir: str = "data/output"
    glossaries_dir: str = "data/glossaries"
    relationships_dir: str = "data/relationships"
    prior_volumes_dir: str = "data/prior"

    # Translation behaviour
    source_language: str = "en"   # "en" for English→VI, "jp" for Japanese→VI
    batch: bool = True
    batch_size: int = 5
    max_tokens: int = 65536
    context_window: int = 3
    resume: bool = True
    start_chapter: int = 0
    end_chapter: Optional[int] = None

    # Quality evaluation
    evaluate: bool = False
    review_threshold: float = 75.0

    # Auto-scan
    auto_scan: bool = True   # scan book and generate draft glossary/relationships before translating

    # Misc
    verbose: bool = False

    @classmethod
    def load(cls, filepath: str | Path = _CONFIG_FILE) -> "TranslatorConfig":
        """Load from YAML file, falling back to env vars for api_key.
        context_window supports:
          - numeric (3, 5, etc): use last N chapters
          - null/~: use all available chapters from prior volumes
        """
        cfg = cls()
        path = Path(filepath)
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            for key, value in data.items():
                if not hasattr(cfg, key):
                    continue
                # Special case: context_window ~ means unlimited
                if key == "context_window" and value is None:
                    setattr(cfg, key, _UNLIMITED_CONTEXT)
                elif value is not None:
                    setattr(cfg, key, value)
        # env / .env always wins for the secret
        env_key = os.environ.get("GEMINI_API_KEY", "")
        if env_key:
            cfg.api_key = env_key
        return cfg

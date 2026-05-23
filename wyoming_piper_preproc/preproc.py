"""Text preprocessing for TTS.

Inspired by the pipeline in VE-Analysis-API (`_normalize_for_tts` +
`_apply_pronunciations` + `_normalize_punctuation_for_engine`). Slimmed
to what Piper needs:

  1. Normalize unicode punctuation (smart quotes, em/en dashes, ellipsis).
  2. Apply pronunciation overrides from CSV (longest-first match).
  3. Light engine-specific cleanup.

The CSV files are reloaded on every preprocess() call so edits take
effect immediately without restarting the container. The reload cost
is tiny (a few hundred bytes per file) compared to TTS time.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

_LOG = logging.getLogger(__name__)


def _load_pronunciations(paths: Iterable[Path]) -> list[tuple[str, str]]:
    """Load pronunciation overrides from one or more CSV files.

    Later files override earlier ones (so a Piper-specific overlay
    can shadow a base CSV shared with other engines).

    Returns list of (written, spoken) tuples sorted longest-first so
    longer phrases match before their substrings.
    """
    pairs: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Strip the key only — value spaces are preserved so authors
                # can write " degrees Fahrenheit" (leading space) to handle
                # substitutions for tokens like "°F" that have no boundary space.
                # Trailing newline already removed by splitlines().
                key, _, value = line.partition(",")
                if value or "," in line:
                    pairs[key.strip()] = value
        except OSError as e:
            _LOG.warning("could not read %s: %s", path, e)
    out = list(pairs.items())
    out.sort(key=lambda p: len(p[0]), reverse=True)
    return out


def _normalize_unicode(text: str) -> str:
    """Replace unicode punctuation with ASCII / spelled-out forms Piper
    will read cleanly. Glyphs like μ, ³, ° aren't handled here — they
    belong in the pronunciation CSV with the right spoken form.
    """
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    # Em/en dash → ellipsis (Piper pauses on ellipsis, blows through em-dash)
    text = text.replace("—", "...").replace("–", "...")
    text = re.sub(r"\s*--\s*", "... ", text)
    text = text.replace("…", "...")
    return text


def _apply_pronunciations(text: str, pairs: list[tuple[str, str]]) -> str:
    for written, spoken in pairs:
        text = text.replace(written, spoken)
    return text


def preprocess(text: str, csv_paths: list[Path]) -> str:
    """Run the full pipeline. Pure function — same input always gives same output."""
    text = _normalize_unicode(text)
    pairs = _load_pronunciations(csv_paths)
    text = _apply_pronunciations(text, pairs)
    return text

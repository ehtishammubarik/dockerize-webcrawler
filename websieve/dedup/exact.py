"""Exact and near-exact duplicate detection by hashing.

Runs before MinHash because it is far cheaper and removes the easy cases. On a
typical crawl this drops a large share of documents before the expensive stage
ever sees them.

Three levels, increasingly aggressive:

``raw``          byte-identical text.
``normalized``   identical after case folding and whitespace collapse. Catches
                 the same page served with different formatting.
``structural``   identical after also removing all digits. Catches templated
                 pages that differ only by a price, date, count, or id, which
                 is the dominant duplicate pattern on e-commerce and listing
                 sites.

``structural`` will merge genuinely different pages whose only distinguishing
content is numeric. That is usually what you want for a training corpus and
usually not what you want for a price tracker. Choose deliberately.
"""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def _digest(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=16).hexdigest()


def raw_hash(text: str) -> str:
    """Hash of the text exactly as given."""
    return _digest(text)


def normalized_hash(text: str) -> str:
    """Hash after case folding, punctuation removal, and whitespace collapse."""
    s = _PUNCT.sub(" ", text.casefold())
    return _digest(_WS.sub(" ", s).strip())


def structural_hash(text: str) -> str:
    """Hash after also collapsing every digit run to a placeholder."""
    s = _PUNCT.sub(" ", text.casefold())
    s = _DIGITS.sub("0", s)
    return _digest(_WS.sub(" ", s).strip())


LEVELS = {
    "raw": raw_hash,
    "normalized": normalized_hash,
    "structural": structural_hash,
}


def signatures(text: str) -> dict[str, str]:
    """All three hashes at once. Cheap enough to always compute."""
    return {name: fn(text) for name, fn in LEVELS.items()}


class ExactDeduper:
    """Streaming first-wins deduplicator at a chosen level."""

    def __init__(self, level: str = "normalized") -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}; expected one of {sorted(LEVELS)}")
        self.level = level
        self._fn = LEVELS[level]
        self._seen: dict[str, str] = {}

    def check(self, key: str, text: str) -> tuple[bool, str | None]:
        """Return ``(is_duplicate, first_key_seen_with_this_hash)``."""
        h = self._fn(text)
        first = self._seen.get(h)
        if first is not None:
            return (True, first)
        self._seen[h] = key
        return (False, None)

    def __len__(self) -> int:
        return len(self._seen)

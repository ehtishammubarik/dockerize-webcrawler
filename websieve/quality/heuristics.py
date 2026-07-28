"""Quality heuristics for web-crawled training corpora.

The rules follow the published filtering recipes for large web corpora, chiefly
the Gopher rules (Rae et al., 2021, "Scaling Language Models", appendix A.1.1)
and the C4 cleanup (Raffel et al., 2020). They are reimplemented here rather
than vendored so that every threshold is visible and adjustable, because the
right values genuinely differ between a general-web corpus and a
domain-specific one.

Every rule returns a ``Rule`` result rather than a bare bool, so a run can
report *why* documents were dropped. At corpus scale that breakdown is the
difference between tuning the filter and guessing at it.

Stdlib only. No dependencies.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?。！？]")

# Terminal punctuation that marks a line as prose rather than a nav item.
_ELLIPSIS = ("...", "…")

# Words that signal machine-generated placeholder or policy boilerplate.
_BOILERPLATE_MARKERS = (
    "lorem ipsum",
    "javascript is disabled",
    "enable javascript",
    "terms of use",
    "privacy policy",
    "all rights reserved",
    "cookie policy",
    "403 forbidden",
    "404 not found",
    "access denied",
)


@dataclass(frozen=True, slots=True)
class Rule:
    """Outcome of a single quality rule."""

    name: str
    passed: bool
    value: float | int | None = None
    threshold: float | int | None = None

    def __bool__(self) -> bool:
        return self.passed


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Aggregate result across all rules."""

    passed: bool
    rules: tuple[Rule, ...]

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.rules if not r.passed)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failures": list(self.failures),
            "rules": {
                r.name: {"passed": r.passed, "value": r.value, "threshold": r.threshold}
                for r in self.rules
            },
        }


def words(text: str) -> list[str]:
    """Tokenize to alphabetic words. Digits and punctuation are excluded."""
    return _WORD.findall(text)


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def word_count(text: str, *, lo: int = 50, hi: int = 100_000) -> Rule:
    """Gopher: drop documents outside 50 to 100,000 words."""
    n = len(words(text))
    return Rule("word_count", lo <= n <= hi, n, lo)


def mean_word_length(text: str, *, lo: float = 3.0, hi: float = 10.0) -> Rule:
    """Gopher: mean word length outside 3 to 10 characters signals junk.

    Catches both character-soup and concatenated-token pages.
    """
    w = words(text)
    if not w:
        return Rule("mean_word_length", False, 0.0, lo)
    m = statistics.fmean(len(x) for x in w)
    return Rule("mean_word_length", lo <= m <= hi, round(m, 2), lo)


def symbol_to_word_ratio(text: str, *, max_ratio: float = 0.10) -> Rule:
    """Gopher: ratio of ``#`` and ellipsis to words above 0.1 signals junk.

    High values indicate code dumps, redacted text, or truncated listings.
    """
    w = words(text)
    if not w:
        return Rule("symbol_to_word_ratio", False, 1.0, max_ratio)
    symbols = text.count("#") + sum(text.count(e) for e in _ELLIPSIS)
    ratio = symbols / len(w)
    return Rule("symbol_to_word_ratio", ratio <= max_ratio, round(ratio, 4), max_ratio)


def alpha_word_ratio(text: str, *, min_ratio: float = 0.80) -> Rule:
    """Gopher: at least 80 percent of words should contain an alphabetic char.

    Tables of numbers and ID dumps fail here.
    """
    tokens = text.split()
    if not tokens:
        return Rule("alpha_word_ratio", False, 0.0, min_ratio)
    alpha = sum(1 for t in tokens if any(c.isalpha() for c in t))
    ratio = alpha / len(tokens)
    return Rule("alpha_word_ratio", ratio >= min_ratio, round(ratio, 4), min_ratio)


def bullet_line_ratio(text: str, *, max_ratio: float = 0.90) -> Rule:
    """Gopher: more than 90 percent bullet lines means it is a list, not prose."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return Rule("bullet_line_ratio", False, 1.0, max_ratio)
    bullets = sum(1 for ln in lines if ln.lstrip()[:1] in "-*•‣◦⁃")
    ratio = bullets / len(lines)
    return Rule("bullet_line_ratio", ratio <= max_ratio, round(ratio, 4), max_ratio)


def ellipsis_line_ratio(text: str, *, max_ratio: float = 0.30) -> Rule:
    """Gopher: many lines ending in an ellipsis means truncated teaser text."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return Rule("ellipsis_line_ratio", False, 1.0, max_ratio)
    n = sum(1 for ln in lines if ln.rstrip().endswith(_ELLIPSIS))
    ratio = n / len(lines)
    return Rule("ellipsis_line_ratio", ratio <= max_ratio, round(ratio, 4), max_ratio)


def terminal_punctuation_ratio(text: str, *, min_ratio: float = 0.15) -> Rule:
    """C4: real prose has sentences. Nav dumps have none.

    C4 drops lines lacking terminal punctuation outright; here it is scored
    across the document so a single caption does not sink an article.
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return Rule("terminal_punctuation_ratio", False, 0.0, min_ratio)
    n = sum(1 for ln in lines if _SENTENCE_END.search(ln.rstrip()[-1:] or ""))
    ratio = n / len(lines)
    return Rule("terminal_punctuation_ratio", ratio >= min_ratio, round(ratio, 4), min_ratio)


def repetition_ratio(text: str, *, max_ratio: float = 0.30) -> Rule:
    """Gopher: fraction of characters inside duplicated lines.

    The single most effective rule against SEO spam and template pages, which
    repeat the same sentence with one word substituted.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return Rule("repetition_ratio", True, 0.0, max_ratio)
    seen: dict[str, int] = {}
    for ln in lines:
        seen[ln] = seen.get(ln, 0) + 1
    dup_chars = sum(len(ln) * (c - 1) for ln, c in seen.items() if c > 1)
    total = sum(len(ln) for ln in lines)
    ratio = dup_chars / total if total else 1.0
    return Rule("repetition_ratio", ratio <= max_ratio, round(ratio, 4), max_ratio)


def boilerplate_markers(text: str, *, max_hits: int = 2) -> Rule:
    """Reject pages dominated by policy or error boilerplate."""
    low = text.lower()
    hits = sum(1 for m in _BOILERPLATE_MARKERS if m in low)
    return Rule("boilerplate_markers", hits <= max_hits, hits, max_hits)


DEFAULT_RULES: tuple[Callable[[str], Rule], ...] = (
    word_count,
    mean_word_length,
    symbol_to_word_ratio,
    alpha_word_ratio,
    bullet_line_ratio,
    ellipsis_line_ratio,
    terminal_punctuation_ratio,
    repetition_ratio,
    boilerplate_markers,
)


def assess(text: str, rules=DEFAULT_RULES) -> QualityReport:
    """Run all rules and aggregate.

    Every rule runs even after one fails, because the failure breakdown is the
    point. Short-circuiting would save microseconds and cost you the ability to
    tune thresholds against a real corpus.
    """
    results = tuple(rule(text) for rule in rules)
    return QualityReport(all(r.passed for r in results), results)

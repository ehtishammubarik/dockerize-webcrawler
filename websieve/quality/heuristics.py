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

from .language import ScriptProfile, profile

# Combining marks, which Python's \w excludes because they are category Mn or
# Mc rather than alphanumeric. Without them every abugida mis-tokenizes: the
# Devanagari word for "machine" splits into two fragments because the vowel
# sign reads as a word boundary. That inflates word counts and collapses mean
# word length, which is what rejected ordinary Hindi at 1.4 characters per
# word. Decomposed Latin diacritics have the same problem.
_COMBINING = (
    "\u0300-\u036f"  # Latin, Greek, Cyrillic
    "\u0483-\u0489"  # Cyrillic
    "\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7"  # Hebrew points
    "\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8"  # Arabic
    "\u0900-\u0903\u093a-\u094f\u0951-\u0957\u0962\u0963"  # Devanagari
    "\u0981-\u0983\u09bc\u09be-\u09cd\u09d7\u09e2\u09e3"  # Bengali
    "\u0a01-\u0a03\u0a3c-\u0a51"  # Gurmukhi
    "\u0b82\u0bbe-\u0bcd\u0bd7"  # Tamil
    "\u0e31\u0e34-\u0e3a\u0e47-\u0e4e"  # Thai
    "\u0f71-\u0f84\u0f86\u0f87"  # Tibetan
    "\u102b-\u103e"  # Myanmar
)

# A word is a letter followed by any letters or combining marks, with internal
# apostrophes and hyphens allowed.
# Note the alternation. [^\W\d_] is already a negated class, so putting the
# combining marks inside it would exclude them, which is the opposite of the
# intent and fails silently: Latin still tokenizes correctly, so the mistake
# only shows up on abugidas.
_LETTER = "[^\\W\\d_]"
_LETTER_OR_MARK = "(?:[^\\W\\d_]|[" + _COMBINING + "])"
_WORD = re.compile(
    _LETTER + _LETTER_OR_MARK + "*(?:['\u2019-]" + _LETTER + _LETTER_OR_MARK + "*)*",
    re.UNICODE,
)

# Sentence-terminating punctuation across writing systems. Restricting this to
# ASCII plus CJK rejected Hindi outright, because Devanagari ends sentences
# with a danda rather than a full stop.
_SENTENCE_END = re.compile(
    "["
    ".!?"  # Latin and most European
    "\u3002\uff01\uff1f"  # CJK full stop, fullwidth ! and ?
    "\u0964\u0965"  # Devanagari danda, double danda
    "\u06d4"  # Arabic full stop
    "\u1362"  # Ethiopic full stop
    "\u0589"  # Armenian full stop
    "]"
)

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
    script: ScriptProfile | None = None

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.rules if not r.passed)

    def to_dict(self) -> dict:
        out = {
            "passed": self.passed,
            "failures": list(self.failures),
            "rules": {
                r.name: {"passed": r.passed, "value": r.value, "threshold": r.threshold}
                for r in self.rules
            },
        }
        if self.script is not None:
            out["script"] = self.script.script
            out["script_confidence"] = self.script.confidence
            out["space_delimited"] = self.script.space_delimited
        return out


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


def char_count(text: str, *, lo: int = 80, hi: int = 400_000) -> Rule:
    """Length in letters, for scripts that do not delimit words with spaces.

    Stands in for ``word_count``. The floor of 80 is calibrated to be roughly
    equivalent to the 50-word English minimum: CJK text averages close to two
    characters per word-equivalent, and setting it by eye rather than by
    equivalence would silently move the bar between languages.
    """
    n = sum(1 for c in text if c.isalpha())
    return Rule("char_count", lo <= n <= hi, n, lo)


def symbol_to_char_ratio(text: str, *, max_ratio: float = 0.05) -> Rule:
    """``symbol_to_word_ratio`` denominated in characters rather than words."""
    letters = sum(1 for c in text if c.isalpha())
    if not letters:
        return Rule("symbol_to_char_ratio", False, 1.0, max_ratio)
    symbols = text.count("#") + sum(text.count(e) for e in _ELLIPSIS)
    ratio = symbols / letters
    return Rule("symbol_to_char_ratio", ratio <= max_ratio, round(ratio, 4), max_ratio)


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


# Applied when the dominant script does not delimit words with spaces. The
# word-based rules are not relaxed here, they are removed: `mean_word_length`
# and `alpha_word_ratio` have no meaningful interpretation when the tokenizer
# cannot find word boundaries, so a "tuned" threshold would be a made-up number
# wearing the appearance of rigour.
NON_SPACE_DELIMITED_RULES: tuple[Callable[[str], Rule], ...] = (
    char_count,
    symbol_to_char_ratio,
    bullet_line_ratio,
    ellipsis_line_ratio,
    terminal_punctuation_ratio,
    repetition_ratio,
    boilerplate_markers,
)


def select_rules(script: ScriptProfile) -> tuple[Callable[[str], Rule], ...]:
    """Compose a rule set from the script's traits.

    Built from independent traits rather than a language whitelist, because the
    traits vary independently: Korean is space-delimited with dense characters,
    Thai is neither space-delimited nor punctuated, Chinese is not
    space-delimited but is punctuated.

    An undetermined script keeps the defaults. Text with no classifiable
    letters is usually junk the default rules reject anyway, and adapting on no
    evidence would let it through.
    """
    if script.is_undetermined:
        return DEFAULT_RULES

    base = DEFAULT_RULES if script.space_delimited else NON_SPACE_DELIMITED_RULES
    rules: list[Callable[[str], Rule]] = []

    for rule in base:
        if rule is terminal_punctuation_ratio and not script.uses_terminal_punctuation:
            continue  # the script has no terminal punctuation to find
        if rule is mean_word_length and script.dense_characters:
            # Lower floor, not removal: character-soup is still worth catching.
            rules.append(lambda t: mean_word_length(t, lo=1.8))
            continue
        rules.append(rule)

    return tuple(rules)


def assess(text: str, rules=None, *, adapt_to_script: bool = True) -> QualityReport:
    """Run all rules and aggregate.

    Every rule runs even after one fails, because the failure breakdown is the
    point. Short-circuiting would save microseconds and cost you the ability to
    tune thresholds against a real corpus.

    By default the rule set adapts to the dominant script: text in a language
    that does not delimit words with spaces is scored on characters instead.
    Pass ``rules`` explicitly to override, or ``adapt_to_script=False`` to force
    the English-derived defaults regardless of what the text is.
    """
    script = profile(text) if (rules is None and adapt_to_script) else None
    if rules is None:
        rules = select_rules(script) if adapt_to_script else DEFAULT_RULES

    results = tuple(rule(text) for rule in rules)
    return QualityReport(all(r.passed for r in results), results, script)

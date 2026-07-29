"""Script detection, and what it implies for the quality rules.

The quality heuristics in this package are inherited from recipes built for
English web text, and every one of them assumes words are separated by spaces.
`words()` tokenizes on a word-character run, and `mean_word_length`,
`alpha_word_ratio`, and `symbol_to_word_ratio` all derive from that count.

Chinese, Japanese, Thai, Lao, Khmer, Burmese, and Tibetan do not delimit words
with spaces. A well-formed Chinese article tokenizes as a handful of enormous
"words", so `mean_word_length` sees a value far above its 10-character ceiling
and rejects the document. The filter reports a near-zero keep rate and gives no
indication why, which reads as the tool being broken rather than misapplied.

This module detects the dominant script so the rule set can adapt. It detects
*script*, not language: distinguishing Mandarin from Cantonese needs a model,
and is not what the thresholds actually depend on. Whether the text is
space-delimited is.

Stdlib only. Codepoint ranges rather than `unicodedata.name()`, which is
correct but roughly two orders of magnitude slower per character.
"""

from __future__ import annotations

from dataclasses import dataclass

# (start, end, script) over the ranges that carry running text. Ordered by
# rough frequency on the web so the common case exits early.
_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0041, 0x005A, "latin"),
    (0x0061, 0x007A, "latin"),
    (0x00C0, 0x024F, "latin"),  # Latin-1 Supplement through Extended-B
    (0x4E00, 0x9FFF, "han"),  # CJK Unified Ideographs
    (0x3400, 0x4DBF, "han"),  # CJK Extension A
    (0xF900, 0xFAFF, "han"),  # CJK Compatibility Ideographs
    (0x3040, 0x309F, "hiragana"),
    (0x30A0, 0x30FF, "katakana"),
    (0xAC00, 0xD7AF, "hangul"),
    (0x0400, 0x04FF, "cyrillic"),
    (0x0500, 0x052F, "cyrillic"),
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),
    (0x0590, 0x05FF, "hebrew"),
    (0x0370, 0x03FF, "greek"),
    (0x0900, 0x097F, "devanagari"),
    (0x0980, 0x09FF, "bengali"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x1780, 0x17FF, "khmer"),
    (0x1000, 0x109F, "myanmar"),
    (0x0F00, 0x0FFF, "tibetan"),
    (0x1200, 0x137F, "ethiopic"),
    (0x10A0, 0x10FF, "georgian"),
    (0x0530, 0x058F, "armenian"),
)

# Scripts that do not put spaces between words. Word-count and word-length
# rules are meaningless for these and must be replaced, not merely relaxed.
#
# Korean is deliberately absent: Hangul is written with spaces between eojeol,
# so the word-based rules apply to it normally.
NON_SPACE_DELIMITED = frozenset(
    {"han", "hiragana", "katakana", "thai", "lao", "khmer", "myanmar", "tibetan"}
)

# Scripts written without sentence-terminating punctuation. Thai, Lao, Khmer,
# and Burmese separate sentences with a space; Tibetan uses a shad, which is a
# clause marker rather than a full stop. Requiring terminal punctuation of them
# rejects perfectly ordinary prose.
#
# CJK is deliberately absent: it has its own terminal marks, and the
# terminal_punctuation_ratio rule already recognises them.
NO_TERMINAL_PUNCTUATION = frozenset({"thai", "lao", "khmer", "myanmar", "tibetan"})

# Scripts where one character carries more phonemic content than a Latin
# letter, so words are shorter measured in characters without being shorter in
# any meaningful sense. Hangul packs a full syllable into one block; the
# abugidas fuse a consonant and its vowel into one glyph.
#
# The English-derived mean_word_length floor of 3.0 rejects ordinary Korean at
# a measured 2.92. That is an artefact of the writing system, not a quality
# signal, so these scripts get a lower floor rather than the rule removed:
# character-soup is still worth catching, just at a different threshold.
DENSE_CHARACTER_SCRIPTS = frozenset(
    {"hangul", "devanagari", "bengali", "ethiopic", "tibetan", "thai", "lao", "khmer", "myanmar"}
)

# Japanese is a mixture, and the han portion alone can look like Chinese.
_JAPANESE_KANA = frozenset({"hiragana", "katakana"})

# Sampling cap. Script does not change halfway through a document, and scanning
# a megabyte to learn what the first few thousand characters already say is
# waste at corpus scale.
_SAMPLE_CHARS = 4096


def _script_of(codepoint: int) -> str | None:
    for lo, hi, script in _RANGES:
        if lo <= codepoint <= hi:
            return script
    return None


@dataclass(frozen=True, slots=True)
class ScriptProfile:
    """What script a document is written in, and what follows from that.

    The traits are separate booleans rather than one "is it English-like" flag
    because they vary independently. Korean is space-delimited but has dense
    characters. Thai is neither space-delimited nor punctuated. Chinese is not
    space-delimited but does use terminal punctuation. Collapsing these into a
    single axis is what produced the original bug.
    """

    script: str
    confidence: float
    space_delimited: bool
    counts: dict[str, int]

    @property
    def is_undetermined(self) -> bool:
        return self.script == "unknown"

    @property
    def uses_terminal_punctuation(self) -> bool:
        return self.script not in NO_TERMINAL_PUNCTUATION

    @property
    def dense_characters(self) -> bool:
        """Whether one character carries more than a Latin letter's worth."""
        return self.script in DENSE_CHARACTER_SCRIPTS


def profile(text: str, *, sample_chars: int = _SAMPLE_CHARS) -> ScriptProfile:
    """Identify the dominant script.

    Only letters are counted. Digits, punctuation, and whitespace are shared
    across scripts and would dilute the signal, most damagingly on short
    documents.

    Confidence is the dominant script's share of classified characters. Text
    with no classifiable letters at all, such as a table of numbers, comes back
    as ``unknown`` with confidence 0, and callers should treat that as "do not
    adapt" rather than as a detection.
    """
    counts: dict[str, int] = {}
    classified = 0

    for ch in text[:sample_chars]:
        if not ch.isalpha():
            continue
        script = _script_of(ord(ch))
        if script is None:
            continue
        counts[script] = counts.get(script, 0) + 1
        classified += 1

    if not classified:
        return ScriptProfile("unknown", 0.0, True, {})

    # Japanese mixes kanji with kana. If any kana are present in meaningful
    # quantity the document is Japanese, even when han outnumbers them, which
    # it usually does in formal prose.
    kana = sum(counts.get(k, 0) for k in _JAPANESE_KANA)
    if kana / classified >= 0.05 and counts.get("han", 0):
        return ScriptProfile(
            "japanese", round((kana + counts["han"]) / classified, 4), False, counts
        )

    script = max(counts, key=lambda k: counts[k])
    return ScriptProfile(
        script,
        round(counts[script] / classified, 4),
        script not in NON_SPACE_DELIMITED,
        counts,
    )


def is_space_delimited(text: str) -> bool:
    """Whether word-based quality rules apply to this text."""
    return profile(text).space_delimited

from websieve.clean.normalize import (
    collapse_whitespace,
    normalize,
    normalize_unicode,
    strip_invisible,
)


def test_strips_zero_width_and_bidi():
    assert strip_invisible("a​b‮c") == "abc"


def test_strips_control_chars_but_keeps_newline_and_tab():
    assert strip_invisible("a\x00b\x07c\nd\te") == "abc\nd\te"


def test_nfkc_folds_compatibility_forms():
    # Fullwidth Latin and the 'fi' ligature both fold under NFKC.
    assert normalize_unicode("Ｈｅｌｌｏ") == "Hello"
    assert normalize_unicode("ﬁle") == "file"


def test_preserves_paragraph_breaks_but_collapses_excess():
    assert collapse_whitespace("a\n\n\n\n\nb") == "a\n\nb"


def test_collapses_horizontal_runs_without_eating_newlines():
    assert collapse_whitespace("a   \t  b\nc") == "a b\nc"


def test_folds_typographic_quotes():
    assert normalize("“quoted” and ’s") == '"quoted" and \'s'


def test_empty_input_is_safe():
    assert normalize("") == ""
    assert normalize("   \n\n  ") == ""


def test_is_idempotent():
    raw = "  “Hello”​   \n\n\n world Ａ  "
    once = normalize(raw)
    assert normalize(once) == once

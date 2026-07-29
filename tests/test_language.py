import pytest

from websieve.quality.heuristics import assess, select_rules, words
from websieve.quality.language import (
    DENSE_CHARACTER_SCRIPTS,
    NO_TERMINAL_PUNCTUATION,
    NON_SPACE_DELIMITED,
    is_space_delimited,
    profile,
)

# Real sentences rather than lorem, so the rules see plausible structure.
SAMPLES = {
    "latin": "Kubernetes exposes GPUs through the NVIDIA device plugin on every node. " * 8,
    "han": "深度学习模型需要大量的训练数据才能达到良好的效果和泛化能力。" * 6,
    "japanese": "機械学習モデルは大量のトレーニングデータを必要とします。品質が重要です。" * 5,
    "hangul": "기계 학습 모델은 많은 양의 학습 데이터가 필요합니다. 데이터 품질이 중요합니다." * 9,
    "thai": "โมเดลการเรียนรู้ของเครื่องต้องการข้อมูลการฝึกอบรมจำนวนมากเพื่อให้ได้ผลลัพธ์ที่ดี" * 4,
    "devanagari": "मशीन लर्निंग मॉडल को बड़ी मात्रा में प्रशिक्षण डेटा की आवश्यकता होती है। " * 6,
    "bengali": "মেশিন লার্নিং মডেলের জন্য প্রচুর প্রশিক্ষণ ডেটা প্রয়োজন। " * 12,
    "arabic": "تحتاج نماذج التعلم الآلي إلى كميات كبيرة من بيانات التدريب لتحقيق نتائج جيدة. " * 6,
    "cyrillic": "Модели машинного обучения требуют большого количества обучающих данных. " * 8,
    "greek": "Τα μοντέλα μηχανικής μάθησης απαιτούν μεγάλες ποσότητες δεδομένων εκπαίδευσης. " * 9,
    "hebrew": "מודלים של למידת מכונה דורשים כמויות גדולות של נתוני אימון. " * 7,
}


# -- detection -------------------------------------------------------------


@pytest.mark.parametrize("expected,text", list(SAMPLES.items()))
def test_detects_the_dominant_script(expected, text):
    assert profile(text).script == expected


def test_confidence_is_high_for_monolingual_text():
    assert profile(SAMPLES["han"]).confidence > 0.9


def test_text_with_no_letters_is_undetermined():
    p = profile("1 2 3 4 5 !!! ### 42")
    assert p.is_undetermined
    assert p.confidence == 0.0


def test_empty_text_is_undetermined_rather_than_raising():
    assert profile("").is_undetermined


def test_japanese_is_distinguished_from_chinese_by_kana():
    # Formal Japanese is mostly kanji, so counting han alone reads as Chinese.
    assert profile(SAMPLES["japanese"]).script == "japanese"
    assert profile(SAMPLES["han"]).script == "han"


def test_korean_is_space_delimited_despite_being_cjk_adjacent():
    # Hangul is written with spaces between eojeol, so word rules apply.
    assert is_space_delimited(SAMPLES["hangul"])
    assert "hangul" not in NON_SPACE_DELIMITED


@pytest.mark.parametrize("script", ["han", "japanese", "thai"])
def test_non_space_delimited_scripts_are_flagged(script):
    assert not profile(SAMPLES[script]).space_delimited


def test_traits_vary_independently():
    # The bug this module fixes came from collapsing these onto one axis.
    ko, th, zh = (profile(SAMPLES[k]) for k in ("hangul", "thai", "han"))
    assert (ko.space_delimited, ko.dense_characters) == (True, True)
    assert (th.space_delimited, th.uses_terminal_punctuation) == (False, False)
    assert (zh.space_delimited, zh.uses_terminal_punctuation) == (False, True)


def test_detection_samples_rather_than_scanning_everything():
    # A megabyte of text must not cost a megabyte of work.
    assert profile(SAMPLES["han"] * 5000, sample_chars=256).script == "han"


# -- tokenization ----------------------------------------------------------


def test_abugida_words_are_not_split_on_vowel_signs():
    # Devanagari vowel signs are combining marks, which \w excludes. Before the
    # fix this returned fragments and collapsed mean_word_length to 1.4.
    assert words("मशीन लर्निंग मॉडल") == ["मशीन", "लर्निंग", "मॉडल"]


def test_bengali_and_tamil_tokenize_whole_words():
    assert words("মেশিন লার্নিং") == ["মেশিন", "লার্নিং"]
    assert words("இயந்திர கற்றல்") == ["இயந்திர", "கற்றல்"]


def test_decomposed_latin_diacritics_stay_in_one_word():
    assert words("café résumé naïve") == ["café", "résumé", "naïve"]


def test_english_tokenization_is_unchanged():
    assert words("Kubernetes exposes GPU-based don't") == [
        "Kubernetes",
        "exposes",
        "GPU-based",
        "don't",
    ]


# -- rule selection --------------------------------------------------------


def test_space_delimited_scripts_keep_the_word_based_rules():
    rules = select_rules(profile(SAMPLES["latin"]))
    assert any(r.__name__ == "word_count" for r in rules if hasattr(r, "__name__"))


def test_non_space_delimited_scripts_drop_word_based_rules():
    names = [getattr(r, "__name__", "") for r in select_rules(profile(SAMPLES["han"]))]
    assert "word_count" not in names
    assert "char_count" in names


def test_scripts_without_terminal_punctuation_drop_that_rule():
    names = [getattr(r, "__name__", "") for r in select_rules(profile(SAMPLES["thai"]))]
    assert "terminal_punctuation_ratio" not in names
    # Chinese has its own terminal marks and must keep it.
    zh = [getattr(r, "__name__", "") for r in select_rules(profile(SAMPLES["han"]))]
    assert "terminal_punctuation_ratio" in zh


def test_undetermined_script_falls_back_to_defaults_rather_than_adapting():
    from websieve.quality.heuristics import DEFAULT_RULES

    assert select_rules(profile("123 456")) == DEFAULT_RULES


# -- end to end ------------------------------------------------------------


@pytest.mark.parametrize("name,text", list(SAMPLES.items()))
def test_ordinary_prose_passes_in_every_script(name, text):
    report = assess(text)
    assert report.passed, f"{name} rejected: {report.failures}"


@pytest.mark.parametrize(
    "junk",
    [
        "Home About Contact Login",
        "1 2 3 4 5 " * 20,
        "\n".join(["Buy cheap now"] * 30),
        "a b c d e " * 40,
        "",
        "\n".join(["- item"] * 25),
    ],
)
def test_junk_is_still_rejected(junk):
    # Adapting to script must not become a way for junk to slip through.
    assert not assess(junk).passed


def test_script_is_reported_in_the_quality_dict():
    d = assess(SAMPLES["han"]).to_dict()
    assert d["script"] == "han"
    assert d["space_delimited"] is False
    assert 0.0 < d["script_confidence"] <= 1.0


def test_adaptation_can_be_disabled():
    # Forcing the English-derived rules must still reject CJK, which is the
    # behaviour this whole module exists to stop being the default.
    assert not assess(SAMPLES["han"], adapt_to_script=False).passed


def test_explicit_rules_override_adaptation():
    from websieve.quality.heuristics import repetition_ratio

    report = assess(SAMPLES["han"], rules=(repetition_ratio,))
    assert len(report.rules) == 1
    assert report.script is None


def test_constants_are_disjoint_where_they_should_be():
    # Korean is dense but space-delimited; CJK is neither dense nor punctuated
    # the same way. A script in NON_SPACE_DELIMITED must not claim to be
    # space-delimited.
    for s in NON_SPACE_DELIMITED:
        assert s not in {"hangul", "latin", "cyrillic", "arabic"}
    assert DENSE_CHARACTER_SCRIPTS | {"tibetan"} >= NO_TERMINAL_PUNCTUATION

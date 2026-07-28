import pytest

from webcorpus.quality import heuristics as q

PROSE = (
    "Kubernetes schedules GPU workloads through the NVIDIA device plugin. "
    "The plugin advertises nvidia.com/gpu as an allocatable resource on nodes. "
    "Fragmentation becomes the dominant concern once training and inference mix. "
    "MIG partitioning splits an A100 into as many as seven separate instances. "
) * 4


def test_clean_prose_passes_everything():
    report = q.assess(PROSE)
    assert report.passed, report.failures


def test_short_document_fails_word_count():
    assert "word_count" in q.assess("Too short.").failures


def test_repeated_lines_fail_repetition():
    assert not q.repetition_ratio("\n".join(["Buy now cheap deals"] * 30)).passed


def test_unique_lines_pass_repetition():
    lines = "\n".join(f"Line number {i} says something different." for i in range(30))
    assert q.repetition_ratio(lines).passed


def test_numeric_dump_fails_alpha_ratio():
    assert not q.alpha_word_ratio("1 2 3 4 5 6 7 8 9 10 " * 20).passed


def test_bullet_list_fails_bullet_ratio():
    assert not q.bullet_line_ratio("\n".join(["- item"] * 20)).passed


def test_teaser_text_fails_ellipsis_ratio():
    assert not q.ellipsis_line_ratio("\n".join(["Read more about this..."] * 10)).passed


def test_nav_dump_fails_terminal_punctuation():
    assert not q.terminal_punctuation_ratio("\n".join(["Home", "About", "Contact"] * 5)).passed


def test_boilerplate_markers_detected():
    text = "Privacy policy. Terms of use. All rights reserved. Cookie policy."
    assert not q.boilerplate_markers(text).passed


def test_character_soup_fails_mean_word_length():
    assert not q.mean_word_length("a b c d e f g " * 40).passed


@pytest.mark.parametrize("empty", ["", "   ", "\n\n"])
def test_empty_input_fails_rather_than_raising(empty):
    report = q.assess(empty)
    assert not report.passed
    assert len(report.failures) > 0


def test_report_serializes_with_values_and_thresholds():
    d = q.assess(PROSE).to_dict()
    assert d["passed"] is True
    assert "word_count" in d["rules"]
    assert d["rules"]["word_count"]["value"] > 0
    assert d["rules"]["word_count"]["threshold"] == 50


def test_all_rules_run_even_after_a_failure():
    # A failure must not short circuit; the breakdown is the whole point.
    report = q.assess("x")
    assert len(report.rules) == len(q.DEFAULT_RULES)


def test_rule_is_truthy_by_passed():
    assert bool(q.word_count(PROSE)) is True
    assert bool(q.word_count("tiny")) is False

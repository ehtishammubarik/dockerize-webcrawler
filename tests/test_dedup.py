import pytest

from websieve.dedup.exact import (
    ExactDeduper,
    normalized_hash,
    raw_hash,
    signatures,
    structural_hash,
)
from websieve.dedup.minhash import LSHIndex, MinHash, deduplicate, shingles

A = "the quick brown fox jumps over the lazy dog beside the river at dawn today"
B = "the quick brown fox jumps over the lazy dog beside the river at dusk today"
C = "kubernetes schedules gpu workloads with the nvidia device plugin and taints"


def true_jaccard(x, y):
    X, Y = shingles(x), shingles(y)
    return len(X & Y) / len(X | Y) if (X | Y) else 0.0


# -- MinHash ---------------------------------------------------------------


def test_identical_text_has_identical_signature():
    mh = MinHash(num_perm=64)
    assert mh.signature(A) == mh.signature(A)


def test_similarity_of_identical_is_one():
    mh = MinHash(num_perm=64)
    assert MinHash.similarity(mh.signature(A), mh.signature(A)) == 1.0


def test_unrelated_documents_score_near_zero():
    mh = MinHash(num_perm=128)
    assert MinHash.similarity(mh.signature(A), mh.signature(C)) < 0.15


def test_estimate_approximates_true_jaccard():
    # Standard error is about 1/sqrt(num_perm); allow 3 sigma.
    mh = MinHash(num_perm=256)
    est = MinHash.similarity(mh.signature(A), mh.signature(B))
    tol = 3 / (256**0.5)
    assert abs(est - true_jaccard(A, B)) < tol


def test_signature_length_matches_num_perm():
    assert len(MinHash(num_perm=32).signature(A)) == 32


def test_mismatched_signature_lengths_raise():
    with pytest.raises(ValueError, match="length mismatch"):
        MinHash.similarity((1, 2, 3), (1, 2))


def test_empty_text_yields_stable_signature():
    mh = MinHash(num_perm=16)
    assert mh.signature("") == mh.signature("")


def test_seed_determines_signature():
    assert MinHash(num_perm=32, seed=1).signature(A) == MinHash(num_perm=32, seed=1).signature(A)
    assert MinHash(num_perm=32, seed=1).signature(A) != MinHash(num_perm=32, seed=2).signature(A)


# -- shingles --------------------------------------------------------------


def test_shingles_are_overlapping_ngrams():
    assert shingles("a b c d", n=2) == {"a b", "b c", "c d"}


def test_short_text_yields_single_shingle():
    assert shingles("a b", n=5) == {"a b"}


def test_empty_text_yields_no_shingles():
    assert shingles("", n=3) == set()


# -- LSH -------------------------------------------------------------------


def test_bands_must_divide_num_perm():
    with pytest.raises(ValueError, match="divisible"):
        LSHIndex(num_perm=128, bands=7)


def test_rows_and_threshold_are_derived():
    idx = LSHIndex(num_perm=128, bands=32)
    assert idx.rows == 4
    assert 0.0 < idx.approx_threshold < 1.0


def test_index_finds_similar_and_ignores_unrelated():
    mh = MinHash(num_perm=128)
    idx = LSHIndex(num_perm=128, bands=64)
    idx.add("a", mh.signature(A))
    assert [k for k, _ in idx.duplicates(mh.signature(B), 0.5)] == ["a"]
    assert idx.duplicates(mh.signature(C), 0.5) == []


def test_add_rejects_wrong_length_signature():
    with pytest.raises(ValueError, match="!= num_perm"):
        LSHIndex(num_perm=128, bands=32).add("k", (1, 2, 3))


def test_exclude_filters_self_match():
    mh = MinHash(num_perm=64)
    idx = LSHIndex(num_perm=64, bands=32)
    sig = mh.signature(A)
    idx.add("a", sig)
    assert idx.query(sig, exclude="a") == set()


# -- greedy dedup ----------------------------------------------------------


def test_first_wins_and_later_copies_are_marked():
    out = list(deduplicate([("d1", A), ("d2", A), ("d3", C)], threshold=0.7))
    assert out[0][:3] == ("d1", False, None)
    assert out[1][:3] == ("d2", True, "d1")
    assert out[2][:3] == ("d3", False, None)


def test_threshold_controls_strictness():
    loose = list(deduplicate([("a", A), ("b", B)], threshold=0.5, bands=64))
    strict = list(deduplicate([("a", A), ("b", B)], threshold=0.99, bands=64))
    assert loose[1][1] is True
    assert strict[1][1] is False


# -- exact hashing ---------------------------------------------------------


def test_raw_hash_is_whitespace_sensitive():
    assert raw_hash("a b") != raw_hash("a  b")


def test_normalized_hash_ignores_case_punctuation_and_spacing():
    assert normalized_hash("Hello, World!") == normalized_hash("hello   world")


def test_structural_hash_ignores_digits():
    assert structural_hash("Price: 100 USD") == structural_hash("Price: 250 USD")


def test_normalized_hash_does_not_ignore_digits():
    assert normalized_hash("Price 100") != normalized_hash("Price 250")


def test_signatures_returns_all_three_levels():
    assert set(signatures("hello")) == {"raw", "normalized", "structural"}


def test_exact_deduper_reports_first_key():
    d = ExactDeduper("normalized")
    assert d.check("k1", "Hello World") == (False, None)
    assert d.check("k2", "hello world") == (True, "k1")
    assert len(d) == 1


def test_exact_deduper_rejects_unknown_level():
    with pytest.raises(ValueError, match="unknown level"):
        ExactDeduper("nonsense")

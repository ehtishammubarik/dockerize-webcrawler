import pytest

from webcorpus.embed.encoder import (
    Batch,
    adaptive_batches,
    embed_all,
    padding_efficiency,
    select_device,
)


class StubEncoder:
    """Deterministic stand-in for a real model. Records the batches it saw."""

    def __init__(self, dim=4):
        self.dim = dim
        self.seen = []

    def encode(self, texts):
        self.seen.append(tuple(texts))
        return [[float(len(t))] * self.dim for t in texts]


class BadEncoder:
    def encode(self, texts):
        return [[0.0]]  # wrong count on purpose


def test_empty_input_yields_no_batches():
    assert adaptive_batches([]) == []


def test_every_text_appears_exactly_once():
    texts = [f"text number {i} " * (i % 7 + 1) for i in range(50)]
    got = [i for b in adaptive_batches(texts) for i in b.indices]
    assert sorted(got) == list(range(50))


def test_max_batch_size_is_respected():
    texts = ["x"] * 100
    assert all(len(b) <= 8 for b in adaptive_batches(texts, max_batch_size=8))


def test_token_cap_is_respected():
    texts = ["x" * 100] * 20
    for b in adaptive_batches(texts, max_batch_tokens=500, max_batch_size=1000):
        assert b.padded_tokens <= 500 or len(b) == 1


def test_oversized_single_text_gets_its_own_batch_not_dropped():
    texts = ["y" * 10_000, "short"]
    batches = adaptive_batches(texts, max_batch_tokens=100)
    assert sorted(i for b in batches for i in b.indices) == [0, 1]


def test_sorting_improves_padding_efficiency():
    # Alternating very short and very long texts. Batch size is the binding
    # constraint here; with a token cap that binds first, both orderings
    # produce the same batches and sorting buys nothing. That is the case
    # worth knowing about when tuning, so it is asserted separately below.
    texts = ["a" * (1 if i % 2 else 500) for i in range(40)]
    opts = {"max_batch_size": 4, "max_batch_tokens": 10**9}
    sorted_eff = padding_efficiency(adaptive_batches(texts, sort_by_length=True, **opts))
    unsorted_eff = padding_efficiency(adaptive_batches(texts, sort_by_length=False, **opts))
    assert sorted_eff > unsorted_eff
    assert sorted_eff == pytest.approx(1.0)


def test_sorting_is_neutral_when_token_cap_binds_first():
    # Documents the regime where sorting does not help: the token cap forces
    # the same max_len into every batch regardless of order.
    texts = ["a" * (1 if i % 2 else 500) for i in range(40)]
    opts = {"max_batch_tokens": 16_384, "max_batch_size": 64}
    assert padding_efficiency(
        adaptive_batches(texts, sort_by_length=True, **opts)
    ) == pytest.approx(padding_efficiency(adaptive_batches(texts, sort_by_length=False, **opts)))


def test_embed_all_restores_original_order():
    texts = ["a", "bbbb", "cc", "ddddddd", "e"]
    vecs = embed_all(texts, StubEncoder(), max_batch_size=2)
    # Stub encodes length into every component, so order is verifiable.
    assert [v[0] for v in vecs] == [float(len(t)) for t in texts]


def test_embed_all_handles_empty_input():
    assert embed_all([], StubEncoder()) == []


def test_encoder_returning_wrong_count_raises():
    with pytest.raises(ValueError, match="vectors for a batch"):
        embed_all(["a", "b", "c"], BadEncoder(), max_batch_size=3)


def test_invalid_batch_size_raises():
    with pytest.raises(ValueError, match="max_batch_size"):
        adaptive_batches(["a"], max_batch_size=0)


def test_padding_efficiency_of_uniform_batch_is_one():
    b = Batch((0, 1), ("abcd", "efgh"))
    assert padding_efficiency([b]) == 1.0


def test_padding_efficiency_of_empty_is_one():
    assert padding_efficiency([]) == 1.0


def test_select_device_honours_explicit_choice():
    assert select_device("cpu") == "cpu"
    assert select_device("cuda") == "cuda"


def test_select_device_auto_falls_back_without_torch():
    # torch is absent in CI; auto must degrade rather than raise.
    assert select_device("auto") in {"cpu", "cuda", "mps"}

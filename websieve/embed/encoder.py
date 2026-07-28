"""GPU-aware batch embedding.

The batching, sorting, and device-selection logic here is the part that
actually determines throughput, and it is testable without a GPU. The model
call itself is behind the ``Encoder`` protocol, so the pipeline can be
exercised end to end with a stub in CI and swapped for a real model in
production.

Two things dominate embedding throughput on a GPU, and neither is the model:

1. **Padding waste.** A batch is as slow as its longest sequence. Sorting by
   length before batching means short documents are not padded up to the
   longest one in the corpus. On heterogeneous web text this is commonly a
   2 to 4x difference.
2. **Batch size versus memory.** Too small wastes the device; too large gets
   you an out-of-memory error partway through a long job. ``adaptive_batches``
   caps on total token count rather than record count, so a batch of long
   documents is automatically smaller.

Order is restored before yielding, so callers never see the sorted order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol


class Encoder(Protocol):
    """Anything that turns a batch of strings into vectors."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class Batch:
    """A batch of texts with their original positions."""

    indices: tuple[int, ...]
    texts: tuple[str, ...]

    @property
    def max_len(self) -> int:
        return max((len(t) for t in self.texts), default=0)

    @property
    def padded_tokens(self) -> int:
        """Tokens actually processed, including padding waste."""
        return self.max_len * len(self.texts)

    def __len__(self) -> int:
        return len(self.texts)


def adaptive_batches(
    texts: Sequence[str],
    *,
    max_batch_tokens: int = 16_384,
    max_batch_size: int = 64,
    sort_by_length: bool = True,
) -> list[Batch]:
    """Group texts into batches bounded by padded token count.

    Args:
        texts: Documents to embed.
        max_batch_tokens: Cap on ``max_len * batch_size``. This is the real
            memory driver on a GPU, not record count.
        max_batch_size: Hard cap on records per batch.
        sort_by_length: Sort before batching to minimize padding. Original
            indices are preserved on each batch so order can be restored.

    A single text longer than ``max_batch_tokens`` still gets its own batch
    rather than being dropped. Truncation is the model's concern, not ours.
    """
    if not texts:
        return []
    if max_batch_size < 1:
        raise ValueError("max_batch_size must be >= 1")

    order = list(range(len(texts)))
    if sort_by_length:
        order.sort(key=lambda i: len(texts[i]))

    batches: list[Batch] = []
    cur: list[int] = []
    cur_max = 0

    for i in order:
        candidate_max = max(cur_max, len(texts[i]))
        if cur and (
            candidate_max * (len(cur) + 1) > max_batch_tokens or len(cur) + 1 > max_batch_size
        ):
            batches.append(Batch(tuple(cur), tuple(texts[j] for j in cur)))
            cur = [i]
            cur_max = len(texts[i])
        else:
            cur.append(i)
            cur_max = candidate_max

    if cur:
        batches.append(Batch(tuple(cur), tuple(texts[j] for j in cur)))
    return batches


def embed_all(
    texts: Sequence[str],
    encoder: Encoder,
    *,
    max_batch_tokens: int = 16_384,
    max_batch_size: int = 64,
    sort_by_length: bool = True,
) -> list[list[float]]:
    """Embed every text, returning vectors in the original input order."""
    out: list[list[float] | None] = [None] * len(texts)
    for batch in adaptive_batches(
        texts,
        max_batch_tokens=max_batch_tokens,
        max_batch_size=max_batch_size,
        sort_by_length=sort_by_length,
    ):
        vectors = encoder.encode(batch.texts)
        if len(vectors) != len(batch):
            raise ValueError(f"encoder returned {len(vectors)} vectors for a batch of {len(batch)}")
        for idx, vec in zip(batch.indices, vectors, strict=True):
            out[idx] = vec
    missing = [i for i, v in enumerate(out) if v is None]
    if missing:
        raise RuntimeError(f"{len(missing)} texts were not embedded, first at index {missing[0]}")
    return out  # type: ignore[return-value]


def padding_efficiency(batches: Iterable[Batch]) -> float:
    """Fraction of processed tokens that were real rather than padding.

    Use it to tune ``max_batch_tokens`` against a real corpus. Below about 0.7
    means sorting is not helping and the length distribution is too spread out
    for the current batch size.
    """
    real = 0
    padded = 0
    for b in batches:
        real += sum(len(t) for t in b.texts)
        padded += b.padded_tokens
    return (real / padded) if padded else 1.0


def select_device(prefer: str = "auto") -> str:
    """Pick a torch device string without importing torch unless needed.

    Returns ``cuda``, ``mps``, or ``cpu``. Falls back to ``cpu`` when torch is
    absent, so the pipeline runs anywhere and only the throughput changes.
    """
    if prefer != "auto":
        return prefer
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class SentenceTransformerEncoder:
    """Adapter for ``sentence-transformers``. Requires that optional extra.

    Not exercised in CI, which has no GPU and does not install torch. The
    batching it sits behind is tested; this class is a thin call-through.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "auto",
        normalize: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(
                "SentenceTransformerEncoder requires the 'embed' extra. "
                "Install with 'pip install websieve[embed]'."
            ) from exc
        self.device = select_device(device)
        self.normalize = normalize
        self.model = SentenceTransformer(model_name, device=self.device)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        vecs = self.model.encode(
            list(texts),
            batch_size=len(texts),
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vecs]

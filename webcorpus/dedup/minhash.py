"""Near-duplicate detection by MinHash with LSH banding.

Exact hashing catches byte-identical pages and nothing else. Web corpora are
full of pages that differ only by a timestamp, a session id, or one paragraph
of navigation. Training on them wastes compute and measurably degrades models,
which is why every serious corpus pipeline does near-dedup.

The method:

1. Shingle the document into overlapping word n-grams.
2. Hash each shingle; keep the minimum under ``num_perm`` independent hash
   functions. That vector is the signature. The probability two signatures
   agree at any position equals the Jaccard similarity of the shingle sets.
3. Split the signature into ``bands`` rows. Two documents become candidates if
   any whole band matches. This is Locality Sensitive Hashing: it turns an
   O(n^2) all-pairs comparison into a hash lookup.

Implemented with stdlib only. A permutation is simulated as
``(a * h + b) mod p`` over a Mersenne prime, which is the standard universal
hashing construction and avoids needing numpy.

Reference: Broder (1997), "On the resemblance and containment of documents";
Leskovec, Rajaraman & Ullman, "Mining of Massive Datasets", chapter 3.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field

# Mersenne prime 2^61 - 1. Large enough that collisions are negligible, small
# enough that products stay in Python's fast integer path on 64-bit builds.
_MERSENNE = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1

_TOKEN = re.compile(r"\w+", re.UNICODE)


def shingles(text: str, n: int = 5) -> set[str]:
    """Overlapping word n-grams.

    Word shingles rather than character shingles: they are more robust to
    formatting differences, which is exactly the noise we want to ignore.

    ``n=5`` is the usual default. Lower values raise recall and false-positive
    rate; higher values make the signature brittle to small edits.
    """
    tokens = _TOKEN.findall(text.lower())
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _base_hash(shingle: str) -> int:
    return int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")


@dataclass(slots=True)
class MinHash:
    """MinHash signature generator.

    ``num_perm`` trades accuracy for cost linearly. 128 gives a standard error
    of roughly 1/sqrt(128), about 0.088, on the Jaccard estimate.
    """

    num_perm: int = 128
    seed: int = 1
    _a: list[int] = field(default_factory=list, repr=False)
    _b: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self._a = [rng.randrange(1, _MERSENNE) for _ in range(self.num_perm)]
        self._b = [rng.randrange(0, _MERSENNE) for _ in range(self.num_perm)]

    def signature(self, text: str, *, n: int = 5) -> tuple[int, ...]:
        """Compute the signature vector for a document."""
        shs = shingles(text, n)
        if not shs:
            return tuple([_MAX_HASH] * self.num_perm)

        base = [_base_hash(s) for s in shs]
        sig = []
        for a, b in zip(self._a, self._b, strict=True):
            sig.append(min(((a * h + b) % _MERSENNE) & _MAX_HASH for h in base))
        return tuple(sig)

    @staticmethod
    def similarity(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
        """Estimated Jaccard similarity between two signatures."""
        if len(sig_a) != len(sig_b):
            raise ValueError(f"signature length mismatch: {len(sig_a)} vs {len(sig_b)}")
        if not sig_a:
            return 0.0
        return sum(1 for x, y in zip(sig_a, sig_b, strict=True) if x == y) / len(sig_a)


@dataclass(slots=True)
class LSHIndex:
    """Banded LSH index over MinHash signatures.

    The threshold at which a pair becomes likely to be a candidate is
    approximately ``(1 / bands) ** (1 / rows)``. Choose ``bands`` to place that
    knee where you want it: more bands means higher recall and more candidates
    to verify.
    """

    num_perm: int = 128
    bands: int = 32
    _buckets: dict[tuple[int, tuple[int, ...]], list[str]] = field(default_factory=dict, repr=False)
    _signatures: dict[str, tuple[int, ...]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.num_perm % self.bands != 0:
            raise ValueError(
                f"num_perm ({self.num_perm}) must be divisible by bands ({self.bands})"
            )

    @property
    def rows(self) -> int:
        return self.num_perm // self.bands

    @property
    def approx_threshold(self) -> float:
        """Similarity at which a pair is roughly 50 percent likely to collide."""
        return (1.0 / self.bands) ** (1.0 / self.rows)

    def add(self, key: str, signature: tuple[int, ...]) -> None:
        if len(signature) != self.num_perm:
            raise ValueError(f"signature length {len(signature)} != num_perm {self.num_perm}")
        self._signatures[key] = signature
        for i in range(self.bands):
            band = signature[i * self.rows : (i + 1) * self.rows]
            self._buckets.setdefault((i, band), []).append(key)

    def query(self, signature: tuple[int, ...], *, exclude: str | None = None) -> set[str]:
        """Return candidate keys sharing at least one band."""
        out: set[str] = set()
        for i in range(self.bands):
            band = signature[i * self.rows : (i + 1) * self.rows]
            out.update(self._buckets.get((i, band), ()))
        out.discard(exclude)
        return out

    def duplicates(
        self, signature: tuple[int, ...], threshold: float, *, exclude: str | None = None
    ) -> list[tuple[str, float]]:
        """Candidates verified against the real signature similarity.

        LSH gives candidates, not answers. Verification is what keeps the false
        positive rate down, and it is cheap because the candidate set is small.
        """
        out = []
        for key in self.query(signature, exclude=exclude):
            s = MinHash.similarity(signature, self._signatures[key])
            if s >= threshold:
                out.append((key, s))
        return sorted(out, key=lambda kv: kv[1], reverse=True)

    def __len__(self) -> int:
        return len(self._signatures)


def deduplicate(
    docs, *, threshold: float = 0.8, num_perm: int = 128, bands: int = 32, ngram: int = 5
):
    """Greedy first-wins near-dedup over an iterable of ``(key, text)``.

    Yields ``(key, is_duplicate, matched_key, similarity)``. The first document
    in a cluster is kept; later ones are marked duplicates of it. Streaming and
    single-pass, so memory grows with corpus size but not with corpus squared.
    """
    hasher = MinHash(num_perm=num_perm)
    index = LSHIndex(num_perm=num_perm, bands=bands)

    for key, text in docs:
        sig = hasher.signature(text, n=ngram)
        matches = index.duplicates(sig, threshold)
        if matches:
            best_key, best_sim = matches[0]
            yield (key, True, best_key, best_sim)
        else:
            index.add(key, sig)
            yield (key, False, None, 0.0)

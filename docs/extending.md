# Extending websieve

Every stage is swappable. The pipeline is deliberately small and boring so that
replacing a piece is a normal afternoon rather than a fork.

## What you can change, at a glance

| You want to | Difficulty | Where |
| :--- | :--- | :--- |
| Adjust a quality threshold | Trivial | Pass a custom rule tuple to `assess` |
| Add a quality rule | Easy | Any `Callable[[str], Rule]` |
| Disable a whole stage | Trivial | `PipelineConfig(run_quality=False)` |
| Swap the extractor | Easy | Any callable returning `(text, title)` |
| Swap the embedding model | Easy | Implement the `Encoder` protocol |
| Add an output format | Easy | Mirror `JsonlShardWriter` |
| Change dedup similarity | Moderate | Subclass or replace `MinHash` |
| Reorder stages | Moderate | Subclass `Pipeline.process` |

## Adjust thresholds

The fastest and most common customization. Defaults suit general web text and
are usually wrong for a domain corpus.

```python
from websieve.quality.heuristics import assess, word_count, repetition_ratio

rules = (
    lambda t: word_count(t, lo=15),      # docs pages are legitimately short
    lambda t: repetition_ratio(t, max_ratio=0.5),
)
report = assess(text, rules=rules)
```

## Add a quality rule

A rule is any callable taking text and returning a `Rule`. Returning the
observed value and the threshold is what makes the failure report useful, so do
not shortcut to a bare bool.

```python
from websieve.quality.heuristics import Rule, DEFAULT_RULES, assess, words

def code_block_ratio(text: str, *, max_ratio: float = 0.5) -> Rule:
    """Reject pages that are mostly code when you want prose."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return Rule("code_block_ratio", False, 1.0, max_ratio)
    codey = sum(1 for ln in lines if ln.startswith(("    ", "\t")) or ln.rstrip().endswith((";", "{", "}")))
    ratio = codey / len(lines)
    return Rule("code_block_ratio", ratio <= max_ratio, round(ratio, 4), max_ratio)

report = assess(text, rules=DEFAULT_RULES + (code_block_ratio,))
```

The rule name appears in `stats.json` automatically, so you get attribution for
free.

## Swap the extractor

The built-in extractor is dependency-free and therefore a heuristic. When
accuracy matters more than portability, use a real one.

```python
import trafilatura
from websieve.pipeline import Pipeline, PipelineConfig
from websieve.models import Document

def crawl_with_trafilatura(raw_pages):
    for url, html in raw_pages:
        text = trafilatura.extract(html) or ""
        yield Document(url=url, text=text)      # text set, so extraction is skipped

pipeline = Pipeline(PipelineConfig())
for doc in pipeline.process(crawl_with_trafilatura(pages)):
    ...
```

Setting `text` means `prepare()` leaves it alone. No subclassing required.

## Swap the embedding model

Implement one method. Anything satisfying this works, including an API client.

```python
class MyEncoder:
    def encode(self, texts):                 # Sequence[str] -> list[list[float]]
        return my_model.embed(list(texts))

from websieve.embed.encoder import embed_all
vectors = embed_all(texts, MyEncoder(), max_batch_tokens=8192)
```

`embed_all` handles batching, length sorting, and restoring the original order.
It raises if your encoder returns the wrong number of vectors, rather than
silently misaligning documents and embeddings, which is a bug you would
otherwise find months later in a vector index.

## Add an output format

Mirror the `JsonlShardWriter` interface: `write`, `close` returning a manifest,
and context manager support.

```python
class MyWriter:
    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
    def write(self, record: dict) -> None: ...
    def close(self) -> dict: ...             # return a manifest dict
```

If it needs a third-party package, guard the import inside `__init__` and add
an extra to `pyproject.toml`, following `ParquetShardWriter`. The core stays
dependency-free and CI enforces it.

## Change how similarity is measured

`MinHash` and `LSHIndex` are plain dataclasses. To use SimHash, character
shingles, or a different hash, replace them and keep the interface: a
`signature(text)` and a `similarity(a, b)`.

Two constraints that are not optional:

1. **Verify candidates.** LSH gives you candidates, not answers. Skipping the
   verification step raises the false positive rate silently.
2. **Changing the hash, seed, or shingle size invalidates every stored
   signature.** Version your output if you have signatures on disk.

## Reorder or replace stages

`Pipeline.process` is one readable loop. Subclass it.

```python
class MyPipeline(Pipeline):
    def process(self, docs):
        for doc in docs:
            prepare(doc, self.config)
            if my_own_filter(doc):
                yield doc
```

Before reordering, read [`architecture.md`](architecture.md). The current order
is cost-ordered: each stage exists partly to shrink the input to the next. Running
quality before exact dedup, for instance, means running nine heuristics against
documents that a single hash would have removed.

## What you cannot easily change

Stated so you do not discover it three hours in.

- **The `Document` schema** is a `slots=True` dataclass. Extra fields go in
  `meta`, which is a free-form dict carried through untouched.
- **Dedup is in-process.** No shared or persistent index. Distributed dedup
  means partitioning by URL host and merging results yourself.
- **There is no plugin system**, deliberately. Composition and subclassing
  cover the real cases without an abstraction layer to learn.

## Contributing your extension back

If your rule or writer is generally useful, open a PR. See
[CONTRIBUTING.md](../CONTRIBUTING.md). Rules with a citation to a published
recipe are especially welcome.

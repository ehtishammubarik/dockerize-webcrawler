# Roadmap

Honest about status: `websieve` is early. The core pipeline works and is
tested, but it has not yet been run against a corpus of tens of millions of
documents by anyone other than the author. Treat version numbers accordingly.

## Now (0.1.x)

Shipped and covered by tests.

- Boilerplate extraction, Unicode normalization
- Nine Gopher and C4 quality heuristics with per-rule attribution
- Exact dedup at three levels, MinHash and LSH near-dedup
- Adaptive batching for embedding
- Sharded JSONL and Parquet output with verifiable manifests
- `build`, `assess`, `dedup`, `extract` commands

## Next (0.2)

The gaps that most affect whether this is usable on a real corpus.

| Item | Why it matters |
| :--- | :--- |
| **Language detection and filtering** | The quality thresholds assume space-delimited text and currently misjudge Chinese, Japanese, and Thai. This is the biggest correctness gap |
| **Resumable runs** | A crash 8 hours into a 12-hour job currently means starting over |
| **Persistent dedup index** | Save and load the LSH index so a second crawl can be deduplicated against the first |
| **Progress reporting** | `build` is silent until it finishes, which is unpleasant at corpus scale |
| **`--sample N`** | Assess a random sample rather than the whole file when calibrating |

## Later (0.3+)

- **Parallel processing.** Multiprocessing over shards. Dedup is the hard part
  because the index is shared state; likely partition by URL host.
- **PII detection.** Currently absent, and its absence is a compliance trap for
  anyone publishing a dataset. Probably a separate optional extra.
- **Quality classifier.** An optional learned filter alongside the heuristics,
  in the style of the FineWeb educational classifier.
- **Streaming from object storage.** Read a crawl directly from S3 or GCS
  without staging it locally.
- **Benchmark suite.** Throughput and quality measured against a public crawl
  sample, so performance claims are reproducible rather than asserted.

## Not planned

Saying no is part of a roadmap.

- **A crawler.** Scrapy exists and is good. `websieve` starts where it ends.
- **Distributed execution.** If you need a cluster, use HuggingFace's
  `datatrove`. Running in one process with no dependencies is the point here,
  and the right trade below roughly ten million documents.
- **A plugin system.** Composition and subclassing already cover the real
  cases. See [`docs/extending.md`](docs/extending.md).
- **Dependencies in the core.** Permanent. CI enforces it.

## Influencing this list

The order is a guess, and a real use case beats a guess.

- **Open an issue** describing what you are building and where this got in the
  way. Concrete beats abstract: corpus size, document type, and what broke.
- **Email** [contact@eprecisio.com](mailto:contact@eprecisio.com) if an issue is
  not the right shape, for instance commercial use or a private corpus.
- **LinkedIn:** [Ehtisham Mubarik](https://www.linkedin.com/in/ehtisham-mubarik)
  or [Eprecisio Technologies](https://www.linkedin.com/company/eprecisio/)

Issues labelled [`good first issue`](https://github.com/ehtishammubarik/websieve/labels/good%20first%20issue)
are scoped so that a first contribution does not require reading the whole
codebase. [`help wanted`](https://github.com/ehtishammubarik/websieve/labels/help%20wanted)
marks items I would genuinely rather not do alone.

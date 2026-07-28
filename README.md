# webcorpus

**Turn a web crawl into an ML-ready dataset.** Extract, filter, deduplicate, embed, shard.

[![CI](https://github.com/ehtishammubarik/dockerize-webcrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/ehtishammubarik/dockerize-webcrawler/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/core%20dependencies-none-success)
![Coverage](https://img.shields.io/badge/coverage-92%25-success)
![License](https://img.shields.io/badge/license-MIT-blue)

Crawling is the easy part. What stops a crawl from being training data is everything after it:
navigation chrome mixed into the text, the same page under six URLs, SEO spam that reads like prose
to a regex, and a corpus that will not fit in memory when you try to deduplicate it.

`webcorpus` is the stage between your crawler and your model.

```
crawl -> extract -> normalize -> exact dedup -> quality -> near dedup -> embed -> shards
         boilerplate  NFKC       3 levels       9 rules    MinHash+LSH   batched
```

**The core has no dependencies.** Not "few". None. It runs inside whatever scraper container you
already have, on a build box with no wheels, or in an air-gapped environment, and the only thing
that changes is throughput. `pyarrow`, `torch`, and `scrapy` are optional extras used only by the
stages that genuinely need them.

## Install

```bash
pip install webcorpus                # core, zero dependencies
pip install "webcorpus[parquet]"     # + Parquet output
pip install "webcorpus[embed]"       # + GPU embedding
pip install "webcorpus[all]"
```

## Use

Pipe a crawl straight in:

```bash
scrapy crawl myspider -o - -t jsonlines | webcorpus build - -o dataset/
```

Or run against a file:

```bash
webcorpus build crawl.jsonl -o dataset/ --threshold 0.85 --shard-size 50000
```

You get sharded output, a manifest, and a stats report:

```
dataset/
  shard-00000.jsonl.gz
  shard-00001.jsonl.gz
  manifest.json     every shard, its record count, its size
  stats.json        what was dropped, and by which rule
```

```
seen        50000
kept        18342  (36.7%)
dropped     31658
  empty              412
  exact duplicate   9884
  quality          14022
  near duplicate    7340
quality rule failures (a document can fail several):
  word_count                   8110
  terminal_punctuation_ratio   6033
  repetition_ratio             2914
```

That breakdown is the point. A filter you cannot attribute is a filter you cannot tune.

### Inspect before you commit

```bash
webcorpus assess crawl.jsonl -v      # what would be dropped, and why. Drops nothing.
webcorpus dedup  crawl.jsonl         # duplicate clusters with similarity scores
webcorpus extract page.html          # main-content text from one page
```

### As a library

```python
from webcorpus.pipeline import Pipeline, PipelineConfig
from webcorpus.models import Document

pipeline = Pipeline(PipelineConfig(near_dup_threshold=0.85))
for doc in pipeline.process(Document(url=u, html=h) for u, h in crawl()):
    index(doc.text)

print(pipeline.stats.render())
```

Every stage also stands alone:

```python
from webcorpus.quality.heuristics import assess
from webcorpus.dedup.minhash import MinHash, LSHIndex
from webcorpus.clean.boilerplate import extract
```

## What each stage does

### Extraction

Text-density heuristic, not a readability port. Blocks are scored by length and link density, then
the best contiguous run is kept, so navigation and footers fall away because they are short and
mostly links. Headings adjacent to the body are reclaimed, because Kadane's algorithm will not pick
them up on its own and an article without its title is a worse document.

No dependencies. If you can afford one and need higher accuracy, use `trafilatura` and feed its
output into the quality stage instead.

### Quality

Nine rules from the published recipes for large web corpora, chiefly the Gopher rules
(Rae et al., 2021) and the C4 cleanup (Raffel et al., 2020): word count, mean word length, symbol
ratio, alphabetic ratio, bullet and ellipsis line ratios, terminal punctuation, line repetition, and
boilerplate markers.

Reimplemented rather than vendored so every threshold is visible and adjustable. The right values
genuinely differ between general web text and a domain corpus, and you cannot tune what you cannot
see. **Every rule runs even after one fails**, so the failure histogram is complete.

### Deduplication

Two passes, cheap before expensive.

**Exact**, at three levels. `raw` is byte-identical. `normalized` ignores case, punctuation, and
spacing. `structural` also collapses digits, which catches templated pages differing only by a
price, date, or id. That last one will merge genuinely different pages whose only distinguishing
content is numeric, so choose it deliberately.

**Near**, by MinHash with LSH banding. Shingle into word n-grams, keep the minimum under `num_perm`
hash permutations, then band the signature so candidate lookup is a hash hit instead of an O(n^2)
scan. Candidates are verified against real signature similarity afterwards, because LSH returns
candidates, not answers.

Permutations are simulated as `(a*h + b) mod p` over a Mersenne prime, the standard universal
hashing construction, which is why this needs no numpy. Accuracy is what the theory predicts:

| Pair | True Jaccard | MinHash estimate, 256 perms |
| :--- | ---: | ---: |
| One word differs | 0.833 | 0.863 |
| Unrelated documents | 0.000 | 0.000 |
| Identical | 1.000 | 1.000 |

### Embedding

The model call sits behind a `Protocol`, so the part that actually governs throughput is testable
without a GPU and CI exercises it with a stub.

Two things dominate embedding throughput, and neither is the model:

- **Padding waste.** A batch is as slow as its longest sequence. Sorting by length before batching
  keeps short documents from being padded up to the longest one in the corpus.
- **Batch size versus memory.** `adaptive_batches` caps on `max_len * batch_size` rather than record
  count, so a batch of long documents automatically becomes a smaller batch.

`padding_efficiency()` reports how much of what you processed was real rather than padding. Below
about 0.7, the length distribution is too spread out for the current batch size.

Worth knowing: sorting helps when batch size is the binding constraint. When the token cap binds
first, both orderings produce identical batches and sorting buys nothing. Both regimes are asserted
in the tests rather than assumed.

### Output

Sharded JSONL (gzip) or Parquet. Many medium shards rather than one large file, because shards
parallelize across dataloader workers, resume cleanly after a failure, and stream from object
storage without a full download.

Both writers emit `manifest.json`. `read_shards()` reads it rather than globbing the directory, so
a truncated or partially uploaded dataset raises an error instead of silently yielding fewer records
than you think you have.

## Tuning

| Symptom | Change |
| :--- | :--- |
| Keeping too much junk | Lower `--threshold` toward 0.7; raise the `word_count` minimum |
| Dropping good documents | Raise `--threshold`; check `stats.json` for the dominant rule |
| Dedup too slow | Lower `--num-perm` to 64 |
| Missing obvious duplicates | Raise `--bands` for higher recall and more candidates to verify |
| Templated pages surviving | `--exact-level structural` |
| Low padding efficiency | Lower `max_batch_tokens`, keep `sort_by_length=True` |

`PipelineConfig` exposes all of it. See [`docs/tuning.md`](docs/tuning.md) and
[`docs/architecture.md`](docs/architecture.md).

## Testing

```bash
pip install -e ".[dev]"
pytest
```

107 tests, 92 percent line coverage, no network access and no GPU required. The uncovered remainder
is `ParquetShardWriter` and `SentenceTransformerEncoder`, which need `pyarrow` and `torch` and are
not installed in CI. They are thin call-throughs; the logic they sit behind is covered.

CI runs on Python 3.10, 3.11, and 3.12, and includes a job that **fails if the core ever acquires a
runtime dependency**.

## Origin

This repository began as a containerized Scrapy deployment (Scrapy, Scrapyd, Postgres, Filebeat,
Jenkins) built for a Swiss real-estate crawl. That crawler is still here under `immo_crawl/` as a
working integration example. `webcorpus` is the part that was missing: everything between a finished
crawl and a dataset you would actually train on.

## License

MIT. See [LICENSE](LICENSE).

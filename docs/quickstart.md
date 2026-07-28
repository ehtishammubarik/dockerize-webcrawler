# Quickstart

Five minutes, no crawler required. Every output below is real; run it and compare.

## 1. Install

```bash
pip install websieve
```

Or from source:

```bash
git clone https://github.com/ehtishammubarik/websieve
cd websieve && pip install -e ".[dev]"
```

## 2. Make a tiny crawl file

`websieve` reads JSONL with a `url` and either `html` or `text`. Save this as `crawl.jsonl`:

```bash
cat > crawl.jsonl <<'JSONL'
{"url": "https://example.com/a", "html": "<html><head><title>GPU scheduling on Kubernetes</title></head><body><nav><a href='/'>Home</a><a href='/about'>About</a></nav><article><h1>GPU scheduling</h1><p>Kubernetes exposes GPUs through the NVIDIA device plugin, which advertises nvidia.com/gpu as an allocatable resource on every node in the pool. Once training and inference share the same hardware, fragmentation becomes the dominant concern: a node with three free GPUs cannot serve a job that wants four. MIG partitioning changes the shape of that problem by splitting a single A100 into as many as seven independent instances, which suits small inference models far better than whole-card allocation does. The trade is that MIG slices are fixed at configuration time, so a cluster tuned for inference will schedule training jobs badly.</p></article><footer>&copy; 2026 Example Inc. Privacy Policy</footer></body></html>"}
{"url": "https://example.com/a?utm_source=twitter", "html": "<html><head><title>GPU scheduling on Kubernetes</title></head><body><article><h1>GPU scheduling</h1><p>Kubernetes exposes GPUs through the NVIDIA device plugin, which advertises nvidia.com/gpu as an allocatable resource on every node in the pool. Once training and inference share the same hardware, fragmentation becomes the dominant concern: a node with three free GPUs cannot serve a job that wants four. MIG partitioning changes the shape of that problem by splitting a single A100 into as many as seven independent instances, which suits small inference models far better than whole-card allocation does. The trade is that MIG slices are fixed at configuration time, so a cluster tuned for inference will schedule training jobs badly.</p></article></body></html>"}
{"url": "https://example.com/nav", "text": "Home About Contact Login Register"}
{"url": "https://example.com/spam", "text": "Buy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now\nBuy cheap GPUs now"}
JSONL
```

Four documents: one real article, the same article under a tracking URL, a nav dump, and SEO spam.

## 3. See what would happen, without doing it

```bash
websieve assess crawl.jsonl -v
```

```
https://example.com/nav     word_count,terminal_punctuation_ratio
https://example.com/spam    repetition_ratio,terminal_punctuation_ratio
documents   4
would pass  2  (50.0%)
rule failures:
  terminal_punctuation_ratio   2
  word_count                   1
  repetition_ratio             1
```

`assess` never drops anything. Use it to calibrate before committing to a long run.

Note that it reports **2 would pass**, because `assess` only runs quality rules. Dedup happens in
`build`, which is why the next step keeps only one.

## 4. Build the dataset

```bash
websieve build crawl.jsonl -o dataset/
```

```
seen        4
kept        1  (25.0%)
dropped     3
  empty            0
  exact duplicate  1
  quality          2
  near duplicate   0
quality rule failures (a document can fail several):
  terminal_punctuation_ratio   2
  word_count                   1
  repetition_ratio             1

wrote 1 records in 1 shard(s) to dataset/
```

The tracking-parameter copy was caught as an **exact duplicate**: extraction stripped the nav from
the first page, so both normalized to identical text even though the HTML differed.

## 5. Look at the output

```bash
ls dataset/
# manifest.json  shard-00000.jsonl.gz  stats.json

zcat dataset/shard-00000.jsonl.gz | python3 -m json.tool
```

```json
{
  "url": "https://example.com/a",
  "text": "GPU scheduling\n\nKubernetes exposes GPUs through the NVIDIA device plugin, ...",
  "title": "GPU scheduling on Kubernetes",
  "quality": {"passed": true, "failures": [], "rules": {"word_count": {"passed": true, "value": 104, "threshold": 50}}},
  "signatures": {"raw": "81879111...", "normalized": "0745f9c2...", "structural": "a74bccb9..."},
  "doc_id": "2dce0a4c50441bfc"
}
```

## 6. Read it back

```python
from websieve.export.writers import read_shards

for record in read_shards("dataset/"):
    print(record["doc_id"], record["title"])
```

`read_shards` uses `manifest.json` rather than globbing, so a missing shard raises instead of
silently giving you a shorter dataset than you think you have.

## Next

- Real crawler: `scrapy crawl spider -o - -t jsonlines | websieve build - -o dataset/`
- Thresholds are wrong for your corpus: [`tuning.md`](tuning.md)
- Swap a stage: [`extending.md`](extending.md)
- Why the stages are ordered this way: [`architecture.md`](architecture.md)

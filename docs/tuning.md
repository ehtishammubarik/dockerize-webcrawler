# Tuning

Run `websieve assess` first. It reports what *would* be dropped without
dropping anything, so you can calibrate against your own corpus rather than
against defaults chosen for general web text.

```bash
websieve assess crawl.jsonl -v | head -50
```

## Reading stats.json

Every run writes `stats.json`. The field that matters is `quality_failures`: it
is a histogram over rules, and a document can appear under several.

```json
{
  "stats": {
    "seen": 50000, "kept": 18342, "keep_rate": 0.3668,
    "dropped_by_stage": {
      "empty": 412, "exact_duplicate": 9884,
      "quality": 14022, "near_duplicate": 7340
    },
    "quality_failures": { "word_count": 8110, "repetition_ratio": 2914 }
  }
}
```

One rule dominating the histogram usually means it is mistuned for your corpus,
not that your corpus is bad.

## Keep rate

There is no correct value, but there are recognizable failure modes.

| Keep rate | Usually means |
| ---: | :--- |
| Above 90% | Filtering is not doing anything. Check that quality is enabled |
| 30% to 70% | Typical for a general web crawl |
| Below 10% | Thresholds are wrong for this corpus, or extraction is failing upstream |

Before assuming the filter is too aggressive, run `websieve extract` on a few
pages. A low keep rate is very often an extraction problem wearing a quality
problem's clothes: if extraction returns nav text, quality correctly rejects it.

## Near-duplicate threshold

| Threshold | Effect |
| ---: | :--- |
| 0.9+ | Only very close copies. Templated pages survive |
| 0.8 | Default. Catches boilerplate-heavy near-copies |
| 0.7 | Aggressive. Will merge genuinely distinct pages on the same template |
| Below 0.6 | Expect real content loss |

## num_perm and bands

`num_perm` sets accuracy. Standard error on the Jaccard estimate is roughly
`1/sqrt(num_perm)`.

| num_perm | Standard error | Use when |
| ---: | ---: | :--- |
| 64 | 0.125 | Speed matters more than precision |
| 128 | 0.088 | Default |
| 256 | 0.063 | Threshold sits near a decision boundary |

`bands` sets where the recall knee falls, at approximately
`(1/bands) ** (1/rows)` where `rows = num_perm / bands`. More bands means
higher recall and more candidates to verify.

```python
LSHIndex(num_perm=128, bands=32).approx_threshold   # rows=4, knee near 0.42
LSHIndex(num_perm=128, bands=64).approx_threshold   # rows=2, knee near 0.125
```

Set `bands` so the knee sits somewhat below your `threshold`. Verification
removes the false positives; a knee above the threshold loses true ones
outright, and those you never see.

## Domain corpora

The defaults come from general-web recipes. Narrow corpora usually need:

- **Lower `word_count` minimum.** 50 words drops legitimate short entries in
  documentation and product catalogues.
- **Lower `terminal_punctuation_ratio`.** Reference material and API docs are
  full of legitimate lines that do not end in a period.
- **Raised `bullet_line_ratio`.** Technical documentation really is mostly
  lists, and that is not a defect.
- **`--exact-level raw`** if numeric differences are the signal you are after.

```python
from websieve.quality.heuristics import assess, word_count, repetition_ratio

rules = (lambda t: word_count(t, lo=15), repetition_ratio)
report = assess(text, rules=rules)
```

## Embedding throughput

```python
from websieve.embed.encoder import adaptive_batches, padding_efficiency

batches = adaptive_batches(texts, max_batch_tokens=16_384)
print(padding_efficiency(batches))
```

Below about 0.7, lower `max_batch_tokens` so extreme lengths stop sharing a
batch. Keep `sort_by_length=True` unless you need strict streaming order.

Note that sorting only helps when batch size is the binding constraint. When
the token cap binds first, both orderings produce identical batches. Both
regimes are asserted in `tests/test_embed.py`.

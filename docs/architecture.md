# Architecture

## Why the stages are in this order

Each stage costs more than the one before it, so each exists partly to shrink
the input to the next.

```
extract -> normalize -> exact dedup -> quality -> near dedup -> embed
 parse       regex        1 hash       9 rules    n hashes     model
```

| Boundary | Reason |
| :--- | :--- |
| normalize before any comparison | Two byte encodings of one character defeat both hashing and the ratio thresholds |
| exact dedup before quality | One hash beats nine heuristics, and typically removes a large share of a crawl |
| quality before near dedup | A MinHash signature costs `num_perm` hashes per shingle. Signing a document you are about to drop is pure waste |
| embed last | Orders of magnitude more expensive than everything above it combined |

Reordering is possible but has a cost. Running quality before exact dedup, for
instance, means running nine heuristics against documents a single hash would
have removed.

## Memory

The pipeline is a generator. Memory grows with documents *kept*, not documents
*seen*, because the only retained state is the dedup index:

- `ExactDeduper` holds one 16-byte digest plus one key per unique document.
- `LSHIndex` holds a `num_perm`-length signature per kept document, plus
  `bands` bucket entries pointing at it.

For a 10 million document corpus at `num_perm=128`, the LSH signatures alone
are roughly 10 GB in CPython, because each signature is a tuple of 128 Python
ints. That is the practical ceiling for a single process.

Past it, shard by URL host: near-duplicates are overwhelmingly same-host, so
partitioning by host and deduplicating each partition independently loses very
little recall and parallelizes cleanly.

## Why no dependencies

Not minimalism for its own sake. This code runs in three places where
dependencies are genuinely expensive:

1. **Inside a scraper container** you do not control, where adding `numpy`
   means rebuilding someone else's image.
2. **Air-gapped environments**, where every wheel is a procurement conversation.
3. **CI**, where a dependency-free core installs in under a second.

The cost is real: a pure-Python MinHash is several times slower than a numpy
one. That trade is stated rather than hidden, and the optional extras exist for
callers who would rather have the speed.

The CI job that fails on any acquired runtime dependency exists because this
claim rots the first time someone adds a convenient import, and it would pass
tests in a fatter dev environment.

## Extension points

| To change | Implement |
| :--- | :--- |
| Extraction | Anything returning `(text, title)`; swap it in `Pipeline.process` |
| Quality rules | A `Callable[[str], Rule]`, then pass a custom tuple to `assess` |
| Embedding model | The `Encoder` protocol: one `encode(texts) -> list[list[float]]` |
| Output format | Mirror `JsonlShardWriter`: `write`, `close`, and a manifest |

## Known limitations

Stated plainly, because a limitation you find yourself is worse than one you
were told about.

- **Extraction is a heuristic.** It will lose content on pages whose body is
  fragmented across many short blocks, and keep a sidebar that happens to be
  long and prose-like. Use `trafilatura` when accuracy matters more than
  portability.
- **Script is detected, language is not.** The rule set adapts to the writing
  system, which is what the thresholds actually depend on. It will not tell you
  Mandarin from Cantonese, or Hindi from Marathi, because that needs a model and
  no threshold here varies on it.
- **Dedup is greedy and order-dependent.** The first document in a cluster
  wins. Feeding the corpus in a different order can keep a different
  representative.
- **`structural` exact hashing merges numeric-only differences** by design.
  Wrong for price tracking, right for training corpora.
- **The LSH index is in-process.** No persistence, no sharing between workers.

---
name: corpus-pipeline
description: Working on the webcorpus crawl-to-dataset pipeline. Use for changes to extraction, quality heuristics, deduplication, embedding batching, sharded output, or the stage ordering. Covers the zero-dependency constraint and how to validate a filtering change against a real corpus.
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Corpus pipeline

You are working on a filtering pipeline whose output becomes training data. A
bug here does not crash; it quietly produces a worse corpus, and nobody notices
until a model is worse for reasons no one can attribute.

## The constraint that governs every change

`webcorpus/` imports **stdlib only**. Before adding an import, confirm it is
stdlib. If a stage genuinely needs a third party package:

1. Guard the import inside the function that uses it.
2. Raise an `ImportError` naming the extra that provides it.
3. Add the extra to `pyproject.toml`.

`export/writers.py` and `embed/encoder.py` are the reference implementations.

## Changing a quality threshold

Never tune against intuition. Tune against a corpus.

```bash
webcorpus assess corpus.jsonl            # before
# make the change
webcorpus assess corpus.jsonl            # after, compare the histogram
```

A threshold change that moves the keep rate by more than a few points needs the
before and after numbers in the commit message. "Felt too aggressive" is not a
justification; "dropped 38% of a documentation corpus on
terminal_punctuation_ratio, which API reference legitimately fails" is.

**Every rule must keep running after a failure.** If you find yourself adding
an early return to `assess`, stop: the complete failure histogram is the only
tuning signal users have.

## Changing extraction

Extraction failures masquerade as quality failures. A sudden drop in keep rate
is more often extraction returning nav text than thresholds being wrong.

Check the actual output before touching a threshold:

```bash
webcorpus extract suspect_page.html
```

The heading reclaim in `_best_run` exists because Kadane discards headings on
its own: they are short, so they score below the mean and read as a cost. If
you rewrite the scoring, that case needs a test.

## Changing dedup

- **Verification is mandatory.** LSH returns candidates. Any path that uses the
  index must check real signature similarity before declaring a duplicate.
- **Test against true Jaccard, not against "found a duplicate."** A broken
  MinHash still finds duplicates; it just returns wrong similarities. The
  existing test asserts the estimate lands within three standard errors of the
  real value.
- **`bands` must divide `num_perm`.** The constructor enforces it.
- Changing the hash function, the seed, or the shingle size **invalidates every
  stored signature**. Say so in the commit message.

## Changing batching

`adaptive_batches` must never drop a text. A document longer than
`max_batch_tokens` gets its own batch; truncation is the model's concern.

Sorting by length helps when batch size is the binding constraint. When the
token cap binds first, both orderings produce identical batches. Both regimes
are asserted in `tests/test_embed.py`; do not delete the second one because it
looks redundant.

## Before finishing

```bash
pytest && ruff check webcorpus tests && ruff format --check webcorpus tests
```

Report skipped tests and uninstalled linters explicitly. A check that did not
run is not a check that passed.

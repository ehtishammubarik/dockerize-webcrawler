# webcorpus

Crawl-to-dataset pipeline. Extract, filter, deduplicate, embed, shard.

## The one rule that shapes everything else

**The core has zero runtime dependencies.** `webcorpus/` imports stdlib only.

Before adding any import, check it is stdlib. If a stage genuinely needs a third
party package, it goes behind a guarded import inside the function that uses it
and into an optional extra in `pyproject.toml`, following the pattern in
`export/writers.py` and `embed/encoder.py`. CI has a job that fails if the core
acquires a dependency, so this is enforced rather than aspirational.

## Layout

| Path | Holds |
| :--- | :--- |
| `webcorpus/models.py` | `Document`, carried through every stage |
| `webcorpus/clean/` | HTML extraction, Unicode normalization |
| `webcorpus/quality/` | Nine Gopher and C4 heuristics |
| `webcorpus/dedup/` | Exact hashing, MinHash with LSH |
| `webcorpus/embed/` | Adaptive batching, encoder protocol |
| `webcorpus/export/` | Sharded writers, manifests |
| `webcorpus/pipeline.py` | Stage orchestration and stats |
| `webcorpus/cli.py` | `build`, `assess`, `dedup`, `extract` |
| `immo_crawl/` | Original Scrapy crawler, kept as an integration example |

## Before you commit

```bash
pytest                              # 107 tests, must all pass
ruff check webcorpus tests
ruff format --check webcorpus tests
```

## Conventions that are not obvious from the code

1. **Stage order is cost-ordered and load-bearing.** Cheap filters run first so
   expensive ones see less input. Reordering is allowed but must be justified in
   the commit message, because the current order is why the pipeline is fast.

2. **Quality rules never short circuit.** Every rule runs even after one fails.
   The failure histogram is what users tune against; short circuiting saves
   microseconds and destroys the only tuning signal there is.

3. **Rules return `Rule`, not `bool`.** A result carries the observed value and
   the threshold, so a report says *why* and *by how much*.

4. **LSH returns candidates, not answers.** Any code path using the index must
   verify candidates against real signature similarity. Skipping verification
   silently raises the false positive rate.

5. **Never claim a check ran when it did not.** Applies to code and to prose. A
   skipped test, an uninstalled linter, and an untested optional extra all get
   said out loud. The README states its uncovered lines and why.

6. **Docstrings explain why, not what.** The signature already says what.

## Security

Never commit credentials. The database connection reads `CRAWL_DB_PASSWORD`
from the environment and raises when unset, deliberately, because a silent
default is how a password ended up committed here in the first place.

That password is still in git history across four commits. It has been rotated.
Rewriting history to purge it requires the owner's explicit approval and a
force push, and is tracked separately.

## Crawling

This project processes crawled data and can imply crawling. Respect
`robots.txt`, rate limit, identify your bot honestly in the user agent, and
check terms of service before crawling a site you do not own. See
`.claude/skills/crawl-ethics`.

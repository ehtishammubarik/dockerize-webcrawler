# Contributing to websieve

This pipeline fails quietly. Nothing crashes; the corpus just gets worse, and
the cause surfaces later as a model regression nobody can attribute. The rules
below exist because of that, not out of ceremony.

## Before you start

**Open an issue first** for anything beyond a typo or an obvious bug. A
paragraph agreeing on the approach is cheaper than a review of the wrong
implementation. Issues labelled `good first issue` are pre-scoped and safe to
pick up without asking.

## Setup

```bash
git clone https://github.com/ehtishammubarik/websieve
cd websieve
pip install -e ".[dev]"
pytest
```

## The rule that governs everything

**The core has zero runtime dependencies.** `websieve/` imports stdlib only.

If a stage genuinely needs a third-party package:

1. Guard the import inside the function that uses it.
2. Raise `ImportError` naming the extra that provides it.
3. Add the extra to `pyproject.toml`.

See `export/writers.py` and `embed/encoder.py`. CI fails on module-level
third-party imports, so this is enforced rather than hoped for.

## Before you open a PR

```bash
pytest
ruff check websieve tests
ruff format websieve tests
python .github/scripts/check_no_deps.py
```

All four must pass. If a tool is not installed, say so in the PR rather than
implying it passed.

## Rules specific to this codebase

1. **Quality rules never short circuit.** Every rule runs even after one fails.
   The failure histogram is the only tuning signal users have; an early return
   in `assess` destroys it.

2. **Rules return `Rule`, not `bool`.** Carry the observed value and the
   threshold so a report can say why, and by how much.

3. **LSH candidates must be verified.** `query()` returns candidates, not
   answers. Any path treating a candidate as a duplicate without checking real
   similarity raises the false positive rate invisibly.

4. **Changing a default threshold requires evidence.** Put before and after keep
   rates from a real corpus in the PR description. "Felt too aggressive" is not
   evidence; "dropped 38% of a documentation corpus on
   `terminal_punctuation_ratio`, which API reference legitimately fails" is.

5. **Changing a hash function, seed, or shingle size invalidates every stored
   signature.** Say so explicitly in the PR.

6. **Never drop a document silently.** `adaptive_batches` must not lose a text;
   an oversized document gets its own batch. Anything that removes a document
   must increment a counter in `PipelineStats`.

## Tests

Test behaviour, not implementation. A dedup test asserting "found a duplicate"
passes against a broken MinHash that returns nonsense similarities. The existing
test asserts the estimate lands within three standard errors of true Jaccard.
Aim for that standard.

New quality rules need a test with text designed to fail that specific rule, so
a threshold change surfaces as one failing test rather than a vague regression.

## Commit messages

```
<type>(<scope>): <imperative summary, 72 chars or less>

Why this change exists. The diff already shows what.

Refs: #123
```

Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `chore`.

One logical change per commit. If the summary needs "and", split it.

## Security

Never commit credentials. Report vulnerabilities to
[contact@eprecisio.com](mailto:contact@eprecisio.com) rather than in a public
issue.

## Crawling responsibly

If your change touches crawling, respect `robots.txt`, rate limit, and identify
your bot honestly. `.claude/skills/crawl-ethics/SKILL.md` has the details.

`websieve` filters for corpus *quality*, not legal *permissibility*. It does no
PII removal and no licence detection. Do not add documentation implying
otherwise.

## Questions

Open a discussion, or email [contact@eprecisio.com](mailto:contact@eprecisio.com).

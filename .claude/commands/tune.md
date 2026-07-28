---
name: tune
description: Calibrate filtering thresholds against a real corpus instead of intuition.
argument-hint: <corpus.jsonl>
allowed-tools: Bash, Read, Edit
---

# /tune

Thresholds are tuned against a corpus, never against a feeling.

## 1. Measure before changing anything

```bash
websieve assess "$1" -v | tee /tmp/before.txt
```

Read the histogram. One rule dominating usually means it is mistuned for this
corpus, not that the corpus is bad.

## 2. Rule out extraction first

A low keep rate is more often extraction returning nav text than thresholds
being wrong. Quality is correct to reject nav text.

```bash
head -3 "$1" | python -c "
import json, sys
for line in sys.stdin:
    d = json.loads(line)
    print(repr(d.get('text', '')[:300]))
    print('---')
"
```

If that looks like navigation rather than content, fix extraction. Do not
loosen a threshold to compensate; you will keep the nav text.

## 3. Change one thing

Edit a single default in `websieve/quality/heuristics.py` or pass a custom
rule tuple. One variable at a time, or you cannot attribute the difference.

## 4. Measure again

```bash
websieve assess "$1" -v | tee /tmp/after.txt
diff <(grep -E '^\s+\w+\s+[0-9]+$' /tmp/before.txt) \
     <(grep -E '^\s+\w+\s+[0-9]+$' /tmp/after.txt)
```

## 5. Record the evidence

Put the before and after keep rates in the commit message. A default that
changed without numbers behind it will be changed back by the next person, for
equally unexamined reasons.

See `docs/tuning.md` for what the ranges mean and for domain-corpus guidance.

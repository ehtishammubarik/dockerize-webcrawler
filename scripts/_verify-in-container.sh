#!/usr/bin/env bash
# Runs INSIDE a stock python image. Nothing from the repository is present:
# this tests only what `pip install websieve` actually delivers.
# $SPEC is passed through the environment.
set -euo pipefail

# Snapshot before installing. Stock python images ship different preinstalled
# sets (3.11-slim has `packaging`, 3.12-slim does not), so an exclude list is
# wrong. Diffing is the only correct test: anything new besides websieve itself
# is a real runtime dependency.
pip list --format=freeze 2>/dev/null | cut -d= -f1 | sort > /tmp/before.txt

pip install --quiet --no-cache-dir "$SPEC" 2>&1 | grep -viE 'notice|warning|upgrade pip' || true

echo "--- installed version"
python -c 'import importlib.metadata as m; print(m.version("websieve"))'

echo "--- zero runtime dependencies"
pip list --format=freeze 2>/dev/null | cut -d= -f1 | sort > /tmp/after.txt
added=$(comm -13 /tmp/before.txt /tmp/after.txt | grep -vx 'websieve' || true)
if [ -n "$added" ]; then
  echo "FAILED: install pulled in:"; echo "$added"; exit 1
fi
echo "nothing installed except websieve itself"

echo "--- every module imports"
python - <<'PY'
import importlib
mods = ['websieve.models', 'websieve.pipeline', 'websieve.cli',
        'websieve.clean.boilerplate', 'websieve.clean.normalize',
        'websieve.quality.heuristics', 'websieve.dedup.exact',
        'websieve.dedup.minhash', 'websieve.embed.encoder',
        'websieve.export.writers']
for m in mods:
    importlib.import_module(m)
print(f"{len(mods)} modules imported")
PY

echo "--- optional extras fail helpfully rather than crashing"
python - <<'PY'
from websieve.export.writers import ParquetShardWriter
try:
    ParquetShardWriter("/tmp/x")
except ImportError as e:
    assert "pyarrow" in str(e) and "parquet" in str(e), e
    print("ParquetShardWriter raises a helpful ImportError")
else:
    raise SystemExit("expected ImportError without pyarrow installed")
PY

echo "--- cli entry point"
websieve --help > /dev/null && echo "websieve --help ok"

echo "--- end to end pipeline"
python - <<'PY'
import json
body = ("Kubernetes exposes GPUs through the NVIDIA device plugin, which advertises "
        "nvidia.com/gpu as an allocatable resource on every node in the pool. Once "
        "training and inference share the same hardware, fragmentation becomes the "
        "dominant concern for the scheduler. MIG partitioning splits an A100 into as "
        "many as seven independent instances, which suits small inference models far "
        "better than whole-card allocation does.")
docs = [
    {"url": "https://e.com/a",
     "html": f"<html><head><title>GPU scheduling</title></head><body>"
             f"<nav><a href='/'>Home</a><a href='/about'>About</a></nav>"
             f"<article><p>{body}</p></article>"
             f"<footer>Privacy Policy</footer></body></html>"},
    {"url": "https://e.com/b", "text": "Home About Contact Login"},
]
with open("/tmp/crawl.jsonl", "w") as fh:
    for d in docs:
        fh.write(json.dumps(d) + "\n")
PY
websieve build /tmp/crawl.jsonl -o /tmp/ds 2>/dev/null

python - <<'PY'
import gzip, json, pathlib
stats = json.loads(pathlib.Path("/tmp/ds/stats.json").read_text())["stats"]
assert stats["seen"] == 2, stats
assert stats["kept"] == 1, stats
assert stats["dropped_by_stage"]["quality"] == 1, stats

manifest = json.loads(pathlib.Path("/tmp/ds/manifest.json").read_text())
assert manifest["total_records"] == 1, manifest

with gzip.open("/tmp/ds/shard-00000.jsonl.gz", "rt") as fh:
    rec = json.loads(fh.readline())
assert rec["title"] == "GPU scheduling", rec["title"]
for junk in ("Home", "About", "Privacy"):
    assert junk not in rec["text"], f"{junk} survived extraction"
assert rec["quality"]["passed"] is True
assert set(rec["signatures"]) == {"raw", "normalized", "structural"}
print("pipeline output verified:", stats)
PY

echo "--- near-duplicate detection"
python - <<'PY'
from websieve.dedup.minhash import deduplicate
a = "the quick brown fox jumps over the lazy dog beside the river at dawn today"
b = a.replace("dawn", "dusk")
out = list(deduplicate([("1", a), ("2", b)], threshold=0.5, bands=64))
assert out[1][1] is True, out
print(f"near-duplicate detected at similarity {out[1][3]:.3f}")
PY

echo "--- reading shards back via the manifest"
python - <<'PY'
from websieve.export.writers import read_shards
n = len(list(read_shards("/tmp/ds")))
assert n == 1, n
print(f"read_shards returned {n} record")
PY

import gzip
from pathlib import Path

import pytest

from websieve.export.writers import JsonlShardWriter, read_shards


def records(n):
    return [{"doc_id": f"d{i}", "text": f"document {i}"} for i in range(n)]


def test_shards_split_at_the_configured_size(tmp_path):
    with JsonlShardWriter(tmp_path, shard_size=3) as w:
        w.write_all(records(7))
        m = w.close()
    assert m["shard_count"] == 3
    assert [s["records"] for s in m["shards"]] == [3, 3, 1]


def test_manifest_totals_match_records(tmp_path):
    with JsonlShardWriter(tmp_path, shard_size=4) as w:
        w.write_all(records(10))
        m = w.close()
    assert m["total_records"] == 10 == sum(s["records"] for s in m["shards"])


def test_roundtrip_preserves_order_and_content(tmp_path):
    original = records(25)
    with JsonlShardWriter(tmp_path, shard_size=6) as w:
        w.write_all(original)
    assert list(read_shards(tmp_path)) == original


def test_compressed_output_is_gzip(tmp_path):
    with JsonlShardWriter(tmp_path, shard_size=100, compress=True) as w:
        w.write_all(records(3))
    path = next(Path(tmp_path).glob("*.jsonl.gz"))
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        assert len(fh.read().strip().splitlines()) == 3


def test_uncompressed_output_is_plain(tmp_path):
    with JsonlShardWriter(tmp_path, shard_size=100, compress=False) as w:
        w.write_all(records(3))
    assert list(Path(tmp_path).glob("*.jsonl"))
    assert not list(Path(tmp_path).glob("*.gz"))


def test_unicode_survives_roundtrip(tmp_path):
    rec = [{"text": "GPU 调度 · naïve café 🚀"}]
    with JsonlShardWriter(tmp_path) as w:
        w.write_all(rec)
    assert list(read_shards(tmp_path)) == rec


def test_context_manager_flushes_partial_shard_on_exception(tmp_path):
    with pytest.raises(RuntimeError), JsonlShardWriter(tmp_path, shard_size=100) as w:
        w.write_all(records(5))
        raise RuntimeError("boom")
    # Records written before the failure must still be recoverable.
    assert len(list(read_shards(tmp_path))) == 5


def test_empty_writer_produces_valid_empty_manifest(tmp_path):
    with JsonlShardWriter(tmp_path) as w:
        m = w.close()
    assert m["total_records"] == 0 and m["shard_count"] == 0
    assert list(read_shards(tmp_path)) == []


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"no manifest\.json"):
        list(read_shards(tmp_path))


def test_manifest_referencing_missing_shard_raises(tmp_path):
    with JsonlShardWriter(tmp_path, shard_size=2) as w:
        w.write_all(records(4))
    next(Path(tmp_path).glob("*.jsonl.gz")).unlink()
    with pytest.raises(FileNotFoundError, match="but it is missing"):
        list(read_shards(tmp_path))


def test_invalid_shard_size_raises(tmp_path):
    with pytest.raises(ValueError, match="shard_size"):
        JsonlShardWriter(tmp_path, shard_size=0)


def test_nested_output_directory_is_created(tmp_path):
    out = tmp_path / "a" / "b" / "c"
    with JsonlShardWriter(out) as w:
        w.write_all(records(2))
    assert (out / "manifest.json").exists()

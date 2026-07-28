import json
import subprocess
import sys

from websieve.cli import main

PROSE = (
    "Kubernetes schedules GPU workloads through the NVIDIA device plugin. "
    "The plugin advertises nvidia.com/gpu as an allocatable resource on nodes. "
    "Fragmentation becomes the dominant concern once training and inference mix. "
    "MIG partitioning splits an A100 into as many as seven separate instances. "
) * 4


def write_input(tmp_path, docs):
    p = tmp_path / "in.jsonl"
    p.write_text("\n".join(json.dumps(d) for d in docs) + "\n", encoding="utf-8")
    return str(p)


def test_build_writes_dataset_and_stats(tmp_path):
    src = write_input(
        tmp_path,
        [
            {"url": "u1", "text": PROSE},
            {"url": "u2", "text": PROSE},  # exact duplicate
            {"url": "u3", "text": "too short"},  # quality drop
        ],
    )
    out = tmp_path / "ds"
    assert main(["build", src, "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())
    assert stats["stats"]["seen"] == 3
    assert stats["stats"]["kept"] == 1
    assert stats["stats"]["dropped_by_stage"]["exact_duplicate"] == 1
    assert (out / "manifest.json").exists()


def test_build_respects_disabled_stages(tmp_path):
    src = write_input(tmp_path, [{"url": "u1", "text": "tiny"}])
    out = tmp_path / "ds"
    main(["build", src, "-o", str(out), "--no-quality", "--no-dedup"])
    assert json.loads((out / "stats.json").read_text())["stats"]["kept"] == 1


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"url":"u1","text":"' + PROSE + '"}\nNOT JSON\n', encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    assert json.loads((out / "stats.json").read_text())["stats"]["seen"] == 1


def test_assess_command_runs(tmp_path, capsys):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    assert main(["assess", src]) == 0


def test_dedup_command_reports_duplicates(tmp_path, capsys):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}, {"url": "u2", "text": PROSE}])
    assert main(["dedup", src]) == 0
    assert "DUPLICATE_OF" in capsys.readouterr().out


def test_extract_command_json_output(tmp_path, capsys):
    page = tmp_path / "p.html"
    page.write_text(f"<html><head><title>T</title></head><body><p>{PROSE}</p></body></html>")
    assert main(["extract", str(page), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["title"] == "T" and "Kubernetes" in out["text"]


def test_module_is_executable(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "websieve.cli", "--help"], capture_output=True, text=True
    )
    assert r.returncode == 0 and "websieve" in r.stdout


def test_stdin_input(tmp_path):
    out = tmp_path / "ds"
    r = subprocess.run(
        [sys.executable, "-m", "websieve.cli", "build", "-", "-o", str(out)],
        input=json.dumps({"url": "u1", "text": PROSE}) + "\n",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert json.loads((out / "stats.json").read_text())["stats"]["kept"] == 1

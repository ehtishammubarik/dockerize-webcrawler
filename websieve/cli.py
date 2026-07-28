"""Command line interface.

    websieve build   input.jsonl -o dataset/     full pipeline to sharded output
    websieve assess  input.jsonl                 quality report, drops nothing
    websieve dedup   input.jsonl                 duplicate clusters only
    websieve extract page.html                   HTML to text, one file

Input is JSONL with at minimum a ``url`` field and one of ``text`` or ``html``.
Reads stdin when the path is ``-``, so it composes with a crawler:

    scrapy crawl spider -o - -t jsonlines | websieve build - -o dataset/
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from .clean.boilerplate import extract
from .dedup.minhash import deduplicate
from .export.writers import JsonlShardWriter
from .models import Document
from .pipeline import Pipeline, PipelineConfig, prepare
from .quality.heuristics import assess


def _open_input(path: str) -> TextIO:
    return sys.stdin if path == "-" else open(path, encoding="utf-8")


def _read_docs(path: str) -> Iterator[Document]:
    fh = _open_input(path)
    try:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield Document.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                print(f"warning: skipping line {lineno}: {exc}", file=sys.stderr)
    finally:
        if fh is not sys.stdin:
            fh.close()


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def _sample_docs(docs: Iterator[Document], n: int) -> list[Document]:
    sample: list[Document] = []
    for seen, doc in enumerate(docs, 1):
        if len(sample) < n:
            sample.append(doc)
            continue
        idx = random.randrange(seen)
        if idx < n:
            sample[idx] = doc
    return sample


# ---------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    config = PipelineConfig(
        exact_level=args.exact_level,
        near_dup_threshold=args.threshold,
        num_perm=args.num_perm,
        bands=args.bands,
        run_quality=not args.no_quality,
        run_near_dedup=not args.no_dedup,
    )
    pipeline = Pipeline(config)

    with JsonlShardWriter(
        args.output, shard_size=args.shard_size, compress=not args.no_compress
    ) as writer:
        for doc in pipeline.process(_read_docs(args.input)):
            writer.write(doc.to_dict())
        manifest = writer.close()

    stats = pipeline.stats
    report = {"stats": stats.to_dict(), "manifest": manifest}
    (Path(args.output) / "stats.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print(stats.render(), file=sys.stderr)
    print(
        f"\nwrote {manifest['total_records']} records "
        f"in {manifest['shard_count']} shard(s) to {args.output}",
        file=sys.stderr,
    )
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    total = 0
    passed = 0
    failures: dict[str, int] = {}
    docs: Iterator[Document] | list[Document] = _read_docs(args.input)
    sampled = args.sample is not None

    if sampled:
        docs = _sample_docs(docs, args.sample)

    for doc in docs:
        total += 1
        # Must extract and normalize first: assessing raw doc.text reports that
        # every HTML-only document fails, and contradicts what build does.
        report = assess(prepare(doc).text)
        if report.passed:
            passed += 1
        for name in report.failures:
            failures[name] = failures.get(name, 0) + 1
        if args.verbose and not report.passed:
            print(f"{doc.url}\t{','.join(report.failures)}")

    sample_note = "  (sampled from stream)" if sampled else ""
    print(f"documents   {total}{sample_note}", file=sys.stderr)
    print(
        f"would pass  {passed}  ({passed / total:.1%})" if total else "would pass  0",
        file=sys.stderr,
    )
    if failures:
        print("rule failures:", file=sys.stderr)
        for name, n in sorted(failures.items(), key=lambda kv: -kv[1]):
            print(f"  {name:28} {n}", file=sys.stderr)
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    pairs = [(d.url, prepare(d).text) for d in _read_docs(args.input)]
    dupes = 0
    for key, is_dup, matched, sim in deduplicate(
        pairs, threshold=args.threshold, num_perm=args.num_perm, bands=args.bands
    ):
        if is_dup:
            dupes += 1
            print(f"{key}\tDUPLICATE_OF\t{matched}\t{sim:.4f}")
        elif args.verbose:
            print(f"{key}\tUNIQUE")
    print(
        f"\n{len(pairs)} documents, {dupes} near-duplicates at threshold {args.threshold}",
        file=sys.stderr,
    )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    html = (
        sys.stdin.read()
        if args.input == "-"
        else Path(args.input).read_text(encoding="utf-8", errors="replace")
    )
    text, title = extract(html, min_block_chars=args.min_block_chars)
    if args.json:
        print(json.dumps({"title": title, "text": text}, ensure_ascii=False))
    else:
        if title:
            print(f"# {title}\n")
        print(text)
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="websieve",
        description="Turn a web crawl into an ML-ready dataset.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_dedup_opts(sp):
        sp.add_argument(
            "--threshold",
            type=float,
            default=0.80,
            help="Jaccard similarity above which documents are duplicates",
        )
        sp.add_argument(
            "--num-perm",
            type=int,
            default=128,
            help="MinHash permutations; higher is more accurate and slower",
        )
        sp.add_argument("--bands", type=int, default=32, help="LSH bands; must divide --num-perm")

    b = sub.add_parser("build", help="run the full pipeline to a sharded dataset")
    b.add_argument("input", help="JSONL file, or - for stdin")
    b.add_argument("-o", "--output", required=True, help="output directory")
    b.add_argument("--shard-size", type=int, default=10_000)
    b.add_argument(
        "--exact-level", default="normalized", choices=["raw", "normalized", "structural"]
    )
    b.add_argument("--no-quality", action="store_true", help="skip quality filtering")
    b.add_argument("--no-dedup", action="store_true", help="skip near-duplicate removal")
    b.add_argument("--no-compress", action="store_true", help="write plain JSONL")
    add_dedup_opts(b)
    b.set_defaults(func=cmd_build)

    a = sub.add_parser("assess", help="quality report without dropping anything")
    a.add_argument("input", help="JSONL file, or - for stdin")
    a.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print each failing document and its failed rules",
    )
    a.add_argument(
        "--sample",
        type=_positive_int,
        metavar="N",
        help="assess a reservoir sample of N documents after reading the full stream",
    )
    a.set_defaults(func=cmd_assess)

    d = sub.add_parser("dedup", help="report near-duplicate clusters")
    d.add_argument("input", help="JSONL file, or - for stdin")
    d.add_argument("-v", "--verbose", action="store_true")
    add_dedup_opts(d)
    d.set_defaults(func=cmd_dedup)

    e = sub.add_parser("extract", help="HTML to main-content text")
    e.add_argument("input", help="HTML file, or - for stdin")
    e.add_argument("--min-block-chars", type=int, default=25)
    e.add_argument("--json", action="store_true", help="emit JSON instead of text")
    e.set_defaults(func=cmd_extract)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # pragma: no cover - shell behaviour
        return 0
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

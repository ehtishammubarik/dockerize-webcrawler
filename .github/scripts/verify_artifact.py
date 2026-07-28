#!/usr/bin/env python3
"""Verify a built distribution before it is allowed anywhere near PyPI.

Checks the *artifact*, not the source tree. The test suite imports from the
checkout, so it cannot see a packaging defect: a module missing from the wheel,
a file absent from the sdist, an entry point that only resolves in an editable
install. Every one of those ships a green repository and a broken package.

Usage:
    python .github/scripts/verify_artifact.py dist/

Exit codes: 0 all checks passed, 1 at least one failed.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

# Files that must never be inside a published wheel.
FORBIDDEN_PATTERNS = [
    re.compile(r"(^|/)tests?/"),
    re.compile(r"\.pyc$"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)\.env"),
    re.compile(r"\.(pem|key|p12|pfx)$"),
    re.compile(r"(^|/)\.git"),
    re.compile(r"(^|/)(id_rsa|credentials)$"),
    re.compile(r"\.(tfstate|db|sqlite3?)$"),
]

# Credential-shaped strings that must not appear in any packaged source file.
SECRET_PATTERNS = [
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"pypi-[A-Za-z0-9_-]{40,}"),
]

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def check_wheel(wheel: Path) -> None:
    print(f"\n{wheel.name}")
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()

        # 1. Nothing forbidden is packaged.
        bad = [n for n in names for p in FORBIDDEN_PATTERNS if p.search(n)]
        if bad:
            fail(f"forbidden files in wheel: {sorted(set(bad))[:5]}")
        else:
            ok(f"no forbidden files ({len(names)} entries)")

        # 2. No credential-shaped strings in packaged sources.
        hits = []
        for n in names:
            if not n.endswith((".py", ".txt", ".cfg", ".toml", ".json", ".yml", ".yaml")):
                continue
            blob = zf.read(n)
            for p in SECRET_PATTERNS:
                if p.search(blob):
                    hits.append(f"{n}:{p.pattern.decode(errors='replace')[:30]}")
        if hits:
            fail(f"credential-shaped strings in wheel: {hits[:3]}")
        else:
            ok("no credential-shaped strings")

        # 3. Zero runtime dependencies, read from wheel METADATA rather than
        #    from pyproject. Extras carry an environment marker; a bare
        #    Requires-Dist without one is a real runtime dependency.
        meta = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
        if not meta:
            fail("wheel has no METADATA")
            return
        text = zf.read(meta).decode("utf-8", "replace")
        runtime = [
            ln.split(":", 1)[1].strip()
            for ln in text.splitlines()
            if ln.startswith("Requires-Dist:") and "extra ==" not in ln
        ]
        if runtime:
            fail(f"wheel declares runtime dependencies: {runtime}")
        else:
            extras = sum(1 for ln in text.splitlines()
                         if ln.startswith("Requires-Dist:") and "extra ==" in ln)
            ok(f"zero runtime dependencies ({extras} behind extras)")

        # 4. Every module in the source tree is actually in the wheel.
        #
        # Comparing against the source tree rather than against a hardcoded
        # list: a misconfigured packages.find silently drops subpackages, and
        # an expected-set that is written by hand goes stale the first time
        # someone adds a module. An earlier version of this check merely
        # printed the subpackages it found and passed regardless, which let a
        # wheel containing none of them through.
        src_root = Path(__file__).resolve().parents[2] / "websieve"
        if not src_root.is_dir():
            notes.append(f"source tree not found at {src_root}, skipped completeness check")
        else:
            expected = {
                str(p.relative_to(src_root.parent)).replace("\\", "/")
                for p in src_root.rglob("*.py")
                if "__pycache__" not in p.parts
            }
            packaged = {n for n in names if n.startswith("websieve/") and n.endswith(".py")}
            missing = sorted(expected - packaged)
            if missing:
                fail(f"{len(missing)} module(s) in the source tree are absent "
                     f"from the wheel: {missing[:5]}")
            else:
                ok(f"all {len(expected)} source modules present in wheel")


def check_sdist(sdist: Path) -> None:
    import tarfile

    print(f"\n{sdist.name}")
    with tarfile.open(sdist) as tf:
        names = tf.getnames()
    bad = [n for n in names for p in FORBIDDEN_PATTERNS
           if p.search(n) and not p.pattern.startswith("(^|/)tests?")]
    if bad:
        fail(f"forbidden files in sdist: {sorted(set(bad))[:5]}")
    else:
        ok(f"no forbidden files ({len(names)} entries)")

    # An sdist must be rebuildable, so it needs the build inputs.
    required = ["pyproject.toml", "README.md", "LICENSE"]
    missing = [r for r in required if not any(n.endswith("/" + r) for n in names)]
    if missing:
        fail(f"sdist missing build inputs: {missing}")
    else:
        ok("sdist carries pyproject, README, LICENSE")


def main(argv: list[str]) -> int:
    dist = Path(argv[1] if len(argv) > 1 else "dist")
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))

    if not wheels:
        print(f"no wheel found in {dist}")
        return 1
    if not sdists:
        print(f"no sdist found in {dist}")
        return 1

    print(f"verifying {len(wheels)} wheel(s) and {len(sdists)} sdist(s) in {dist}/")
    for w in wheels:
        check_wheel(w)
    for s in sdists:
        check_sdist(s)

    print()
    if failures:
        print(f"ARTIFACT VERIFICATION FAILED: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("artifact verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

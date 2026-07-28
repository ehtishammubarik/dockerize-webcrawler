---
name: check
description: Run the full local gate: tests, lint, format, and the zero-dependency guard.
allowed-tools: Bash, Read
---

# /check

Everything CI will run, locally, before you push.

```bash
pytest
ruff check websieve tests
ruff format --check websieve tests
```

## Zero-dependency guard

The core must import stdlib only **at module level**. Imports inside a function
body are the sanctioned escape hatch for optional extras, so the guard
distinguishes the two rather than failing on both.

```bash
python3 - <<'PY'
import ast, pathlib, sys

stdlib = sys.stdlib_module_names
violations, guarded = [], []

for path in sorted(pathlib.Path("websieve").rglob("*.py")):
    tree = ast.parse(path.read_text())
    # Module-level imports are direct children of the module body.
    toplevel = {id(n) for n in ast.walk(tree)
                if isinstance(n, ast.Module)
                for stmt in n.body for n in [stmt]}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module.split(".")[0]]
        else:
            continue
        for mod in mods:
            if mod in stdlib or mod == "websieve":
                continue
            entry = f"{path}:{node.lineno} {mod}"
            (violations if id(node) in toplevel else guarded).append(entry)

if guarded:
    print("optional extras, imported lazily (expected):")
    for g in guarded:
        print(f"  {g}")
if violations:
    print("VIOLATIONS: third-party imports at module level in the core:")
    for v in violations:
        print(f"  {v}")
    sys.exit(1)
print("OK: core has no module-level third-party imports")
PY
```

Each lazily imported name must sit inside a `try/except ImportError` that names
the extra providing it, as in `export/writers.py`. The guard proves it is not
at module level; it cannot prove the error message is helpful. Read it.

## Reporting

State what ran and what did not. If `ruff` is not installed, that is a skipped
check, not a passed one. Never summarize a run containing skips as "all checks
passed".

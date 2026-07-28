import ast, pathlib, sys

stdlib = sys.stdlib_module_names
violations, guarded = [], []

for path in sorted(pathlib.Path("webcorpus").rglob("*.py")):
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
            if mod in stdlib or mod == "webcorpus":
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

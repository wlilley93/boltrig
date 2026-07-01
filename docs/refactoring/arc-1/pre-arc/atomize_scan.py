"""Preflight atomization scanner (substitutes vibeclean - broken install).

Computes the structural-floor metrics per function via the stdlib AST + McCabe:
function length (lines), cyclomatic complexity, max nesting depth, param count.
Plus file-level LOC. Output JSON feeds arc-1/inventory + the Tier dispatch.
Floor (defaults): file<=400, func<=80, cc<=15, nesting<=4, params<=5.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

MAX_FILE = 400
MAX_FUNC = 80
MAX_CC = 15
MAX_NEST = 4
MAX_PARAMS = 5


def cc(node: ast.AST) -> int:
    """McCabe cyclomatic complexity (decision points + 1)."""
    v = 1
    for n in ast.walk(node):
        if isinstance(n, ast.BoolOp):
            v += max(0, len(n.values) - 1)  # a AND/OR chain: n-1 implicit branches
        elif isinstance(n, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While,
                            ast.ExceptHandler, ast.With, ast.AsyncWith, ast.Assert)):
            v += 1
    return v


def nesting(node: ast.AST, defs: dict) -> int:
    """Max nesting depth of control-flow inside a function body."""
    ctrl = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
            ast.Try, ast.ExceptHandler, ast.IfExp)
    best = 0

    def walk(n, depth):
        nonlocal best
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ctrl):
                best = max(best, depth + 1)
                walk(child, depth + 1)
            else:
                walk(child, depth)
    walk(node, 0)
    return best


def scan_file(p: Path) -> list[dict]:
    try:
        tree = ast.parse(p.read_text())
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            out.append({
                "file": str(p), "name": node.name, "line": node.lineno,
                "length": length, "cc": cc(node), "nesting": nesting(node, {}),
                "params": len(node.args.args) + len(node.args.kwonlyargs),
            })
    return out


def main(root: str) -> None:
    files = sorted(Path(root).rglob("*.py"))
    files = [f for f in files if "__pycache__" not in f.parts]
    funcs = []
    file_loc = []
    for f in files:
        loc = sum(1 for _ in f.open())
        file_loc.append({"file": str(f), "loc": loc, "over": loc > MAX_FILE})
        funcs.extend(scan_file(f))
    violations = [
        x for x in funcs if x["length"] > MAX_FUNC or x["cc"] > MAX_CC
        or x["nesting"] > MAX_NEST or x["params"] > MAX_PARAMS
    ]
    violations.sort(key=lambda x: (
        (x["length"] > MAX_FUNC) + (x["cc"] > MAX_CC) + (x["nesting"] > MAX_NEST)
        + (x["params"] > MAX_PARAMS), x["length"]), reverse=True)
    print(json.dumps({
        "floor": {"file": MAX_FILE, "func": MAX_FUNC, "cc": MAX_CC,
                  "nesting": MAX_NEST, "params": MAX_PARAMS},
        "files": len(files), "functions": len(funcs),
        "over_floor_files": [f["file"] for f in file_loc if f["over"]],
        "over_floor_funcs": len(violations),
        "violations": violations,
    }, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "boltrig")

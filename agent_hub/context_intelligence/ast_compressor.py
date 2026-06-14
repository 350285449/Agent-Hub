from __future__ import annotations

import ast


def compress_python_ast(source: str, *, include_docstrings: bool = False) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "\n".join(source.splitlines()[:80])
    lines: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(_name(base) for base in node.bases)
            lines.append(f"class {node.name}({bases}):" if bases else f"class {node.name}:")
            if include_docstrings and ast.get_docstring(node):
                lines.append(f"    {ast.get_docstring(node)!r}")
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(f"    {child.name}{_args(child)}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append(f"{node.name}{_args(node)}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.append(ast.unparse(node) if hasattr(ast, "unparse") else "import ...")
    return "\n".join(lines)


def _args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return "(" + ", ".join(arg.arg for arg in node.args.args) + ")"


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "Base"

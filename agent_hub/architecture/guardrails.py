from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class FileSizeFinding:
    path: str
    lines: int
    limit: int
    severity: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "lines": self.lines,
            "limit": self.limit,
            "severity": self.severity,
        }


@dataclass(slots=True)
class FunctionSizeFinding:
    path: str
    function: str
    lines: int
    limit: int
    severity: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "function": self.function,
            "lines": self.lines,
            "limit": self.limit,
            "severity": self.severity,
        }


@dataclass(slots=True)
class ImportCycleFinding:
    modules: list[str]
    severity: str

    def to_dict(self) -> dict[str, object]:
        return {"modules": list(self.modules), "severity": self.severity}


@dataclass(slots=True)
class LayerViolationFinding:
    source: str
    source_layer: str
    target: str
    target_layer: str
    severity: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_layer": self.source_layer,
            "target": self.target,
            "target_layer": self.target_layer,
            "severity": self.severity,
        }


@dataclass(slots=True)
class ApiStabilityFinding:
    module: str
    name: str
    severity: str

    def to_dict(self) -> dict[str, object]:
        return {"module": self.module, "name": self.name, "severity": self.severity}


@dataclass(slots=True)
class ArchitectureGuardrailReport:
    object: str
    max_file_lines: int
    max_function_lines: int
    enforce: bool
    findings: list[FileSizeFinding]
    function_findings: list[FunctionSizeFinding]
    import_cycle_findings: list[ImportCycleFinding]
    layer_violation_findings: list[LayerViolationFinding]
    api_stability_findings: list[ApiStabilityFinding]
    checked_files: int

    @property
    def ok(self) -> bool:
        return not self.enforce or not self.all_findings

    @property
    def all_findings(
        self,
    ) -> list[
        FileSizeFinding
        | FunctionSizeFinding
        | ImportCycleFinding
        | LayerViolationFinding
        | ApiStabilityFinding
    ]:
        return [
            *self.findings,
            *self.function_findings,
            *self.import_cycle_findings,
            *self.layer_violation_findings,
            *self.api_stability_findings,
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "object": self.object,
            "ok": self.ok,
            "max_file_lines": self.max_file_lines,
            "max_function_lines": self.max_function_lines,
            "enforce": self.enforce,
            "checked_files": self.checked_files,
            "findings": [finding.to_dict() for finding in self.findings],
            "function_findings": [finding.to_dict() for finding in self.function_findings],
            "import_cycle_findings": [
                finding.to_dict() for finding in self.import_cycle_findings
            ],
            "layer_violation_findings": [
                finding.to_dict() for finding in self.layer_violation_findings
            ],
            "api_stability_findings": [
                finding.to_dict() for finding in self.api_stability_findings
            ],
        }


DEFAULT_PUBLIC_API: dict[str, tuple[str, ...]] = {
    "agent_hub.providers.base": (
        "ProviderAdapter",
        "ChatRequest",
        "ChatResponse",
        "StreamChunk",
    ),
    "agent_hub.providers.sdk": (
        "ProviderAdapter",
        "ProviderDescriptor",
        "ProviderCapabilities",
        "provider_conformance_report",
    ),
}

LAYER_ORDER = {
    "api": 0,
    "application": 1,
    "services": 2,
    "core": 3,
    "adapters": 4,
}


def architecture_guardrail_report(
    root: str | Path,
    *,
    max_file_lines: int = 1200,
    max_function_lines: int = 120,
    enforce: bool = False,
    public_api: dict[str, Iterable[str]] | None = None,
) -> ArchitectureGuardrailReport:
    base = Path(root)
    findings: list[FileSizeFinding] = []
    function_findings: list[FunctionSizeFinding] = []
    checked = 0
    module_paths = _module_paths(base)
    severity = "error" if enforce else "advisory"
    for module, path in sorted(module_paths.items()):
        if "__pycache__" in path.parts:
            continue
        checked += 1
        lines = _line_count(path)
        if lines > max_file_lines:
            findings.append(
                FileSizeFinding(
                    path=path.relative_to(base).as_posix(),
                    lines=lines,
                    limit=max_file_lines,
                    severity=severity,
                )
            )
        function_findings.extend(
            _function_size_findings(
                path,
                base=base,
                max_function_lines=max_function_lines,
                severity=severity,
            )
        )
    graph = _internal_import_graph(module_paths)
    return ArchitectureGuardrailReport(
        object="agent_hub.architecture_guardrails",
        max_file_lines=max_file_lines,
        max_function_lines=max_function_lines,
        enforce=enforce,
        findings=findings,
        function_findings=function_findings,
        import_cycle_findings=[
            ImportCycleFinding(modules=component, severity=severity)
            for component in _strongly_connected_components(graph)
            if len(component) > 1
        ],
        layer_violation_findings=_layer_violation_findings(graph, severity=severity),
        api_stability_findings=_api_stability_findings(
            module_paths,
            public_api or DEFAULT_PUBLIC_API,
            severity=severity,
        ),
        checked_files=checked,
    )


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _function_size_findings(
    path: Path,
    *,
    base: Path,
    max_function_lines: int,
    severity: str,
) -> list[FunctionSizeFinding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    findings: list[FunctionSizeFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        lines = int(end) - int(node.lineno) + 1
        if lines > max_function_lines:
            findings.append(
                FunctionSizeFinding(
                    path=path.relative_to(base).as_posix(),
                    function=node.name,
                    lines=lines,
                    limit=max_function_lines,
                    severity=severity,
                )
            )
    return findings


def _module_paths(base: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    package = base / "agent_hub"
    if not package.exists():
        return paths
    for path in package.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(base).with_suffix("")
        paths[".".join(relative.parts)] = path
    return paths


def _internal_import_graph(module_paths: dict[str, Path]) -> dict[str, set[str]]:
    packages = {
        module.removesuffix(".__init__")
        for module in module_paths
        if module.endswith(".__init__")
    }
    graph: dict[str, set[str]] = {module: set() for module in module_paths}
    for module, path in module_paths.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            for raw_target in _import_targets(module, node):
                if not raw_target.startswith("agent_hub"):
                    continue
                target = _resolve_known_module(raw_target, module_paths, packages)
                if target is not None and target != module:
                    graph[module].add(target)
    return graph


def _import_targets(module: str, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [_resolve_import_from(module, node.level, node.module)]
    return []


def _resolve_import_from(module: str, level: int, imported: str | None) -> str:
    if level == 0:
        return imported or ""
    package_parts = module.split(".")[:-1]
    base = package_parts[: len(package_parts) - level + 1]
    if imported:
        return ".".join(base + imported.split("."))
    return ".".join(base)


def _resolve_known_module(
    target: str,
    modules: dict[str, Path],
    packages: set[str],
) -> str | None:
    if target in modules:
        return target
    if target in packages:
        return f"{target}.__init__"
    parts = target.split(".")
    while len(parts) > 1:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        if candidate in packages:
            return f"{candidate}.__init__"
    return None


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in graph.get(node, set()):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return components


def _layer_violation_findings(
    graph: dict[str, set[str]],
    *,
    severity: str,
) -> list[LayerViolationFinding]:
    findings: list[LayerViolationFinding] = []
    for source, targets in sorted(graph.items()):
        source_layer = _module_layer(source)
        if source_layer is None:
            continue
        for target in sorted(targets):
            target_layer = _module_layer(target)
            if target_layer is None:
                continue
            if LAYER_ORDER[target_layer] < LAYER_ORDER[source_layer]:
                findings.append(
                    LayerViolationFinding(
                        source=source,
                        source_layer=source_layer,
                        target=target,
                        target_layer=target_layer,
                        severity=severity,
                    )
                )
    return findings


def _module_layer(module: str) -> str | None:
    if module.startswith(("agent_hub.api.", "agent_hub.server_routes.")) or module == "agent_hub.server":
        return "api"
    if module.startswith("agent_hub.application."):
        return "application"
    if module.startswith(("agent_hub.workflows.", "agent_hub.orchestration.", "agent_hub.memory.")):
        return "services"
    if module.startswith(("agent_hub.core.", "agent_hub.models", "agent_hub.payloads")):
        return "core"
    if module.startswith(
        (
            "agent_hub.providers.",
            "agent_hub.tools.",
            "agent_hub.plugins.",
            "agent_hub.security.",
            "agent_hub.sdk.",
        )
    ):
        return "adapters"
    return None


def _api_stability_findings(
    module_paths: dict[str, Path],
    public_api: dict[str, Iterable[str]],
    *,
    severity: str,
) -> list[ApiStabilityFinding]:
    findings: list[ApiStabilityFinding] = []
    exports_by_module = {
        module: _module_exports(path)
        for module, path in module_paths.items()
        if module in public_api
    }
    for module, names in sorted(public_api.items()):
        exports = exports_by_module.get(module)
        if exports is None:
            findings.append(ApiStabilityFinding(module=module, name="*", severity=severity))
            continue
        for name in sorted(set(names)):
            if name not in exports:
                findings.append(ApiStabilityFinding(module=module, name=name, severity=severity))
    return findings


def _module_exports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    exports: set[str] = set()
    explicit_all = _literal_all(tree)
    if explicit_all is not None:
        return explicit_all
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            exports.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    exports.add(target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                if not name.startswith("_"):
                    exports.add(name)
    return exports


def _literal_all(tree: ast.Module) -> set[str] | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            return None
        if isinstance(value, (list, tuple, set)):
            return {item for item in value if isinstance(item, str)}
    return None

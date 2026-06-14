from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RepoDNAProfile:
    language: str = "unknown"
    framework: str = "unknown"
    test_framework: str = "unknown"
    package_manager: str = "unknown"
    architecture_pattern: str = "unknown"
    naming_style: str = "unknown"
    lint_tools: list[str] = field(default_factory=list)
    formatting_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    important_files: list[str] = field(default_factory=list)
    risky_files: list[str] = field(default_factory=list)
    architecture_fingerprint: list[str] = field(default_factory=list)
    coding_style_fingerprint: list[str] = field(default_factory=list)
    symbol_graph: dict[str, list[str]] = field(default_factory=dict)
    import_graph: dict[str, list[str]] = field(default_factory=dict)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "object": "agent_hub.repo_dna.profile",
            "language": self.language,
            "framework": self.framework,
            "test_framework": self.test_framework,
            "package_manager": self.package_manager,
            "architecture_pattern": self.architecture_pattern,
            "naming_style": self.naming_style,
            "lint_tools": list(self.lint_tools),
            "formatting_tools": list(self.formatting_tools),
            "dependencies": list(self.dependencies),
            "important_files": list(self.important_files),
            "risky_files": list(self.risky_files),
            "architecture_fingerprint": list(self.architecture_fingerprint),
            "coding_style_fingerprint": list(self.coding_style_fingerprint),
            "symbol_graph": {key: list(value) for key, value in self.symbol_graph.items()},
            "import_graph": {key: list(value) for key, value in self.import_graph.items()},
            "dependency_graph": {key: list(value) for key, value in self.dependency_graph.items()},
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        parts = [
            self.framework if self.framework != "unknown" else self.language,
            *self.architecture_fingerprint[:2],
            self.test_framework if self.test_framework != "unknown" else "",
            *self.coding_style_fingerprint[:1],
        ]
        return " + ".join(part for part in parts if part)

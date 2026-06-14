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
        }

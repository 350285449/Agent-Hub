from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
class ArchitectureGuardrailReport:
    object: str
    max_file_lines: int
    enforce: bool
    findings: list[FileSizeFinding]
    checked_files: int

    @property
    def ok(self) -> bool:
        return not self.enforce or not self.findings

    def to_dict(self) -> dict[str, object]:
        return {
            "object": self.object,
            "ok": self.ok,
            "max_file_lines": self.max_file_lines,
            "enforce": self.enforce,
            "checked_files": self.checked_files,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def architecture_guardrail_report(
    root: str | Path,
    *,
    max_file_lines: int = 1200,
    enforce: bool = False,
) -> ArchitectureGuardrailReport:
    base = Path(root)
    findings: list[FileSizeFinding] = []
    checked = 0
    for path in sorted((base / "agent_hub").rglob("*.py")):
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
                    severity="error" if enforce else "advisory",
                )
            )
    return ArchitectureGuardrailReport(
        object="agent_hub.architecture_guardrails",
        max_file_lines=max_file_lines,
        enforce=enforce,
        findings=findings,
        checked_files=checked,
    )


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "secret_assignment",
        re.compile(
            r"(?im)\b(?:api[_-]?key|token|secret|password|passwd|credential)\b\s*[:=]\s*['\"]?[^'\"\s]{8,}"
        ),
    ),
)

CONFIG_FILENAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "agent-hub.config.json",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "tsconfig.json",
}


@dataclass(slots=True)
class SecretFinding:
    kind: str
    preview: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"kind": self.kind, "preview": self.preview}
        if self.line is not None:
            data["line"] = self.line
        return data


@dataclass(slots=True)
class RiskAssessment:
    category: str
    risk_level: str = "low"
    reason: str = ""
    blocked: bool = False
    explicit_approval_required: bool = False
    findings: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "blocked": self.blocked,
            "explicit_approval_required": self.explicit_approval_required,
            "findings": self.findings,
            "metadata": self.metadata,
        }


def detect_secrets(text: str, *, limit: int = 12) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    if not text:
        return findings
    line_starts = _line_starts(text)
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                SecretFinding(
                    kind=kind,
                    preview=_redacted_preview(match.group(0)),
                    line=_line_for_offset(line_starts, match.start()),
                )
            )
            if len(findings) >= limit:
                return findings
    return findings


def classify_tool_action(tool_name: str, args: dict[str, Any]) -> RiskAssessment:
    if tool_name == "run_command":
        return classify_shell_command(str(args.get("command") or ""))
    if tool_name in {"write_file", "replace_in_file", "apply_patch"}:
        return classify_file_mutation(tool_name, args)
    return RiskAssessment(category="read", risk_level="low")


def classify_shell_command(command: str) -> RiskAssessment:
    text = f" {command.strip()} "
    normalized = _normalize_command(text)
    findings: list[dict[str, Any]] = []
    category = "shell_command"
    risk = "medium"
    reason = "Shell command execution can inspect or modify the workspace."
    blocked = False
    explicit = False

    critical_patterns = (
        r"\brm\s+-[^\n;&|]*r[^\n;&|]*f\b",
        r"\bremove-item\b[^\n;&|]*\b-recurse\b[^\n;&|]*\b-force\b",
        r"\brd\s+/s\s+/q\b",
        r"\brmdir\s+/s\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-[^\n;&|]*[xfd][^\n;&|]*\b",
        r"\bsudo\b",
        r"\brunas\b",
        r"\bstart-process\b[^\n;&|]*\b-verb\s+runas\b",
        r"\bset-executionpolicy\b",
        r"\bshutdown\b",
        r"\breboot\b",
    )
    if _matches_any(normalized, critical_patterns):
        return RiskAssessment(
            category="shell_command",
            risk_level="critical",
            reason="Command matches an explicitly blocked destructive or admin pattern.",
            blocked=True,
            explicit_approval_required=True,
            findings=[{"kind": "blocked_command", "command": command[:240]}],
        )

    package_patterns = (
        r"\bnpm\s+(?:i|install)\b",
        r"\bpnpm\s+(?:i|install|add)\b",
        r"\byarn\s+(?:install|add)\b",
        r"\bpip(?:3)?\s+install\b",
        r"\bpython(?:3)?\s+-m\s+pip\s+install\b",
        r"\bpoetry\s+(?:add|install)\b",
        r"\buv\s+(?:add|pip\s+install)\b",
        r"\bcargo\s+install\b",
        r"\bgo\s+install\b",
        r"\bapt(?:-get)?\s+install\b",
        r"\bbrew\s+install\b",
        r"\bchoco\s+install\b",
        r"\bwinget\s+install\b",
    )
    if _matches_any(normalized, package_patterns):
        category = "package_install"
        risk = "high"
        reason = "Package manager execution can run install scripts or change the environment."
        explicit = True
        findings.append({"kind": "package_manager", "command": command[:240]})

    download_patterns = (
        r"\bcurl\b",
        r"\bwget\b",
        r"\binvoke-webrequest\b",
        r"\biwr\b",
        r"\binvoke-restmethod\b",
        r"\birm\b",
        r"\bscp\b",
        r"\brsync\b",
    )
    if _matches_any(normalized, download_patterns):
        category = "external_download"
        risk = _max_risk(risk, "high")
        reason = "Command can download or transfer external content."
        explicit = True
        findings.append({"kind": "network_transfer", "command": command[:240]})

    pipe_to_shell_patterns = (
        r"\|\s*(?:sh|bash|zsh|pwsh|powershell|iex|invoke-expression)\b",
        r"\b(?:iwr|irm|curl|wget)\b[^\n]*\|\s*(?:iex|invoke-expression|sh|bash|pwsh|powershell)\b",
    )
    if _matches_any(normalized, pipe_to_shell_patterns):
        return RiskAssessment(
            category="external_download",
            risk_level="critical",
            reason="Command downloads content and pipes it into an interpreter.",
            blocked=True,
            explicit_approval_required=True,
            findings=[{"kind": "install_script", "command": command[:240]}],
        )

    upload_patterns = (
        r"\bgit\s+push\b",
        r"\baws\s+s3\s+(?:cp|sync)\b",
        r"\bgsutil\s+(?:cp|rsync)\b",
        r"\baz\s+storage\b",
        r"\bgcloud\b",
        r"\bdocker\s+push\b",
    )
    if _matches_any(normalized, upload_patterns):
        category = "workspace_upload"
        risk = _max_risk(risk, "high")
        reason = "Command can upload workspace content or credentials to a remote service."
        explicit = True
        findings.append({"kind": "external_upload", "command": command[:240]})

    mutating_patterns = (
        r"\bdel\b",
        r"\berase\b",
        r"\bcopy\b",
        r"\bcp\b",
        r"\bmove\b",
        r"\bmv\b",
        r"\bmkdir\b",
        r"\bnew-item\b",
        r"\bset-content\b",
        r"\badd-content\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bkill\b",
        r"\bpkill\b",
        r"\btaskkill\b",
        r">\s*\S",
        r">>\s*\S",
    )
    if _matches_any(normalized, mutating_patterns):
        risk = _max_risk(risk, "high")
        reason = "Command appears to modify files, permissions, or processes."
        explicit = True
        findings.append({"kind": "mutating_shell", "command": command[:240]})

    secret_findings = [finding.to_dict() for finding in detect_secrets(command)]
    if secret_findings:
        risk = _max_risk(risk, "high")
        explicit = True
        findings.extend(secret_findings)
        reason = "Command text appears to contain credentials or secrets."

    return RiskAssessment(
        category=category,
        risk_level=risk,
        reason=reason,
        blocked=blocked,
        explicit_approval_required=explicit,
        findings=findings,
        metadata={"command": command[:500]},
    )


def classify_file_mutation(tool_name: str, args: dict[str, Any]) -> RiskAssessment:
    paths = _mutation_paths(tool_name, args)
    deleted = _delete_count(tool_name, args)
    content = _mutation_content(tool_name, args)
    secret_findings = [finding.to_dict() for finding in detect_secrets(content)]
    category = "file_write"
    risk = "medium"
    reason = "Workspace file mutation."
    explicit = False
    blocked = False
    findings: list[dict[str, Any]] = []

    if any(_is_config_path(path) for path in paths):
        category = "config_edit"
        risk = "high"
        explicit = True
        reason = "The edit targets configuration or dependency files."
        findings.append({"kind": "config_edit", "paths": paths[:20]})

    if deleted:
        category = "file_delete"
        risk = "high"
        explicit = True
        reason = f"The edit deletes {deleted} file(s)."
        findings.append({"kind": "file_delete", "count": deleted})
        if deleted >= 8:
            risk = "critical"
            blocked = True
            reason = "The edit deletes too many files in one operation."

    if len(paths) >= 8:
        risk = _max_risk(risk, "high")
        explicit = True
        findings.append({"kind": "many_files", "count": len(paths)})

    if secret_findings:
        risk = _max_risk(risk, "high")
        explicit = True
        reason = "The edit appears to write credentials or secrets."
        findings.extend(secret_findings)

    return RiskAssessment(
        category=category,
        risk_level=risk,
        reason=reason,
        blocked=blocked,
        explicit_approval_required=explicit,
        findings=findings,
        metadata={"paths": paths, "delete_count": deleted},
    )


def cloud_transparency_report(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    context: str | None = None,
    token_estimate: int = 0,
    cost_per_million_input: float | None = None,
) -> dict[str, Any]:
    text = "\n".join(
        str(part)
        for part in [
            context or "",
            *[
                _content_text(message.get("content"))
                for message in messages[:12]
                if isinstance(message, dict)
            ],
        ]
        if part
    )
    files = _referenced_files(text)
    snippets = _workspace_snippets(text)
    secrets = [finding.to_dict() for finding in detect_secrets(text)]
    cost = None
    if cost_per_million_input is not None and token_estimate > 0:
        cost = round((token_estimate / 1_000_000) * float(cost_per_million_input), 6)
    return {
        "provider": provider,
        "model": model,
        "token_estimate": token_estimate,
        "estimated_cost_usd": cost,
        "files": files[:30],
        "snippets": snippets[:12],
        "secret_findings": secrets,
        "has_secret_findings": bool(secrets),
    }


def _mutation_paths(tool_name: str, args: dict[str, Any]) -> list[str]:
    if tool_name in {"write_file", "replace_in_file"}:
        path = args.get("path")
        return [str(path)] if isinstance(path, str) and path.strip() else []
    if tool_name == "apply_patch":
        changes = args.get("changes")
        if isinstance(changes, list):
            return [
                str(item.get("path"))
                for item in changes
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            ]
        patch = args.get("patch")
        if isinstance(patch, str):
            paths: list[str] = []
            for line in patch.splitlines():
                if line.startswith(("+++ ", "--- ")):
                    value = line[4:].strip().split("\t", 1)[0].split(" ", 1)[0]
                    if value in {"/dev/null", "dev/null"}:
                        continue
                    if value.startswith(("a/", "b/")):
                        value = value[2:]
                    paths.append(value)
            return _dedupe(paths)
    return []


def _mutation_content(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "write_file":
        return str(args.get("content") or "")
    if tool_name == "replace_in_file":
        return str(args.get("new") or "")
    if tool_name == "apply_patch":
        parts: list[str] = []
        changes = args.get("changes")
        if isinstance(changes, list):
            for item in changes:
                if not isinstance(item, dict):
                    continue
                for key in ("content", "new"):
                    value = item.get(key)
                    if isinstance(value, str):
                        parts.append(value)
        patch = args.get("patch")
        if isinstance(patch, str):
            parts.append(patch)
        return "\n".join(parts)
    return ""


def _delete_count(tool_name: str, args: dict[str, Any]) -> int:
    if tool_name != "apply_patch":
        return 0
    changes = args.get("changes")
    if isinstance(changes, list):
        return sum(1 for item in changes if isinstance(item, dict) and item.get("delete"))
    patch = args.get("patch")
    if not isinstance(patch, str):
        return 0
    return sum(1 for line in patch.splitlines() if line.startswith("+++ ") and "dev/null" in line)


def _is_config_path(value: str) -> bool:
    path = Path(value.replace("\\", "/"))
    name = path.name.lower()
    if name in CONFIG_FILENAMES:
        return True
    return name.endswith((".toml", ".yaml", ".yml", ".ini", ".cfg"))


def _normalize_command(command: str) -> str:
    return re.sub(r"\s+", " ", command.replace("`", "").lower()).strip()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _max_risk(left: str, right: str) -> str:
    return right if RISK_ORDER.get(right, 0) > RISK_ORDER.get(left, 0) else left


def _redacted_preview(value: str) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    if len(clean) <= 10:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


def _line_for_offset(starts: list[int], offset: int) -> int:
    line = 1
    for index, start in enumerate(starts, start=1):
        if start > offset:
            break
        line = index
    return line


def _referenced_files(text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"\s*(?:Current file|File|Reference):\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip().strip("\"'")
        if value and value not in seen:
            seen.add(value)
            files.append({"path": value, "source": "request_context"})
    return files


def _workspace_snippets(text: str) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    current_path = ""
    pending: list[str] = []
    for line in text.splitlines():
        match = re.match(r"\s*(?:Current file|File|Reference):\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if match:
            if current_path and pending:
                snippets.append({"path": current_path, "preview": "\n".join(pending)[:500]})
            current_path = match.group(1).strip().strip("\"'")
            pending = []
            continue
        if current_path and line.strip():
            pending.append(line[:220])
            if len(pending) >= 4:
                snippets.append({"path": current_path, "preview": "\n".join(pending)[:500]})
                current_path = ""
                pending = []
    if current_path and pending:
        snippets.append({"path": current_path, "preview": "\n".join(pending)[:500]})
    return snippets


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts)
    if isinstance(content, dict):
        value = content.get("text") or content.get("content")
        if isinstance(value, str):
            return value
    return str(content)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

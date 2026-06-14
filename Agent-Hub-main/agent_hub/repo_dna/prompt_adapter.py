from __future__ import annotations

from .dna_profile import RepoDNAProfile


def repository_prompt_prefix(profile: RepoDNAProfile | dict[str, object]) -> str:
    data = profile.to_dict() if hasattr(profile, "to_dict") else dict(profile)
    tools = sorted(set([*list(data.get("lint_tools") or []), *list(data.get("formatting_tools") or [])]))
    dependencies = [str(item) for item in list(data.get("dependencies") or [])[:8]]
    lines = [
        "This repository uses:",
        f"- {data.get('language') or 'unknown'}",
        f"- {data.get('framework') or 'unknown'}",
        f"- {data.get('test_framework') or 'unknown'}",
        f"- {data.get('package_manager') or 'unknown'}",
        f"- {data.get('architecture_pattern') or 'unknown'}",
    ]
    for dependency in dependencies:
        if dependency and dependency.lower() not in "\n".join(lines).lower():
            lines.append(f"- {dependency}")
    if tools:
        lines.append(f"- {', '.join(str(tool) for tool in tools)} formatting")
    lines.extend(
        [
            "",
            "Follow the existing style.",
            "Prefer tests in tests/.",
            "Do not change public APIs unless required.",
        ]
    )
    return "\n".join(lines)


def adapt_prompt(prompt: str, profile: RepoDNAProfile | dict[str, object], *, separator: str = "\n\n") -> str:
    prefix = repository_prompt_prefix(profile)
    prompt = str(prompt or "").strip()
    if not prompt:
        return prefix
    if prompt.startswith("This repository uses:"):
        return prompt
    return f"{prefix}{separator}{prompt}"

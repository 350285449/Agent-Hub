from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.config_reference import generate_config_reference


def main() -> int:
    reference_path = Path("docs/config-reference.md")
    expected = generate_config_reference()
    actual = reference_path.read_text(encoding="utf-8")
    if actual != expected:
        print("docs/config-reference.md is out of date. Regenerate it with:")
        print("python -m agent_hub.config_reference > docs/config-reference.md")
        return 1
    print("Config reference is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

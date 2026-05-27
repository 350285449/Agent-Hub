from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backend_snapshot import validate_snapshot


def main() -> int:
    failures = validate_snapshot(ROOT)
    if failures:
        print("Backend snapshot drift detected:")
        for failure in failures:
            print(f"- {failure}")
        print("Regenerate with: python scripts/generate_backend_snapshot.py")
        return 1
    print("Backend snapshot matches canonical agent_hub source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

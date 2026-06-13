from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backend_snapshot import generate_snapshot


def main() -> int:
    manifest = generate_snapshot(ROOT)
    print(
        "Generated backend snapshot: "
        f"{manifest['file_count']} files, tree {manifest['tree_sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

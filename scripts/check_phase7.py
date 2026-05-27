from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run lightweight Phase 7 readiness checks.")
    parser.add_argument("--skip-unittest", action="store_true", help="Skip unittest discovery.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    commands = [
        [python, "-m", "compileall", "-q", "agent_hub", "scripts"],
        [python, "scripts/check_config_reference.py"],
        [python, "scripts/check_config_migration_coverage.py"],
        [python, "scripts/validate_backend_drift.py"],
        [python, "scripts/validate_release.py"],
        [python, "scripts/validate_vsix_cleanliness.py"],
    ]
    if not args.skip_unittest:
        commands.insert(1, [python, "-m", "unittest", "discover", "-s", "tests"])
    node = shutil.which("node")
    if node:
        commands.append([node, "vscode-extension/scripts/check-version.js"])
    else:
        print("node was not found; extension version consistency check cannot run.")
        return 1

    for command in commands:
        print(f"> {' '.join(command)}")
        completed = subprocess.run(command, cwd=root)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

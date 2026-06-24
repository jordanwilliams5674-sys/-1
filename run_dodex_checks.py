from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/dodex", "-p", "test_*.py"],
        [sys.executable, "-m", "dodex.cli", "doctor"],
        [sys.executable, "-m", "dodex.cli", "backtest"],
        [sys.executable, "-m", "dodex.cli", "trade:paper"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

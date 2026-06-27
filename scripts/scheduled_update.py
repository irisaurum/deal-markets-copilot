from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOW_START = time(8, 30)
WINDOW_END = time(18, 30)


def is_update_window(now: datetime) -> bool:
    return now.weekday() < 5 and WINDOW_START <= now.time() <= WINDOW_END


def main() -> int:
    parser = argparse.ArgumentParser(description="Scheduled Deal Desk live update")
    parser.add_argument("--force", action="store_true", help="Run outside the weekday update window")
    args = parser.parse_args()
    now = datetime.now().astimezone()
    if not args.force and not is_update_window(now):
        print(f"Skipped outside update window: {now.isoformat(timespec='seconds')}")
        return 0

    result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--live"],
        cwd=ROOT,
        check=False,
        timeout=180,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

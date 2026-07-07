"""Expose the canonical Summary selector to the local JavaScript workbook builder."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deal_markets_copilot.deals import select_key_deals


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rows = json.load(sys.stdin)
    json.dump(select_key_deals(rows, limit), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()

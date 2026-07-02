"""Fail the build when HTML, JSON, CSV and XLSX do not describe one dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def dataset_build_id(rows: list[dict]) -> str:
    payload = "\n".join(
        "|".join(str(row.get(field) or "") for field in (
            "deal_id", "record_kind", "quality_status", "source_count", "headline",
        ))
        for row in sorted(rows, key=lambda item: str(item.get("deal_id") or ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    rows = json.loads((ROOT / "data" / "precedent_transactions.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "output" / "build_manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((ROOT / "output" / "latest_snapshot.json").read_text(encoding="utf-8"))
    html = (ROOT / "output" / "deal_markets_brief.html").read_text(encoding="utf-8")
    with (ROOT / "output" / "precedent_transactions.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    expected = dataset_build_id(rows)
    assert manifest.get("build_id") == expected, "XLSX manifest build ID is stale"
    assert manifest.get("record_count") == len(rows), "XLSX manifest record count is stale"
    assert snapshot.get("health", {}).get("build_id") == expected, "Snapshot build ID is stale"
    assert snapshot.get("health", {}).get("xlsx_synced") is True, "Snapshot says XLSX is not synchronized"
    assert expected in html, "Dashboard does not expose the synchronized build ID"
    assert len(csv_rows) == len(rows), "CSV and JSON record counts differ"
    with zipfile.ZipFile(ROOT / "output" / "precedent_transactions.xlsx") as workbook:
        assert "xl/workbook.xml" in workbook.namelist(), "XLSX package is invalid"
    print(f"Artifacts synchronized: build={expected}, records={len(rows)}")


if __name__ == "__main__":
    main()

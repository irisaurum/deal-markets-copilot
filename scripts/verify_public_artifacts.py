"""Fail the build when HTML, JSON, CSV and XLSX do not describe one dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deal_markets_copilot.deals import CSV_FIELDS, _is_technical_filing, select_deal_buckets, select_key_deals


def dataset_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_value(row: dict, field: str) -> str:
    value = row.get(field)
    if field in {"matched_coverage", "quality_flags"}:
        return ", ".join(value or [])
    if field == "sources":
        return json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)


def workbook_text(workbook: zipfile.ZipFile) -> str:
    """Read cell text from both shared-string and inline-string XLSX files."""
    values: list[str] = []
    for name in workbook.namelist():
        if name == "xl/sharedStrings.xml" or (name.startswith("xl/worksheets/") and name.endswith(".xml")):
            try:
                root = ET.fromstring(workbook.read(name))
            except ET.ParseError:
                continue
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] in {"t", "v"} and node.text:
                    values.append(node.text)
    return "\n".join(values)


def main() -> None:
    dataset_path = ROOT / "data" / "precedent_transactions.json"
    rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "output" / "build_manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((ROOT / "output" / "latest_snapshot.json").read_text(encoding="utf-8"))
    html = (ROOT / "output" / "deal_markets_brief.html").read_text(encoding="utf-8")
    with (ROOT / "output" / "precedent_transactions.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    digest = dataset_digest(dataset_path)
    expected = digest[:12]
    assert manifest.get("dataset_sha256") == digest, "XLSX manifest dataset hash is stale"
    assert manifest.get("build_id") == expected, "XLSX manifest build ID is stale"
    assert manifest.get("record_count") == len(rows), "XLSX manifest record count is stale"
    assert snapshot.get("health", {}).get("build_id") == expected, "Snapshot build ID is stale"
    assert snapshot.get("health", {}).get("xlsx_synced") is True, "Snapshot says XLSX is not synchronized"
    assert snapshot.get("health", {}).get("source_status") == "ok", "One or more sources failed"
    assert snapshot.get("health", {}).get("discovery_status") == "ok", "All news discovery sources returned zero records"
    assert snapshot.get("health", {}).get("freshness_status") == "ok", "Source data is stale"
    assert snapshot.get("health", {}).get("system_status") == "ok", "Dashboard health is not green"
    assert expected in html, "Dashboard does not expose the synchronized build ID"
    assert len(csv_rows) == len(rows), "CSV and JSON record counts differ"
    assert list(csv_rows[0]) == CSV_FIELDS, "CSV columns differ from the public schema"
    for index, (source, exported) in enumerate(zip(rows, csv_rows, strict=True), start=2):
        for field in CSV_FIELDS:
            assert exported[field] == csv_value(source, field), f"CSV mismatch at row {index}, field {field}"
    assert not any(row.get("deal_type") == "DCM" and row.get("status") == "Closed" for row in rows), "DCM records still use M&A Closed status"
    technical_patterns = ("о проведении выкупа облигаций", "о регистрации выпуска", "о порядке сбора заявок", "операции репо")
    assert not any(str(item.get("event", {}).get("title") or "").lower().startswith(technical_patterns) for item in snapshot.get("events", [])), "Technical filing leaked into live signals"
    assert not any(_is_technical_filing(str(row.get("headline") or "")) and row.get("record_kind") != "technical_filing" for row in rows), "Technical filing is stored in a transaction stream"
    buckets = select_deal_buckets(rows, 10)
    assert all(row.get("deal_type") == "M&A" for row in buckets["watchlist"]), "Review stream contains a routine ECM/DCM item"
    assert len(select_key_deals(rows, 10)) <= 10, "Key-deal view exceeds its stated limit"
    auto_rows = [row for row in rows if "авто.ру" in str(row.get("headline") or "").lower()]
    assert not auto_rows or all(row.get("acquirer_or_investor") == "T-Technologies" for row in auto_rows), "Auto.ru buyer is missing"
    assert "Подтверждённые" not in html and "Слухи и переговоры" not in html, "Dashboard contains obsolete stream labels"
    key_deal_count = len(select_key_deals(rows, 10))
    assert f"{key_deal_count} строк" in html, "Dashboard table row label is inconsistent"
    with zipfile.ZipFile(ROOT / "output" / "precedent_transactions.xlsx") as workbook:
        assert "xl/workbook.xml" in workbook.namelist(), "XLSX package is invalid"
        workbook_xml = workbook.read("xl/workbook.xml")
        sheet_names = re.findall(rb'<(?:\w+:)?sheet\s+name="([^"]+)"', workbook_xml)
        assert sheet_names == [b"Summary", b"Deals", b"Financials", b"Multiples", b"Sources &amp; QA"], "XLSX sheet contract changed"
        xml = b"\n".join(workbook.read(name) for name in workbook.namelist() if name.endswith(".xml"))
        assert expected.encode() in xml, "Workbook does not contain the current Build ID"
        cells = workbook_text(workbook)
        missing_ids = [str(row.get("deal_id")) for row in rows if str(row.get("deal_id")) not in cells]
        assert not missing_ids, f"Workbook is missing {len(missing_ids)} deal IDs"
    print(f"Artifacts synchronized: build={expected}, records={len(rows)}")


if __name__ == "__main__":
    main()

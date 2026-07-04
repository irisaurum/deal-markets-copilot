"""Fail the build when HTML, JSON, CSV and XLSX do not describe one dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
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
    assert isinstance(rows, list) and rows, "Dataset must be a non-empty list"
    deal_ids = [str(row.get("deal_id") or "") for row in rows]
    assert all(deal_ids), "Every record must have a deal ID"
    assert len(deal_ids) == len(set(deal_ids)), "Dataset contains duplicate deal IDs"
    for row in rows:
        deal_id = str(row.get("deal_id"))
        assert row.get("headline") and row.get("target_or_issuer") and row.get("announced_date"), f"Missing identity field: {deal_id}"
        try:
            date.fromisoformat(str(row["announced_date"])[:10])
        except ValueError as exc:
            raise AssertionError(f"Invalid announced date: {deal_id}") from exc
        assert str(row.get("first_seen_at") or "") <= str(row.get("last_seen_at") or ""), f"Invalid seen range: {deal_id}"
        sources = [source for source in row.get("sources", []) if isinstance(source, dict)]
        unique_sources = {
            (str(source.get("url") or ""), "" if source.get("url") else str(source.get("name") or "").lower())
            for source in sources
        }
        assert row.get("source_count") == len(unique_sources), f"Source count mismatch: {deal_id}"
        assert all(str(source.get("url") or "").startswith(("http://", "https://")) for source in sources), f"Unsafe or empty evidence URL: {deal_id}"
        assert row.get("currency") in {"Not disclosed", "RUB", "USD", "EUR", "CNY", "GBP", "CHF"}, f"Invalid currency: {deal_id}"
        for field in ("stake_percent", "discount_percent", "free_float_percent"):
            value = row.get(field)
            assert value is None or 0 <= float(value) <= 100, f"Invalid {field}: {deal_id}"
        if row.get("quality_status") == "approved":
            assert row.get("record_kind") == "deal" and not row.get("quality_flags"), f"Approved record has blockers: {deal_id}"
    assert manifest.get("dataset_sha256") == digest, "XLSX manifest dataset hash is stale"
    assert manifest.get("build_id") == expected, "XLSX manifest build ID is stale"
    assert manifest.get("record_count") == len(rows), "XLSX manifest record count is stale"
    assert snapshot.get("health", {}).get("build_id") == expected, "Snapshot build ID is stale"
    assert snapshot.get("health", {}).get("dataset_sha256") == digest, "Snapshot dataset hash is stale"
    assert snapshot.get("health", {}).get("record_count") == len(rows), "Snapshot record count is stale"
    assert snapshot.get("health", {}).get("xlsx_synced") is True, "Snapshot says XLSX is not synchronized"
    assert snapshot.get("health", {}).get("source_status") == "ok", "One or more sources failed"
    assert snapshot.get("health", {}).get("discovery_status") == "ok", "All news discovery sources returned zero records"
    assert snapshot.get("health", {}).get("freshness_status") == "ok", "Source data is stale"
    assert snapshot.get("health", {}).get("system_status") == "ok", "Dashboard health is not green"
    required_runs = [run for run in snapshot.get("health", {}).get("source_runs", []) if run.get("required")]
    assert required_runs and all(run.get("status") == "ok" and int(run.get("records") or 0) > 0 for run in required_runs), "Required source did not return usable records"
    assert expected in html, "Dashboard does not expose the synchronized build ID"
    assert not re.search(r"(?:file://|localhost|/Users/|javascript:)", html, re.I), "Dashboard exposes a local or unsafe URL"
    for anchor in re.findall(r"<a\b[^>]*target=[\"']_blank[\"'][^>]*>", html, re.I):
        assert re.search(r"\brel=[\"'][^\"']*noopener", anchor, re.I), "External target=_blank link misses rel=noopener"
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
        workbook_ids = set(re.findall(r"(?:DL-[A-Z0-9-]{8,}|CURATED-[A-Z0-9-]+)", cells, re.I))
        assert workbook_ids == set(deal_ids), "Workbook contains missing or phantom deal IDs"
        assert not re.search(r"#(?:REF!|DIV/0!|VALUE!|NAME\?|N/A)", cells), "Workbook contains a formula error"
    print(f"Artifacts synchronized: build={expected}, records={len(rows)}")


if __name__ == "__main__":
    main()

"""Fail the build when HTML, JSON, CSV and XLSX do not describe one dataset."""
from __future__ import annotations

import csv
import hashlib
import json
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deal_markets_copilot.deals import CSV_FIELDS, _is_technical_filing, _multiple_is_eligible, select_deal_buckets, select_key_deals


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EXPECTED_SHEETS = ["Summary", "Deals", "Financials", "Multiples", "Sources & QA"]


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


def shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(f".//{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def workbook_sheets(workbook: zipfile.ZipFile) -> tuple[list[str], dict[str, str]]:
    root = ET.fromstring(workbook.read("xl/workbook.xml"))
    relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relationship.get("Id"): relationship.get("Target")
        for relationship in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    names: list[str] = []
    paths: dict[str, str] = {}
    for sheet in root.findall(f".//{{{MAIN_NS}}}sheet"):
        name = str(sheet.get("name") or "")
        target = str(targets.get(sheet.get(f"{{{REL_NS}}}id")) or "")
        assert target, f"XLSX relationship is missing for sheet: {name}"
        names.append(name)
        paths[name] = target.lstrip("/") if target.startswith("/xl/") else posixpath.normpath(posixpath.join("xl", target))
    return names, paths


def sheet_rows(workbook: zipfile.ZipFile, path: str, strings: list[str]) -> dict[int, dict[str, str]]:
    root = ET.fromstring(workbook.read(path))
    result: dict[int, dict[str, str]] = {}
    for row in root.findall(f".//{{{MAIN_NS}}}row"):
        row_number = int(row.get("r") or 0)
        cells: dict[str, str] = {}
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            reference = str(cell.get("r") or "")
            match = re.match(r"([A-Z]+)", reference)
            if not match:
                continue
            cell_type = cell.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(f".//{{{MAIN_NS}}}t"))
            else:
                value_node = cell.find(f"{{{MAIN_NS}}}v")
                value = value_node.text if value_node is not None and value_node.text is not None else ""
                if cell_type == "s" and value:
                    value = strings[int(value)]
            cells[match.group(1)] = value
        result[row_number] = cells
    return result


def table_records(rows: dict[int, dict[str, str]], header_row: int) -> list[dict[str, str]]:
    headers = rows.get(header_row, {})
    records: list[dict[str, str]] = []
    for row_number in sorted(number for number in rows if number > header_row):
        values = rows[row_number]
        record = {header: values.get(column, "") for column, header in headers.items() if header}
        if any(value != "" for value in record.values()):
            records.append(record)
    return records


def normalized_count(value) -> str:
    if value in {None, ""}:
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def summary_signature(row: dict, workbook_row: bool = False) -> tuple[str, ...]:
    if workbook_row:
        return (
            str(row.get("Type") or ""),
            str(row.get("Status") or ""),
            str(row.get("Target / Issuer") or ""),
            str(row.get("Buyer / Investor") or ""),
            str(row.get("Currency") or ""),
            str(row.get("Quality") or ""),
            normalized_count(row.get("Sources")),
            str(row.get("Headline") or ""),
        )
    return (
        str(row.get("deal_type") or ""),
        str(row.get("status") or ""),
        str(row.get("target_or_issuer") or ""),
        str(row.get("acquirer_or_investor") or ""),
        str(row.get("currency") or ""),
        str(row.get("quality_status") or ""),
        normalized_count(row.get("source_count")),
        str(row.get("headline") or ""),
    )


def assert_exact_ids(sheet_name: str, actual_ids: list[str], expected_ids: list[str]) -> None:
    actual = [deal_id for deal_id in actual_ids if deal_id]
    expected = [deal_id for deal_id in expected_ids if deal_id]
    duplicate_ids = sorted(deal_id for deal_id, count in Counter(actual).items() if count > 1)
    missing_ids = sorted(set(expected) - set(actual))
    extra_ids = sorted(set(actual) - set(expected))
    assert not duplicate_ids, f"{sheet_name} contains duplicate deal IDs: {duplicate_ids[:5]}"
    assert not missing_ids, f"{sheet_name} is missing deal IDs: {missing_ids[:5]}"
    assert not extra_ids, f"{sheet_name} contains phantom deal IDs: {extra_ids[:5]}"
    assert len(actual) == len(expected), f"{sheet_name} row count differs: actual={len(actual)}, expected={len(expected)}"


def verify_workbook(path: Path, rows: list[dict], expected_build_id: str) -> None:
    deal_ids = [str(row.get("deal_id") or "") for row in rows]
    with zipfile.ZipFile(path) as workbook:
        assert "xl/workbook.xml" in workbook.namelist(), "XLSX package is invalid"
        names, paths = workbook_sheets(workbook)
        assert names == EXPECTED_SHEETS, f"XLSX sheet contract changed: {names}"
        xml = b"\n".join(workbook.read(name) for name in workbook.namelist() if name.endswith(".xml"))
        assert expected_build_id.encode() in xml, "Workbook does not contain the current Build ID"
        strings = shared_strings(workbook)
        parsed = {name: sheet_rows(workbook, paths[name], strings) for name in EXPECTED_SHEETS}

        deals = table_records(parsed["Deals"], 6)
        assert_exact_ids("Deals", [record.get("Deal ID", "") for record in deals], deal_ids)

        expected_key_deals = select_key_deals(rows, 10)
        signature_ids: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for row in rows:
            signature_ids[summary_signature(row)].append(str(row.get("deal_id") or ""))
        summary_ids: list[str] = []
        unmatched: list[tuple[str, ...]] = []
        ambiguous: list[tuple[str, ...]] = []
        for record in table_records(parsed["Summary"], 18):
            signature = summary_signature(record, workbook_row=True)
            matches = signature_ids.get(signature, [])
            if len(matches) == 1:
                summary_ids.append(matches[0])
            elif matches:
                ambiguous.append(signature)
            else:
                unmatched.append(signature)
        assert not unmatched, f"Summary contains rows that do not match the dataset: {len(unmatched)}"
        assert not ambiguous, f"Summary rows cannot be mapped to unique deal IDs: {len(ambiguous)}"
        assert_exact_ids("Summary", summary_ids, [str(row.get("deal_id") or "") for row in expected_key_deals])

        expected_financial_ids = [
            str(row.get("deal_id") or "")
            for row in rows
            if row.get("revenue_ltm") or row.get("ebitda_ltm") or row.get("financials_source_url")
        ]
        financials = table_records(parsed["Financials"], 6)
        assert_exact_ids("Financials", [record.get("Deal ID", "") for record in financials], expected_financial_ids)

        expected_multiple_ids = [
            str(row.get("deal_id") or "")
            for row in rows
            if _multiple_is_eligible(row) and bool(row.get("ev_revenue") or row.get("ev_ebitda"))
        ]
        multiple_records = table_records(parsed["Multiples"], 6)
        actual_multiple_ids = [
            record.get("Deal ID", "")
            for record in multiple_records
            if str(record.get("Model Eligible") or "").upper() == "YES"
        ]
        assert_exact_ids("Multiples eligible rows", actual_multiple_ids, expected_multiple_ids)

        expected_sources = Counter({
            str(row.get("deal_id") or ""): len([source for source in row.get("sources", []) if isinstance(source, dict)])
            for row in rows
            if row.get("sources")
        })
        source_records = table_records(parsed["Sources & QA"], 6)
        actual_sources = Counter(record.get("Deal ID", "") for record in source_records if record.get("Deal ID"))
        assert actual_sources == expected_sources, "Sources & QA deal/source multiplicity differs from the dataset"
        expected_source_rows = Counter()
        for row in rows:
            for source in row.get("sources", []):
                if not isinstance(source, dict):
                    continue
                representations = source.get("representations") if isinstance(source.get("representations"), list) and source.get("representations") else [source]
                expected_source_rows[(
                    str(row.get("deal_id") or ""),
                    str(source.get("url") or ""),
                    str(len(representations)),
                    "\n".join(str(item.get("url") or "") for item in representations),
                )] += 1
        actual_source_rows = Counter(
            (
                str(record.get("Deal ID") or ""),
                str(record.get("Canonical URL") or ""),
                normalized_count(record.get("Representation Count")),
                str(record.get("Representation URLs") or ""),
            )
            for record in source_records if record.get("Deal ID")
        )
        assert actual_source_rows == expected_source_rows, "Sources & QA publication/representation semantics differ from the dataset"

        cells = workbook_text(workbook)
        assert not re.search(r"#(?:REF!|DIV/0!|VALUE!|NAME\?|N/A)", cells), "Workbook contains a formula error"


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
        assert len(unique_sources) == len(sources), f"Duplicate canonical publication source: {deal_id}"
        assert row.get("source_count") == len(sources), f"Source count mismatch: {deal_id}"
        assert all(str(source.get("url") or "").startswith(("http://", "https://")) for source in sources), f"Unsafe or empty evidence URL: {deal_id}"
        for source in sources:
            representations = source.get("representations") if isinstance(source.get("representations"), list) and source.get("representations") else [source]
            representation_urls = [str(item.get("url") or "") for item in representations if isinstance(item, dict)]
            assert source.get("url") in representation_urls, f"Canonical source missing from representations: {deal_id}"
            assert len(representation_urls) == len(set(representation_urls)), f"Duplicate raw source representation: {deal_id}"
            assert all(url.startswith(("http://", "https://")) for url in representation_urls), f"Unsafe raw source representation: {deal_id}"
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
    verify_workbook(ROOT / "output" / "precedent_transactions.xlsx", rows, expected)
    print(f"Artifacts synchronized: build={expected}, records={len(rows)}")


if __name__ == "__main__":
    main()

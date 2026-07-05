from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import verify_public_artifacts
from deal_markets_copilot.deals import select_key_deals


ROOT = Path(__file__).resolve().parents[1]
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{MAIN_NS}}}t"))
    value = cell.find(f"{{{MAIN_NS}}}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value.text)]
    return value.text


def _set_inline_text(cell: ET.Element, value: str) -> None:
    for child in list(cell):
        cell.remove(child)
    cell.set("t", "inlineStr")
    inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
    text = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
    text.text = value


def _rewrite_workbook(path: Path, mutate) -> None:
    with zipfile.ZipFile(path) as source:
        files = {name: source.read(name) for name in source.namelist()}

    shared_strings: list[str] = []
    if "xl/sharedStrings.xml" in files:
        root = ET.fromstring(files["xl/sharedStrings.xml"])
        shared_strings = [
            "".join(node.text or "" for node in item.findall(f".//{{{MAIN_NS}}}t"))
            for item in root.findall(f"{{{MAIN_NS}}}si")
        ]

    workbook = ET.fromstring(files["xl/workbook.xml"])
    relationships = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    sheets: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
        target = targets[sheet.get(f"{{{REL_NS}}}id")]
        sheets[sheet.get("name")] = "xl/" + target.lstrip("/")

    mutate(files, sheets, shared_strings)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as destination:
        for name, content in files.items():
            destination.writestr(name, content)


def _remove_sheet_row(path: Path, sheet_name: str, deal_id: str) -> None:
    def mutate(files, sheets, shared_strings):
        sheet = ET.fromstring(files[sheets[sheet_name]])
        sheet_data = sheet.find(f"{{{MAIN_NS}}}sheetData")
        for row in sheet_data.findall(f"{{{MAIN_NS}}}row"):
            first_cell = row.find(f"{{{MAIN_NS}}}c")
            if first_cell is not None and _cell_text(first_cell, shared_strings) == deal_id:
                sheet_data.remove(row)
                files[sheets[sheet_name]] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
                return
        raise AssertionError(f"{sheet_name} row not found: {deal_id}")

    _rewrite_workbook(path, mutate)


def _replace_deals_id(path: Path, old_id: str, new_id: str) -> None:
    def mutate(files, sheets, shared_strings):
        sheet = ET.fromstring(files[sheets["Deals"]])
        for row in sheet.findall(f".//{{{MAIN_NS}}}row"):
            first_cell = row.find(f"{{{MAIN_NS}}}c")
            if first_cell is not None and _cell_text(first_cell, shared_strings) == old_id:
                _set_inline_text(first_cell, new_id)
                files[sheets["Deals"]] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
                return
        raise AssertionError(f"Deal row not found: {old_id}")

    _rewrite_workbook(path, mutate)


def _append_phantom_deals_id(path: Path, deal_id: str) -> None:
    def mutate(files, sheets, shared_strings):
        sheet = ET.fromstring(files[sheets["Deals"]])
        sheet_data = sheet.find(f"{{{MAIN_NS}}}sheetData")
        row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": "999"})
        cell = ET.SubElement(row, f"{{{MAIN_NS}}}c", {"r": "A999"})
        _set_inline_text(cell, deal_id)
        files[sheets["Deals"]] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)

    _rewrite_workbook(path, mutate)


def _replace_summary_row(path: Path, current_headline: str, replacement: dict) -> None:
    def mutate(files, sheets, shared_strings):
        sheet = ET.fromstring(files[sheets["Summary"]])
        for cell in sheet.findall(f".//{{{MAIN_NS}}}c"):
            if cell.get("r", "").startswith("J") and _cell_text(cell, shared_strings) == current_headline:
                row_number = re.sub(r"\D", "", cell.get("r", ""))
                values = {
                    "A": replacement.get("announced_date"),
                    "B": replacement.get("deal_type"),
                    "C": replacement.get("status"),
                    "D": replacement.get("target_or_issuer"),
                    "E": replacement.get("acquirer_or_investor"),
                    "F": replacement.get("transaction_value"),
                    "G": replacement.get("currency"),
                    "H": replacement.get("quality_status"),
                    "I": replacement.get("source_count"),
                    "J": replacement.get("headline"),
                }
                row = next(item for item in sheet.findall(f".//{{{MAIN_NS}}}row") if item.get("r") == row_number)
                cells = {re.match(r"([A-Z]+)", item.get("r", "")).group(1): item for item in row.findall(f"{{{MAIN_NS}}}c")}
                for column, value in values.items():
                    target = cells.get(column)
                    if target is None:
                        target = ET.SubElement(row, f"{{{MAIN_NS}}}c", {"r": f"{column}{row_number}"})
                    _set_inline_text(target, "" if value is None else str(value))
                files[sheets["Summary"]] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
                return
        raise AssertionError(f"Summary headline not found: {current_headline}")

    _rewrite_workbook(path, mutate)


class XlsxVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = json.loads((ROOT / "data" / "precedent_transactions.json").read_text(encoding="utf-8"))

    def _fixture_root(self, directory: str) -> Path:
        root = Path(directory)
        (root / "data").mkdir()
        (root / "output").mkdir()
        shutil.copy2(ROOT / "data" / "precedent_transactions.json", root / "data")
        for name in (
            "build_manifest.json",
            "latest_snapshot.json",
            "deal_markets_brief.html",
            "precedent_transactions.csv",
            "precedent_transactions.xlsx",
        ):
            shutil.copy2(ROOT / "output" / name, root / "output" / name)
        return root

    def _verify(self, root: Path) -> None:
        with patch.object(verify_public_artifacts, "ROOT", root):
            verify_public_artifacts.main()

    def test_strict_verifier_accepts_correct_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._verify(self._fixture_root(directory))

    def test_strict_verifier_rejects_missing_deals_row_when_id_exists_on_other_sheet(self) -> None:
        deal_id = next(row["deal_id"] for row in self.rows if row.get("sources"))
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _remove_sheet_row(root / "output" / "precedent_transactions.xlsx", "Deals", deal_id)
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_duplicate_deals_id(self) -> None:
        source_backed_ids = [row["deal_id"] for row in self.rows if row.get("sources")]
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _replace_deals_id(root / "output" / "precedent_transactions.xlsx", source_backed_ids[1], source_backed_ids[0])
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_extra_phantom_deals_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _append_phantom_deals_id(root / "output" / "precedent_transactions.xlsx", "DL-PHANTOM-12345678")
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_wrong_summary_current_deal_set(self) -> None:
        current = select_key_deals(self.rows, 10)
        current_ids = {row["deal_id"] for row in current}
        historical = next(row for row in self.rows if row["deal_id"] not in current_ids)
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _replace_summary_row(
                root / "output" / "precedent_transactions.xlsx",
                current[0]["headline"],
                historical,
            )
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_technical_filing_in_summary(self) -> None:
        current = select_key_deals(self.rows, 10)
        technical = next(row for row in self.rows if row.get("record_kind") == "technical_filing")
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _replace_summary_row(
                root / "output" / "precedent_transactions.xlsx",
                current[0]["headline"],
                technical,
            )
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_missing_financials_row(self) -> None:
        deal_id = next(
            row["deal_id"]
            for row in self.rows
            if row.get("revenue_ltm") or row.get("ebitda_ltm") or row.get("financials_source_url")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _remove_sheet_row(root / "output" / "precedent_transactions.xlsx", "Financials", deal_id)
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_missing_eligible_multiples_row(self) -> None:
        from deal_markets_copilot.deals import _multiple_is_eligible

        deal_id = next(
            row["deal_id"]
            for row in self.rows
            if _multiple_is_eligible(row) and (row.get("ev_revenue") or row.get("ev_ebitda"))
        )
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _remove_sheet_row(root / "output" / "precedent_transactions.xlsx", "Multiples", deal_id)
            with self.assertRaises(AssertionError):
                self._verify(root)

    def test_strict_verifier_rejects_missing_source_register_row(self) -> None:
        deal_id = next(row["deal_id"] for row in self.rows if row.get("sources"))
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture_root(directory)
            _remove_sheet_row(root / "output" / "precedent_transactions.xlsx", "Sources & QA", deal_id)
            with self.assertRaises(AssertionError):
                self._verify(root)


if __name__ == "__main__":
    unittest.main()

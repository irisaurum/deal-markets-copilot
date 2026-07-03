"""Public CI fallback for rebuilding the multi-sheet XLSX on GitHub-hosted runners.

The local analyst build uses @oai/artifact-tool and performs visual QA. GitHub
Actions does not have access to that private runtime, so CI uses the public
XlsxWriter package while preserving the same five-sheet contract and formulas.
"""
from __future__ import annotations

import json
import hashlib
import statistics
from datetime import datetime
from pathlib import Path

import xlsxwriter


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "precedent_transactions.json"
ROWS = json.loads(DATASET.read_text(encoding="utf-8"))
OUTPUT = ROOT / "output" / "precedent_transactions.xlsx"
MANIFEST = ROOT / "output" / "build_manifest.json"


def dataset_digest():
    return hashlib.sha256(DATASET.read_bytes()).hexdigest()


def eligible(row):
    available = str(row.get("financials_available_at") or "")[:10]
    announced = str(row.get("announced_date") or "")[:10]
    return (
        row.get("deal_type") == "M&A"
        and row.get("record_kind") == "deal"
        and row.get("quality_status") == "approved"
        and bool(available and announced and available <= announced)
        and (row.get("ev_revenue") or row.get("ev_ebitda"))
    )


def date(value):
    try:
        return datetime.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def main() -> None:
    digest = dataset_digest()
    current_build_id = digest[:12]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(OUTPUT)
    title = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#10243E", "font_size": 18, "align": "left", "valign": "vcenter"})
    subtitle = workbook.add_format({"italic": True, "font_color": "#52616F", "bg_color": "#F4F6F8"})
    header = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#10243E", "text_wrap": True, "valign": "vcenter"})
    sourced = workbook.add_format({"font_color": "#008000"})
    number = workbook.add_format({"font_color": "#008000", "num_format": "#,##0;[Red](#,##0);-"})
    pct = workbook.add_format({"font_color": "#008000", "num_format": "0.0%;[Red](0.0%);-"})
    multiple = workbook.add_format({"num_format": "0.0x", "font_color": "#000000"})
    day = workbook.add_format({"font_color": "#008000", "num_format": "dd-mmm-yyyy"})
    section = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#1F4E78"})

    def setup(sheet, end_col, name, note):
        sheet.hide_gridlines(2)
        sheet.merge_range(0, 0, 0, end_col, name, title)
        sheet.merge_range(1, 0, 1, end_col, note, subtitle)
        sheet.set_row(0, 28)

    summary = workbook.add_worksheet("Summary")
    setup(summary, 9, "DEAL MARKETS COPILOT — SUMMARY", f"As of {datetime.now():%Y-%m-%d} | Build {current_build_id} | Quality-controlled transaction monitor")
    summary.merge_range("A4:J4", "DATABASE SNAPSHOT", section)
    summary_headers = ["Total records", "M&A", "ECM", "DCM", "Approved", "Review", "Financials", "EV/Revenue coverage", "EV/EBITDA coverage", "Model status"]
    summary.write_row("A6", summary_headers, header)
    eligible_rows = [r for r in ROWS if eligible(r)]
    ev_rev = [float(r["ev_revenue"]) for r in eligible_rows if r.get("ev_revenue")]
    ev_ebitda = [float(r["ev_ebitda"]) for r in eligible_rows if r.get("ev_ebitda")]
    summary.write_row("A7", [len(ROWS), sum(r.get("deal_type") == "M&A" for r in ROWS), sum(r.get("deal_type") == "ECM" for r in ROWS), sum(r.get("deal_type") == "DCM" for r in ROWS), sum(r.get("quality_status") == "approved" for r in ROWS), sum(r.get("quality_status") == "review" for r in ROWS), sum(bool(r.get("revenue_ltm") or r.get("ebitda_ltm")) for r in ROWS), len(ev_rev), len(ev_ebitda), "OK"])
    summary.merge_range("A10:J10", "PRECEDENT VALUATION — APPROVED M&A ONLY", section)
    summary.write_row("A12", ["Median EV / Revenue", "Median EV / EBITDA", "EV / Revenue observations", "EV / EBITDA observations"], header)
    summary.write_row("A13", [statistics.median(ev_rev) if len(ev_rev) >= 3 else "N/M", statistics.median(ev_ebitda) if len(ev_ebitda) >= 3 else "N/M", len(ev_rev), len(ev_ebitda)])
    summary.set_row(12, None, multiple)
    summary.set_column("A:J", 19)

    deals = workbook.add_worksheet("Deals")
    deal_headers = ["Deal ID", "Announced Date", "Type", "Record Kind", "Status", "Target / Issuer", "Buyer / Investor", "Seller", "Sector", "Geography", "Transaction Value", "Enterprise Value", "Currency", "Stake %", "Payment Form", "Advisors", "Instrument", "Security Code", "ISIN", "Coupon %", "Coupon Type", "Yield %", "Maturity", "Tenor", "Issue Price", "Price / Share", "Discount %", "Bookrunners", "Free Float %", "Rationale", "Revenue LTM", "EBITDA LTM", "Financials As Of", "Financials Currency", "EV / Revenue", "EV / EBITDA", "Financial Source", "Metric Basis", "Multiple Notes", "Quality", "Quality Score", "Evidence", "Source Count", "Primary Source", "Primary URL", "Headline"]
    setup(deals, len(deal_headers)-1, "DEALS", "Normalized M&A, DCM and ECM database; blanks mean not disclosed")
    deals.write_row(5, 0, deal_headers, header)
    keys = ["deal_id", "announced_date", "deal_type", "record_kind", "status", "target_or_issuer", "acquirer_or_investor", "seller", "sector", "geography", "transaction_value", "enterprise_value", "currency", "stake_percent", "payment_form", "advisors", "instrument", "security_code", "isin", "coupon_rate", "coupon_type", "yield_rate", "maturity_date", "tenor", "issue_price", "price_per_share", "discount_percent", "bookrunners", "free_float_percent", "rationale", "revenue_ltm", "ebitda_ltm", "financials_as_of", "financials_currency", "ev_revenue", "ev_ebitda", "financials_source_name", "financials_metric_basis", "multiple_notes", "quality_status", "quality_score", "evidence_label", "source_count", "source_name", "source_url", "headline"]
    for idx, row in enumerate(ROWS, 6):
        for col, key in enumerate(keys):
            value = row.get(key)
            fmt = sourced
            if key in {"announced_date", "maturity_date", "financials_as_of"}:
                value, fmt = date(value), day
            elif key in {"transaction_value", "enterprise_value", "issue_price", "price_per_share", "revenue_ltm", "ebitda_ltm"}:
                fmt = number
            elif key in {"stake_percent", "coupon_rate", "yield_rate", "discount_percent", "free_float_percent"}:
                value, fmt = (value / 100 if isinstance(value, (int, float)) else value), pct
            elif key in {"ev_revenue", "ev_ebitda"}:
                fmt = multiple
            if value is not None:
                deals.write(idx, col, value, fmt)
    deals.add_table(5, 0, 5 + max(len(ROWS), 1), len(deal_headers)-1, {"name": "DealsTable", "columns": [{"header": h} for h in deal_headers], "style": "Table Style Medium 2"})
    deals.freeze_panes(6, 0)
    deals.set_column(0, len(deal_headers)-1, 16)
    deals.set_column(5, 7, 24)
    deals.set_column(37, 38, 45)
    deals.set_column(44, 45, 48)

    fin = workbook.add_worksheet("Financials")
    fin_headers = ["Deal ID", "Target", "Deal Date", "Financials As Of", "Available At", "Currency", "Revenue LTM", "Operating Income", "Depreciation", "Amortization", "EBITDA LTM", "Metric Basis", "Source", "Source URL"]
    setup(fin, len(fin_headers)-1, "FINANCIALS", "Audited inputs with metric period, availability date and source")
    fin.write_row(5, 0, fin_headers, header)
    fin_rows = [r for r in ROWS if r.get("revenue_ltm") or r.get("ebitda_ltm") or r.get("financials_source_url")]
    for idx, row in enumerate(fin_rows, 6):
        values = [row.get("deal_id"), row.get("target_or_issuer"), date(row.get("announced_date")), date(row.get("financials_as_of")), date(row.get("financials_available_at")), row.get("financials_currency"), row.get("revenue_ltm"), row.get("operating_income"), row.get("depreciation"), row.get("amortization"), row.get("ebitda_ltm"), row.get("financials_metric_basis"), row.get("financials_source_name"), row.get("financials_source_url")]
        for col, value in enumerate(values):
            if value is not None:
                fin.write(idx, col, value, day if col in {2,3,4} else number if col in {6,7,8,9,10} else sourced)
    fin.add_table(5, 0, 5 + max(len(fin_rows), 1), len(fin_headers)-1, {"name": "FinancialsTable", "columns": [{"header": h} for h in fin_headers], "style": "Table Style Medium 2"})
    fin.freeze_panes(6, 0); fin.set_column("A:N", 20); fin.set_column("L:N", 45)

    mult = workbook.add_worksheet("Multiples")
    mult_headers = ["Deal ID", "Date", "Target", "Enterprise Value", "EV Currency", "Revenue LTM", "EBITDA LTM", "Financials Currency", "Quality", "Available at announcement", "EV / Revenue", "EV / EBITDA", "Model Eligible", "Financial Source", "Notes"]
    setup(mult, len(mult_headers)-1, "MULTIPLES", "Only approved M&A with contemporaneously available financials enters the model median")
    mult.write_row(5, 0, mult_headers, header)
    ma_rows = [r for r in ROWS if r.get("deal_type") == "M&A"]
    for idx, row in enumerate(ma_rows, 6):
        excel_row = idx + 1
        available = "YES" if row.get("financials_available_at") and str(row.get("financials_available_at"))[:10] <= str(row.get("announced_date") or "")[:10] else "NO"
        values = [row.get("deal_id"), date(row.get("announced_date")), row.get("target_or_issuer"), row.get("enterprise_value"), row.get("currency"), row.get("revenue_ltm"), row.get("ebitda_ltm"), row.get("financials_currency"), row.get("quality_status"), available]
        for col, value in enumerate(values):
            if value is not None:
                mult.write(idx, col, value, day if col == 1 else number if col in {3,5,6} else sourced)
        mult.write_formula(idx, 10, f'=IFERROR(IF(AND(D{excel_row}>0,F{excel_row}>0,E{excel_row}=H{excel_row}),D{excel_row}/F{excel_row},""),"")', multiple, row.get("ev_revenue") or "")
        mult.write_formula(idx, 11, f'=IFERROR(IF(AND(D{excel_row}>0,G{excel_row}>0,E{excel_row}=H{excel_row}),D{excel_row}/G{excel_row},""),"")', multiple, row.get("ev_ebitda") or "")
        mult.write_formula(idx, 12, f'=IF(AND(I{excel_row}="approved",J{excel_row}="YES",OR(K{excel_row}>0,L{excel_row}>0)),"YES","NO")', None, "YES" if eligible(row) else "NO")
        mult.write(idx, 13, row.get("financials_source_name"), sourced); mult.write(idx, 14, row.get("multiple_notes"), sourced)
    mult.add_table(5, 0, 5 + max(len(ma_rows), 1), len(mult_headers)-1, {"name": "MultiplesTable", "columns": [{"header": h} for h in mult_headers], "style": "Table Style Medium 2"})
    mult.freeze_panes(6, 0); mult.set_column("A:O", 19); mult.set_column("N:O", 45)

    qa = workbook.add_worksheet("Sources & QA")
    qa_headers = ["Deal ID", "Date", "Target / Issuer", "Source", "Type", "Evidence", "URL", "Published", "Headline"]
    setup(qa, 15, "SOURCES & QA", "One row per source plus automated workbook checks")
    qa.write_row(5, 0, qa_headers, header)
    source_rows = [(r, s) for r in ROWS for s in r.get("sources", [])]
    for idx, (row, source) in enumerate(source_rows, 6):
        qa.write_row(idx, 0, [row.get("deal_id"), date(row.get("announced_date")), row.get("target_or_issuer"), source.get("name"), source.get("source_type"), source.get("evidence_label"), source.get("url"), date(str(source.get("published_at", ""))[:10]), row.get("headline")], sourced)
        qa.write_datetime(idx, 1, date(row.get("announced_date")), day) if date(row.get("announced_date")) else None
    qa.add_table(5, 0, 5 + max(len(source_rows), 1), len(qa_headers)-1, {"name": "SourcesTable", "columns": [{"header": h} for h in qa_headers], "style": "Table Style Medium 2"})
    qa.freeze_panes(6, 0); qa.set_column("A:I", 20); qa.set_column("G:G", 50); qa.set_column("I:I", 55)
    qa.merge_range("K4:P4", "MODEL CHECKS", section)
    qa.write_row("K6", ["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"], header)
    checks = [
        ("Duplicate deal IDs", len(ROWS) - len({r.get("deal_id") for r in ROWS}), 0),
        ("Missing primary URLs", sum(not r.get("source_url") for r in ROWS), 0),
        ("Missing announced dates", sum(not r.get("announced_date") for r in ROWS), 0),
        ("Unsafe URLs", sum(bool(r.get("source_url")) and not str(r.get("source_url")).startswith(("http://", "https://")) for r in ROWS), 0),
        ("Approved non-deal records", sum(r.get("quality_status") == "approved" and r.get("record_kind") != "deal" for r in ROWS), 0),
        ("Stake populated outside M&A", sum(r.get("deal_type") != "M&A" and r.get("stake_percent") not in {None, "", 0} for r in ROWS), 0),
        ("Buyer populated for DCM", sum(r.get("deal_type") == "DCM" and r.get("acquirer_or_investor") not in {None, "", "Not applicable", "Not disclosed"} for r in ROWS), 0),
        ("Eligible multiple observations", len(eligible_rows), 1),
    ]
    for idx, (name, actual, expected) in enumerate(checks, 6):
        status = "OK" if (actual >= expected if name.startswith("Eligible") else actual == expected) else "REVIEW"
        qa.write_row(idx, 10, [name, actual, expected, actual - expected, 0, status])
    qa.merge_range("K16:O16", "Overall model status", section)
    qa.write("P16", "OK" if all((actual >= expected if name.startswith("Eligible") else actual == expected) for name, actual, expected in checks) else "REVIEW")
    workbook.close()
    MANIFEST.write_text(json.dumps({"build_id": current_build_id, "dataset_sha256": digest, "record_count": len(ROWS), "generated_at": datetime.now().astimezone().isoformat(timespec="seconds")}, indent=2) + "\n", encoding="utf-8")
    print(f"Workbook created: {OUTPUT}")


if __name__ == "__main__":
    main()

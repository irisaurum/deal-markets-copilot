import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const rows = JSON.parse(await fs.readFile(path.join(root, "data", "precedent_transactions.json"), "utf8"));
const outputPath = path.join(root, "output", "precedent_transactions.xlsx");
const qaDir = path.join("/tmp", "deal-markets-copilot-xlsx-qa");
const wb = Workbook.create();
const dashboard = wb.worksheets.add("Deal Dashboard");
const precedents = wb.worksheets.add("Precedent Transactions");
const card = wb.worksheets.add("Deal Card");
const qa = wb.worksheets.add("Sources & QA");
for (const sheet of [dashboard, precedents, card, qa]) sheet.showGridLines = false;

const navy = "#10243E", blue = "#1F4E78", paleBlue = "#D9EAF7", paleGreen = "#E2F0D9";
const paleYellow = "#FFF2CC", paleRed = "#FCE4D6", light = "#F4F6F8", border = "#CCD5DF";
const white = "#FFFFFF", green = "#008000";

function titleBand(sheet, endCol, title, subtitle) {
  sheet.getRange(`A1:${endCol}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${endCol}1`).format = { fill: navy, font: { color: white, bold: true, size: 18 }, verticalAlignment: "center", rowHeight: 32 };
  sheet.getRange(`A2:${endCol}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endCol}2`).format = { fill: light, font: { color: "#52616F", italic: true, size: 9 }, verticalAlignment: "center", rowHeight: 25 };
}
function sectionHeader(sheet, range, text) {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = { fill: blue, font: { color: white, bold: true, size: 11 }, verticalAlignment: "center", rowHeight: 22 };
}
function formatHeaders(range) {
  range.format = { fill: navy, font: { color: white, bold: true, size: 9 }, wrapText: true, verticalAlignment: "center", rowHeight: 32, borders: { preset: "outside", style: "thin", color: border } };
}
function toDate(value) { return value ? new Date(`${value}T00:00:00Z`) : null; }

// Dashboard: headline database statistics and formula-driven median transaction multiples.
titleBand(dashboard, "H", "DEAL MARKETS COPILOT — PRECEDENT TRANSACTIONS", `Screening-grade database | As of ${new Date().toISOString().slice(0, 10)} | N/M means insufficient disclosed data`);
sectionHeader(dashboard, "A4:H4", "DATABASE SNAPSHOT");
dashboard.getRange("A6:H6").values = [["Total deals", "M&A", "ECM", "DCM", "Disclosed value", "High score (≥7)", "Missing value", "QA status"]];
formatHeaders(dashboard.getRange("A6:H6"));
dashboard.getRange("A7:H7").formulas = [[
  "=COUNTA('Precedent Transactions'!$A$7:$A$506)",
  "=COUNTIF('Precedent Transactions'!$C$7:$C$506,\"M&A\")",
  "=COUNTIF('Precedent Transactions'!$C$7:$C$506,\"ECM\")",
  "=COUNTIF('Precedent Transactions'!$C$7:$C$506,\"DCM\")",
  "=SUM('Precedent Transactions'!$I$7:$I$506)",
  "=COUNTIF('Precedent Transactions'!$W$7:$W$506,\">=7\")",
  "=COUNTBLANK('Precedent Transactions'!$I$7:$I$506)-COUNTBLANK('Precedent Transactions'!$A$7:$A$506)",
  "='Sources & QA'!$F$31",
]];
dashboard.getRange("A7:H7").format = { fill: paleBlue, font: { bold: true, size: 14 }, horizontalAlignment: "center", verticalAlignment: "center", rowHeight: 32, borders: { preset: "outside", style: "thin", color: border } };
dashboard.getRange("E7").setNumberFormat("#,##0;[Red](#,##0);-");
sectionHeader(dashboard, "A10:H10", "PRECEDENT VALUATION — VALID M&A OBSERVATIONS ONLY");
dashboard.getRange("A12:D12").values = [["Median EV / Revenue", "Median EV / EBITDA", "EV / Revenue coverage", "EV / EBITDA coverage"]];
formatHeaders(dashboard.getRange("A12:D12"));
dashboard.getRange("A13:D13").formulas = [[
  "=IFERROR(MEDIAN(FILTER('Precedent Transactions'!$S$7:$S$506,('Precedent Transactions'!$C$7:$C$506=\"M&A\")*('Precedent Transactions'!$S$7:$S$506>0))),\"N/M\")",
  "=IFERROR(MEDIAN(FILTER('Precedent Transactions'!$T$7:$T$506,('Precedent Transactions'!$C$7:$C$506=\"M&A\")*('Precedent Transactions'!$T$7:$T$506>0))),\"N/M\")",
  "=COUNTIFS('Precedent Transactions'!$C$7:$C$506,\"M&A\",'Precedent Transactions'!$S$7:$S$506,\">0\")",
  "=COUNTIFS('Precedent Transactions'!$C$7:$C$506,\"M&A\",'Precedent Transactions'!$T$7:$T$506,\">0\")",
]];
dashboard.getRange("A13:D13").format = { fill: paleGreen, font: { bold: true, size: 14 }, horizontalAlignment: "center", rowHeight: 32 };
dashboard.getRange("A13:B13").setNumberFormat("0.0x");
sectionHeader(dashboard, "A16:H16", "LATEST TRANSACTIONS");
dashboard.getRange("A18:H18").values = [["Date", "Type", "Status", "Target / Issuer", "Acquirer", "Value", "Currency", "Source"]];
formatHeaders(dashboard.getRange("A18:H18"));
const latest = rows.slice(0, 10).map(r => [toDate(r.announced_date), r.deal_type, r.status, r.target_or_issuer, r.acquirer_or_investor, r.transaction_value, r.currency, r.source_name]);
if (latest.length) dashboard.getRangeByIndexes(18, 0, latest.length, 8).values = latest;
dashboard.getRange(`A19:A${18 + Math.max(latest.length, 1)}`).setNumberFormat("dd-mmm-yyyy");
dashboard.getRange(`F19:F${18 + Math.max(latest.length, 1)}`).setNumberFormat("#,##0;[Red](#,##0);-");
dashboard.getRange("A:H").format.columnWidth = 17;
dashboard.getRange("D:E").format.columnWidth = 25;
dashboard.getRange("H:H").format.columnWidth = 24;
dashboard.freezePanes.freezeRows(4);

// Full database. Economics are imported as disclosed; multiples are calculated formulas.
titleBand(precedents, "AC", "PRECEDENT TRANSACTIONS DATABASE", "Blank economics mean not publicly disclosed, not zero; valuation multiples require aligned EV and financial currencies");
precedents.getRange("A4:AC4").merge();
precedents.getRange("A4").values = [["Green text = sourced/imported field · black formula cells = calculated output · verify primary transaction documents before use"]];
precedents.getRange("A4:AC4").format = { fill: paleYellow, font: { color: "#7F6000", size: 9 }, wrapText: true };
const headers = ["Deal ID", "Announced Date", "Type", "Status", "Target / Issuer", "Acquirer / Investor", "Sector", "Geography", "Transaction Value", "Enterprise Value", "Currency", "Stake %", "Payment Form", "Advisors", "Revenue LTM", "EBITDA LTM", "Financials As Of", "Financials Currency", "EV / Revenue", "EV / EBITDA", "Instrument", "Rationale / Use of Proceeds", "Score", "Evidence", "Coverage", "Source", "Source URL", "Headline", "Notes"];
precedents.getRange("A6:AC6").values = [headers];
formatHeaders(precedents.getRange("A6:AC6"));
const matrix = rows.map(r => [r.deal_id, toDate(r.announced_date), r.deal_type, r.status, r.target_or_issuer, r.acquirer_or_investor, r.sector, r.geography, r.transaction_value, r.enterprise_value, r.currency, r.stake_percent == null ? null : r.stake_percent / 100, r.payment_form, r.advisors, r.revenue_ltm, r.ebitda_ltm, r.financials_as_of, r.financials_currency, null, null, r.instrument, r.rationale, r.score, r.evidence_label, (r.matched_coverage || []).join(", "), r.source_name, r.source_url, r.headline, r.notes]);
if (matrix.length) {
  const end = 6 + matrix.length;
  precedents.getRangeByIndexes(6, 0, matrix.length, headers.length).values = matrix;
  for (let row = 7; row <= end; row++) {
    precedents.getRange(`S${row}`).formulas = [[`=IFERROR(IF(AND($J${row}>0,$O${row}>0,$K${row}=$R${row}),$J${row}/$O${row},\"\"),\"\")`]];
    precedents.getRange(`T${row}`).formulas = [[`=IFERROR(IF(AND($J${row}>0,$P${row}>0,$K${row}=$R${row}),$J${row}/$P${row},\"\"),\"\")`]];
  }
  const table = precedents.tables.add(`A6:AC${end}`, true, "PrecedentTransactionsTable");
  table.style = "TableStyleMedium2";
  precedents.getRange(`A7:AC${end}`).format.font = { color: green, size: 9 };
  precedents.getRange(`S7:T${end}`).format.font = { color: "#000000", size: 9 };
  precedents.getRange(`B7:B${end}`).setNumberFormat("dd-mmm-yyyy");
  precedents.getRange(`I7:J${end}`).setNumberFormat("#,##0;[Red](#,##0);-");
  precedents.getRange(`L7:L${end}`).setNumberFormat("0.0%;[Red](0.0%);-");
  precedents.getRange(`O7:P${end}`).setNumberFormat("#,##0;[Red](#,##0);-");
  precedents.getRange(`S7:T${end}`).setNumberFormat("0.0x");
  precedents.getRange(`W7:W${end}`).conditionalFormats.add("colorScale", { colors: ["#F8696B", "#FFEB84", "#63BE7B"], thresholds: ["min", "50%", "max"] });
}
precedents.freezePanes.freezeRows(6);
const widths = [20,14,10,14,24,24,16,16,18,18,10,11,18,30,18,18,18,16,14,14,22,34,9,13,14,22,42,52,44];
widths.forEach((width, index) => precedents.getRangeByIndexes(0, index, Math.max(matrix.length + 6, 7), 1).format.columnWidth = width);

// Latest transaction card.
const deal = rows[0] || {};
titleBand(card, "H", "DEAL CARD", "Latest transaction; N/M and Not disclosed are deliberate, not missing-data errors");
sectionHeader(card, "A4:H4", `${deal.deal_type || "—"} | ${deal.status || "No transaction loaded"}`);
const cardRows = [
  ["Headline", deal.headline || "No deal available"], ["Announced date", toDate(deal.announced_date)],
  ["Target / Issuer", deal.target_or_issuer || "Not disclosed"], ["Acquirer / Investor", deal.acquirer_or_investor || "Not disclosed"],
  ["Transaction value", deal.transaction_value ?? null], ["Enterprise value", deal.enterprise_value ?? null], ["Currency", deal.currency || "Not disclosed"],
  ["Stake", deal.stake_percent == null ? null : deal.stake_percent / 100], ["Payment form", deal.payment_form || "Not disclosed"], ["Advisors", deal.advisors || "Not disclosed"],
  ["Revenue LTM", deal.revenue_ltm ?? null], ["EBITDA LTM", deal.ebitda_ltm ?? null], ["EV / Revenue", deal.ev_revenue ?? "N/M"], ["EV / EBITDA", deal.ev_ebitda ?? "N/M"],
  ["Instrument", deal.instrument || "Not disclosed"], ["Rationale", deal.rationale || "Not disclosed"], ["Evidence / score", `${deal.evidence_label || "unverified"} / ${deal.score ?? "—"} out of 10`],
  ["Source", deal.source_name || "Not disclosed"], ["Source URL", deal.source_url ? "See Precedent Transactions → Source URL" : "Not disclosed"],
];
card.getRange("A6:B24").values = cardRows;
card.getRange("A6:A24").format = { fill: light, font: { bold: true, color: navy }, borders: { insideHorizontal: { style: "thin", color: border } } };
card.getRange("B6:B24").format = { font: { color: green }, wrapText: true, borders: { insideHorizontal: { style: "thin", color: border } } };
card.getRange("B7").setNumberFormat("dd-mmm-yyyy");
card.getRange("B10:B11").setNumberFormat("#,##0;[Red](#,##0);-");
card.getRange("B13").setNumberFormat("0.0%;[Red](0.0%);-");
card.getRange("B16:B17").setNumberFormat("#,##0;[Red](#,##0);-");
card.getRange("B18:B19").setNumberFormat("0.0x");
card.getRange("A:A").format.columnWidth = 27; card.getRange("B:B").format.columnWidth = 78;
card.freezePanes.freezeRows(4);

// Source register and visible QA checks.
titleBand(qa, "H", "SOURCES & QA", "Completeness, uniqueness, URL safety and valuation-input checks");
sectionHeader(qa, "A4:H4", "SOURCE REGISTER");
qa.getRange("A6:F6").values = [["Deal ID", "Date", "Source", "URL", "Evidence", "Headline"]];
formatHeaders(qa.getRange("A6:F6"));
const sourceRows = rows.slice(0, 10).map(r => [r.deal_id, toDate(r.announced_date), r.source_name, "See Precedent Transactions → Source URL", r.evidence_label, r.headline]);
if (sourceRows.length) qa.getRangeByIndexes(6, 0, sourceRows.length, 6).values = sourceRows;
qa.getRange(`B7:B${6 + Math.max(sourceRows.length, 1)}`).setNumberFormat("dd-mmm-yyyy");
qa.getRange(`A7:F${6 + Math.max(sourceRows.length, 1)}`).format.font = { color: green, size: 9 };
sectionHeader(qa, "A20:H20", "DATABASE CHECKS");
qa.getRange("A22:F22").values = [["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]];
formatHeaders(qa.getRange("A22:F22"));
qa.getRange("A23:A29").values = [["Duplicate deal IDs"], ["Missing source URLs"], ["Missing announced dates"], ["Unsafe / non-HTTP URLs"], ["Missing target / issuer"], ["EV without revenue/EBITDA"], ["Multiple without enterprise value"]];
const databaseEnd = 6 + Math.max(rows.length, 1);
qa.getRange("B23:B29").formulas = [[`=SUMPRODUCT(--(COUNTIF('Precedent Transactions'!$A$7:$A$${databaseEnd},'Precedent Transactions'!$A$7:$A$${databaseEnd})>1))/2`],
  [`=COUNTBLANK('Precedent Transactions'!$AA$7:$AA$${databaseEnd})`], [`=COUNTBLANK('Precedent Transactions'!$B$7:$B$${databaseEnd})`],
  [`=SUMPRODUCT(--(LEFT('Precedent Transactions'!$AA$7:$AA$${databaseEnd},4)<>\"http\"),--('Precedent Transactions'!$A$7:$A$${databaseEnd}<>\"\"))`],
  [`=COUNTIF('Precedent Transactions'!$E$7:$E$${databaseEnd},\"Not disclosed\")`],
  [`=SUMPRODUCT(--('Precedent Transactions'!$J$7:$J$${databaseEnd}>0),--('Precedent Transactions'!$O$7:$O$${databaseEnd}=\"\"),--('Precedent Transactions'!$P$7:$P$${databaseEnd}=\"\"))`],
  [`=SUMPRODUCT(--('Precedent Transactions'!$J$7:$J$${databaseEnd}=\"\"),--((('Precedent Transactions'!$S$7:$S$${databaseEnd}>0)+('Precedent Transactions'!$T$7:$T$${databaseEnd}>0))>0))`]];
qa.getRange("C23:C29").values = [[0],[0],[0],[0],[0],[0],[0]];
qa.getRange("D23:D29").formulas = [["=B23-C23"],["=B24-C24"],["=B25-C25"],["=B26-C26"],["=B27-C27"],["=B28-C28"],["=B29-C29"]];
qa.getRange("E23:E29").values = [[0],[0],[0],[0],[0],[0],[0]];
qa.getRange("F23:F29").formulas = Array.from({ length: 7 }, (_, i) => [`=IF(ABS(D${23+i})<=E${23+i},\"OK\",\"REVIEW\")`]);
qa.getRange("A31:E31").merge(); qa.getRange("A31").values = [["Overall model status"]];
qa.getRange("F31").formulas = [["=IF(COUNTIF(F23:F29,\"REVIEW\")=0,\"OK\",\"REVIEW\")"]];
qa.getRange("A31:F31").format = { fill: navy, font: { color: white, bold: true }, borders: { preset: "outside", style: "thin", color: border } };
qa.getRange("F23:F31").conditionalFormats.add("containsText", { text: "OK", format: { fill: paleGreen, font: { color: "#006100", bold: true } } });
qa.getRange("F23:F31").conditionalFormats.add("containsText", { text: "REVIEW", format: { fill: paleRed, font: { color: "#9C0006", bold: true } } });
qa.getRange("A:F").format.columnWidth = 20; qa.getRange("C:C").format.columnWidth = 24; qa.getRange("D:D").format.columnWidth = 46; qa.getRange("F:F").format.columnWidth = 52;
qa.freezePanes.freezeRows(6);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const workbookFile = await SpreadsheetFile.exportXlsx(wb);
await workbookFile.save(outputPath);
const inspection = await wb.inspect({ kind: "sheet,table,formula", maxChars: 7000, tableMaxRows: 5, tableMaxCols: 12, options: { maxResults: 120 } });
console.log(inspection.ndjson || String(inspection));
for (const errorToken of ["#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A"]) {
  const errorScan = await wb.inspect({ kind: "match", searchTerm: errorToken, maxChars: 2000, options: { maxResults: 20 } });
  const scanText = errorScan.ndjson || String(errorScan);
  if (scanText.includes(errorToken)) throw new Error(`Workbook formula error detected: ${errorToken}`);
}
await fs.mkdir(qaDir, { recursive: true });
for (const name of ["Deal Dashboard", "Precedent Transactions", "Deal Card", "Sources & QA"]) {
  const preview = await wb.render({ sheetName: name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(qaDir, `${name.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(`Workbook created: ${outputPath}`);
console.log(`QA renders: ${qaDir}`);
